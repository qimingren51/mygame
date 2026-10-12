//! 游戏流程（docs/DESIGN.md 第 5 节）：应用层状态，以及一局之内的阶段（移植自网页版 sim/flow.ts）。
//!
//! 一局之内的阶段 [`SimPhase`] 是模拟内部的资源，不是 Bevy 的 State：State 要等到下一帧才切换，
//! 一帧里补跑几步时会多跑几步，实际游戏和不开窗口的重放就对不上了。只有 `Play` 时时间推进；
//! 其他阶段每步只处理界面发来的命令（选择、重抽、跳过、确认）。

use std::collections::VecDeque;

use bevy_ecs::prelude::*;
use bevy_ecs::system::SystemParam;
use bevy_state::prelude::*;

use lantern_content::Stat;
use lantern_core::Stream;

use crate::boss::Foes;
use crate::build::{Awaken, Build, Offer, apply_offer, offers, pick_weighted, roll_choices};
use crate::combat::{Area, Source, Strike, StrikeFx, Strikes, heal};
use crate::encounters::Encounters;
use crate::run::{Progress, RunMode, RunPlan};
use crate::stats::{Effects, Stats, StatsDirty, collect};
use crate::weapons::Arsenal;
use crate::{
    GameContent, Health, Player, Pos, RunSetup, SimCommand, SimCommands, SimEvent, SimOutbox, SimRng, Tick,
};

#[derive(States, Default, Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum AppState {
    /// 加载内容和资源
    #[default]
    Boot,
    Title,
    Run,
    Results,
}

/// 一局之内界面层面的状态。模拟只在 `Playing` 下运行；暂停不属于模拟，不进回放。
#[derive(SubStates, Default, Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[source(AppState = AppState::Run)]
pub enum RunState {
    #[default]
    Playing,
    Paused,
    /// 这一局结束（灯灭或天明），等待界面进入结算
    Over,
}

/// 一局之内模拟的阶段。
#[derive(Resource, Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum SimPhase {
    #[default]
    Play,
    /// 升级三选一
    LevelUp,
    /// 宝箱揭晓
    Chest,
    /// 进化演出
    Evolve,
    /// 点亮石灯笼后的三选一奖励
    Lantern,
    /// 货郎的摊子
    Shop,
    Over,
}

/// 这一步开始时是否处于 Play 阶段。本步其余系统都看它，阶段在步中切换也不影响本步。
#[derive(Resource, Clone, Copy, Debug, Default)]
pub struct StepGate {
    pub play: bool,
}

/// 演出停顿：Play 阶段里接下来这么多步时间不走（第一次发生某种反应时停 0.3 秒）。
/// 停顿在模拟里，回放和不开窗口的重放结果一样。
#[derive(Resource, Clone, Copy, Debug, Default)]
pub struct Hold(pub u32);

/// 宝箱的来历（界面显示不同的标题）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ChestSource {
    /// 精英掉落、天降宝箱
    Elite,
    /// 血祭坛
    Altar,
    /// 小头目：至少几连，优先升级最接近进化的法器
    MiniBoss,
    /// 货郎卖的
    Merchant,
}

/// 点灯奖励的一项。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LampReward {
    /// 回复生命
    Heal,
    /// 一次升级
    Level,
    /// 金币
    Gold,
}

/// 货郎的摊子：宝箱、灯坠三选一的价钱。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Shop {
    pub chest_cost: u32,
    pub charm_cost: u32,
}

/// 升级时给出的选项。
#[derive(Clone, Debug, PartialEq)]
pub struct Choice {
    pub offers: Vec<Offer>,
    /// 灵光一闪：多一个选项
    pub inspired: bool,
    /// 这次升到的等级
    pub level: u32,
}

/// 宝箱里开出的一项。`level` 是生效后的等级（新法器、新心法为 1，补给为 0）。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ChestItem {
    pub offer: Offer,
    pub level: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ChestReveal {
    pub items: Vec<ChestItem>,
    pub source: ChestSource,
}

/// 一局的结算。
#[derive(Clone, Debug, PartialEq)]
pub struct RunResult {
    pub won: bool,
    pub seconds: f32,
    pub kills: u32,
    pub level: u32,
    pub best_combo: u32,
    pub evolutions: u32,
    /// 灯油：合计与各项（存活、击杀、天明、石灯笼、额外）
    pub oil: u32,
    pub oil_parts: [u32; 5],
    /// 带出这一夜的金币
    pub gold: u32,
    /// 点亮的石灯笼、灯阵是否完整
    pub lanterns: u32,
    pub lamps_complete: bool,
}

/// 一局之内的流程状态。
#[derive(Resource, Clone, Debug, Default)]
pub struct Flow {
    pub choice: Option<Choice>,
    pub chest: Option<ChestReveal>,
    /// 正在演出进化的法器（在 [`Arsenal`] 里的位置）
    pub evolving: Option<usize>,
    pub chest_queue: VecDeque<ChestSource>,
    pub pending_evos: VecDeque<usize>,
    pub rerolls: u32,
    /// 剩余封印次数
    pub banishes: u32,
    /// 排队的点灯奖励与当前的三选一
    pub lamp_queue: u32,
    pub lamp: Option<Vec<LampReward>>,
    /// 正在逛的货郎
    pub shop: Option<Shop>,
    /// 击败夜主后进入结算的时刻
    pub won_at: Option<f32>,
    /// 局内额外得到的灯油（跳过升级、补给、金蟾）
    pub oil_bonus: u32,
    pub result: Option<RunResult>,
}

/// 处理流程需要的全部资源。
#[derive(SystemParam)]
pub(crate) struct FlowParams<'w, 's> {
    content: Res<'w, GameContent>,
    setup: Res<'w, RunSetup>,
    plan: ResMut<'w, RunPlan>,
    tick: Res<'w, Tick>,
    phase: ResMut<'w, SimPhase>,
    flow: ResMut<'w, Flow>,
    arsenal: ResMut<'w, Arsenal>,
    build: ResMut<'w, Build>,
    stats: ResMut<'w, Stats>,
    effects: ResMut<'w, Effects>,
    encounters: Res<'w, Encounters>,
    progress: ResMut<'w, Progress>,
    rng: ResMut<'w, SimRng>,
    dirty: ResMut<'w, StatsDirty>,
    outbox: ResMut<'w, SimOutbox>,
    lanterns: Res<'w, crate::lanterns::Lanterns>,
    coins: ResMut<'w, crate::gold::Coins>,
    player: Query<'w, 's, &'static mut Health, With<Player>>,
}

impl FlowParams<'_, '_> {
    fn secs(&self) -> f32 {
        self.tick.secs()
    }

    /// 应用一个选项，重算共鸣和属性。
    fn apply(&mut self, offer: Offer) {
        let c = &self.content.0;
        if let Some(k) = apply_offer(c, &mut self.arsenal, &mut self.build, offer) {
            self.flow.pending_evos.push_back(k);
        }
        match offer {
            Offer::Heal => {
                let amount = self.stats.max_hp() * c.run.choices.heal * self.stats.get(Stat::Healing);
                for mut h in &mut self.player {
                    heal(&mut h, amount, &mut self.outbox);
                }
            }
            Offer::Oil => self.flow.oil_bonus += c.run.choices.oil,
            _ => {}
        }
        for a in self.build.compute_resonance(c, &self.arsenal) {
            self.outbox.0.push(match a {
                Awaken::Tier { element, tier } => SimEvent::Resonance { element, tier },
                Awaken::Sheng(i) => SimEvent::Sheng { index: i },
                Awaken::Taiji => SimEvent::Taiji,
            });
        }
        self.refresh();
    }

    /// 立即重算属性（下一个选项、宝箱的下一项要用到新的构筑）。
    fn refresh(&mut self) {
        let c = &self.content.0;
        let (stats, mut effects) =
            collect(c, &self.setup, &self.build, self.encounters.buff.map(|b| b.0), self.progress.level);
        for t in &mut effects.periodic {
            if let Some(old) = self.effects.periodic.iter().find(|o| o.key == t.key) {
                t.elapsed = old.elapsed;
            }
        }
        let prev_max = self.stats.max_hp();
        *self.stats = stats;
        *self.effects = effects;
        self.dirty.0 = false;
        let max = self.stats.max_hp();
        for mut h in &mut self.player {
            if max > prev_max {
                h.hp += max - prev_max;
            }
            h.max = max;
            h.hp = h.hp.min(max);
        }
    }

    fn open_level_up(&mut self) {
        let c = &self.content.0;
        self.progress.pending_levels -= 1;
        let secs = self.secs();
        let (offers, inspired) = roll_choices(
            c,
            &self.arsenal,
            &mut self.build,
            &self.stats,
            secs,
            self.rng.0.get(Stream::Choice),
            true,
        );
        let level = self.progress.level - self.progress.pending_levels;
        self.flow.choice = Some(Choice { offers, inspired, level });
        *self.phase = SimPhase::LevelUp;
    }

    fn open_chest(&mut self) {
        let Some(source) = self.flow.chest_queue.pop_front() else { return };
        let content = self.content.0.clone();
        let c = &*content;
        let r = self.rng.0.get(Stream::Chest).next_f32() + self.stats.get(Stat::ChestLuck);
        let by_odds = c.run.choices.chest_odds.iter().find(|(t, _)| r > *t).map_or(1, |&(_, n)| n);
        let mut n = by_odds.max(self.stats.get(Stat::ChestMin).round() as u32);
        if source == ChestSource::MiniBoss {
            n = n.max(miniboss_chest_min(c));
        }
        // 每个宝箱附带金币
        let (lo, hi) = c.run.gold.chest;
        let gold = self.rng.0.get(Stream::Chest).range_f32(lo as f32, hi as f32 + 0.999).floor();
        self.progress.gold += gold * self.stats.get(Stat::GoldGain);
        let mut items = Vec::with_capacity(n as usize);
        for k in 0..n {
            // 宝箱只给升级和进化；都满了才放开新法器、新心法
            let all = offers(c, &self.arsenal, &self.build, self.secs());
            let ups: Vec<_> = all.iter().copied().filter(|(o, _)| o.is_upgrade()).collect();
            let pool = if ups.is_empty() { &all } else { &ups };
            // 小头目的宝箱：第一项优先升级最接近进化的法器
            let priority = if source == ChestSource::MiniBoss && k == 0 {
                closest_to_evolution(&self.arsenal, pool)
            } else {
                None
            };
            let offer = priority.unwrap_or_else(|| {
                pick_weighted(self.rng.0.get(Stream::Chest), pool, 1).first().copied().unwrap_or(Offer::Oil)
            });
            self.apply(offer);
            let level = match offer {
                Offer::Evolve(k) | Offer::WeaponUp(k) => self.arsenal.0[k].level,
                Offer::PassiveUp(k) => self.build.passives[k].level,
                Offer::NewWeapon(_) | Offer::NewPassive(_) => 1,
                Offer::Heal | Offer::Oil => 0,
            };
            items.push(crate::flow::ChestItem { offer, level });
        }
        self.outbox.0.push(SimEvent::ChestOpened { count: n as u8, source });
        self.flow.chest = Some(ChestReveal { items, source });
        *self.phase = SimPhase::Chest;
    }

    /// 一个选择结束：先演出待进化，再处理剩余升级，再开排队的宝箱、点灯奖励，最后回到 Play。
    fn after_choice(&mut self) {
        self.flow.choice = None;
        self.flow.chest = None;
        self.flow.evolving = None;
        self.flow.lamp = None;
        self.flow.shop = None;
        if let Some(k) = self.flow.pending_evos.pop_front() {
            self.flow.evolving = Some(k);
            *self.phase = SimPhase::Evolve;
            self.outbox.0.push(SimEvent::Evolve { weapon: self.arsenal.0[k].def as u16 });
        } else {
            self.next_pending();
        }
    }

    /// 打开排队中的下一个选择；都没有就回到 Play。
    fn next_pending(&mut self) {
        if self.progress.pending_levels > 0 {
            self.open_level_up();
        } else if !self.flow.chest_queue.is_empty() {
            self.open_chest();
        } else if self.flow.lamp_queue > 0 {
            self.open_lamp();
        } else {
            *self.phase = SimPhase::Play;
        }
    }

    /// 点灯奖励：回复生命 / 一次升级 / 金币（无法回复生命时不给回复）。
    fn open_lamp(&mut self) {
        self.flow.lamp_queue -= 1;
        let mut v = Vec::with_capacity(3);
        if self.stats.can_heal() {
            v.push(LampReward::Heal);
        }
        v.push(LampReward::Level);
        v.push(LampReward::Gold);
        self.flow.lamp = Some(v);
        *self.phase = SimPhase::Lantern;
    }

    fn apply_lamp(&mut self, r: LampReward) {
        let c = &self.content.0;
        match r {
            LampReward::Heal => {
                let amount = self.stats.max_hp() * c.run.lanterns.heal * self.stats.get(Stat::Healing);
                for mut h in &mut self.player {
                    heal(&mut h, amount, &mut self.outbox);
                }
            }
            LampReward::Level => {
                self.progress.level += 1;
                self.progress.pending_levels += 1;
                self.dirty.0 = true;
                self.outbox.0.push(SimEvent::LevelUp { level: self.progress.level });
            }
            LampReward::Gold => {
                self.progress.gold += c.run.lanterns.gold as f32 * self.stats.get(Stat::GoldGain);
            }
        }
    }

    fn end(&mut self, won: bool) {
        let c = &self.content.0;
        let o = &c.run.oil;
        let secs = self.secs();
        let lit = self.lanterns.lit();
        let parts = [
            (secs.min(o.max_seconds) * o.per_second).floor() as u32,
            (self.progress.kills as f32 * o.per_kill).floor() as u32,
            if won { o.win } else { 0 },
            lit * c.run.lanterns.oil,
            self.flow.oil_bonus,
        ];
        let oil = (parts.iter().sum::<u32>() as f32 * self.stats.get(Stat::OilGain)).round() as u32;
        // 天明时地上剩下的金币全部飞来；倒下时已经捡到的全部保留
        if won {
            self.progress.gold += self.coins.total();
            self.coins.0.clear();
        }
        let gold = self.progress.gold.floor() as u32;
        self.flow.result = Some(RunResult {
            won,
            seconds: secs,
            kills: self.progress.kills,
            level: self.progress.level,
            best_combo: self.progress.best_combo,
            evolutions: self.build.evolutions,
            oil,
            oil_parts: parts,
            gold,
            lanterns: lit,
            lamps_complete: self.lanterns.complete(),
        });
        self.flow.choice = None;
        *self.phase = SimPhase::Over;
        self.outbox.0.push(SimEvent::RunOver { won });
    }
}

/// 每步开头：记下本步是否推进时间。
pub(crate) fn begin_step(phase: Res<SimPhase>, mut hold: ResMut<Hold>, mut gate: ResMut<StepGate>) {
    let play = *phase == SimPhase::Play;
    gate.play = play && hold.0 == 0;
    if play && hold.0 > 0 {
        hold.0 -= 1;
    }
}

/// 本步推进时间（开头处于 Play 阶段）。
pub(crate) fn playing(gate: Option<Res<StepGate>>) -> bool {
    gate.is_some_and(|g| g.play)
}

/// 正在进行一局，而且还没结束。
pub(crate) fn not_over(phase: Option<Res<SimPhase>>) -> bool {
    phase.is_some_and(|p| *p != SimPhase::Over)
}

/// 处理命令：Play 阶段处理闪避、燃灯；选择阶段处理选择、重抽、跳过、确认。其他命令丢弃。
pub(crate) fn handle_commands(
    mut fp: FlowParams,
    mut commands: ResMut<SimCommands>,
    mut strikes: ResMut<Strikes>,
    mut foes: ResMut<Foes>,
    mut dash_hits: ResMut<crate::player::DashHits>,
    mut player: Query<(&Pos, &mut Player)>,
) {
    for cmd in std::mem::take(&mut commands.0) {
        match (*fp.phase, cmd) {
            (_, SimCommand::BenchTarget(n)) => {
                if let RunMode::Bench { enemies } = &mut fp.plan.mode {
                    *enemies = n;
                }
            }
            (SimPhase::Play, SimCommand::Dash) => {
                let dash = &fp.content.0.player.dash;
                for (pos, mut p) in &mut player {
                    if p.dash_ready == 0 || p.dash_t > 0.0 {
                        continue;
                    }
                    p.dash_ready -= 1;
                    p.dash_t = dash.duration;
                    p.dash_vel = p.facing * dash.speed * fp.stats.get(Stat::DashDistance);
                    p.iframe = p.iframe.max(dash.iframe);
                    if p.dash_cd <= 0.0 {
                        p.dash_cd = fp.stats.get(Stat::DashCooldown);
                    }
                    dash_hits.0.clear();
                    fp.outbox.0.push(SimEvent::Dash { pos: pos.0 });
                }
            }
            (SimPhase::Play, SimCommand::Ult) => {
                if fp.progress.ult < 1.0 {
                    continue;
                }
                fp.progress.ult = 0.0;
                let u = &fp.content.0.player.ult;
                let minute = fp.secs() / 60.0;
                for (pos, _) in &player {
                    let mut s = Strike::new(
                        pos.0,
                        Area::Screen(60.0),
                        u.damage.at(minute),
                        Source::Ult,
                        StrikeFx::Ult,
                    );
                    s.knockback = u.knockback;
                    s.boss_fraction = u.boss_fraction;
                    strikes.0.push(s);
                }
                foes.0.clear();
                fp.outbox.0.push(SimEvent::Ult);
            }
            (SimPhase::LevelUp, SimCommand::Choose(i)) => {
                let Some(offer) = fp.flow.choice.as_ref().and_then(|c| c.offers.get(i as usize)).copied()
                else {
                    continue;
                };
                fp.apply(offer);
                fp.after_choice();
            }
            (SimPhase::LevelUp, SimCommand::Reroll) => {
                if fp.flow.rerolls == 0 {
                    continue;
                }
                fp.flow.rerolls -= 1;
                let c = &fp.content.0;
                let secs = fp.secs();
                let (offers, inspired) = roll_choices(
                    c,
                    &fp.arsenal,
                    &mut fp.build,
                    &fp.stats,
                    secs,
                    fp.rng.0.get(Stream::Choice),
                    false,
                );
                if let Some(choice) = &mut fp.flow.choice {
                    choice.offers = offers;
                    choice.inspired = inspired;
                }
            }
            (SimPhase::LevelUp, SimCommand::Banish(i)) => {
                let Some(offer) = fp.flow.choice.as_ref().and_then(|c| c.offers.get(i as usize)).copied()
                else {
                    continue;
                };
                let Some(ban) = offer.banned(&fp.arsenal, &fp.build) else { continue };
                if fp.flow.banishes == 0 {
                    continue;
                }
                fp.flow.banishes -= 1;
                fp.build.banished.push(ban);
                // 被封印的那一项换成新抽的一项，其余不变
                let content = fp.content.0.clone();
                let c = &*content;
                let pool: Vec<_> = offers(c, &fp.arsenal, &fp.build, fp.secs())
                    .into_iter()
                    .filter(|(o, _)| fp.flow.choice.as_ref().is_none_or(|ch| !ch.offers.contains(o)))
                    .collect();
                let new = pick_weighted(fp.rng.0.get(Stream::Choice), &pool, 1).first().copied();
                if let Some(choice) = &mut fp.flow.choice {
                    match new {
                        Some(o) => choice.offers[i as usize] = o,
                        None => {
                            choice.offers.remove(i as usize);
                        }
                    }
                    if choice.offers.is_empty() {
                        choice.offers.push(Offer::Oil);
                    }
                }
                fp.outbox.0.push(SimEvent::Banished);
            }
            (SimPhase::LevelUp, SimCommand::Skip) => {
                fp.flow.oil_bonus += fp.content.0.run.choices.skip_oil;
                fp.after_choice();
            }
            (SimPhase::Chest | SimPhase::Evolve, SimCommand::Ack) => fp.after_choice(),
            (SimPhase::Lantern, SimCommand::Choose(i)) => {
                let Some(r) = fp.flow.lamp.as_ref().and_then(|v| v.get(i as usize)).copied() else {
                    continue;
                };
                fp.apply_lamp(r);
                fp.after_choice();
            }
            (SimPhase::Shop, SimCommand::Choose(0)) => {
                let Some(shop) = fp.flow.shop else { continue };
                if fp.progress.gold < shop.chest_cost as f32 {
                    continue;
                }
                fp.progress.gold -= shop.chest_cost as f32;
                fp.flow.chest_queue.push_back(ChestSource::Merchant);
                fp.outbox.0.push(SimEvent::Bought);
                fp.after_choice();
            }
            (SimPhase::Shop, SimCommand::Skip) => fp.after_choice(),
            _ => {}
        }
    }
}

/// 一步结束时检查：倒下、天明、升级、宝箱（与网页版的顺序一致）。
pub(crate) fn check_flow(mut fp: FlowParams) {
    if *fp.phase != SimPhase::Play {
        return;
    }
    let dead = fp.player.iter().any(|h| h.hp <= 0.0);
    if dead {
        fp.end(false);
        return;
    }
    if fp.plan.is_bench() {
        // 跑分模式不升级、不开宝箱
        fp.progress.pending_levels = 0;
        fp.flow.chest_queue.clear();
        return;
    }
    if fp.flow.won_at.is_some_and(|t| fp.secs() >= t) {
        fp.end(true);
    } else if fp.flow.shop.is_some() {
        *fp.phase = SimPhase::Shop;
        fp.outbox.0.push(SimEvent::ShopOpened);
    } else {
        fp.next_pending();
    }
}

/// 小头目宝箱至少几连（时间表里写的）。
fn miniboss_chest_min(c: &lantern_content::Content) -> u32 {
    c.run
        .schedule
        .iter()
        .find_map(|s| match s.event {
            lantern_content::PlanEvent::MiniBoss { chest_min, .. } => Some(chest_min),
            _ => None,
        })
        .unwrap_or(1)
}

/// 宝箱里优先给的一项：能进化的直接进化；否则升级等级最高、还没满级的法器。
fn closest_to_evolution(arsenal: &Arsenal, pool: &[(Offer, f32)]) -> Option<Offer> {
    if let Some(&(o, _)) = pool.iter().find(|(o, _)| matches!(o, Offer::Evolve(_))) {
        return Some(o);
    }
    // 等级最高的；一样高时取先拿到的
    pool.iter()
        .filter_map(|&(o, _)| match o {
            Offer::WeaponUp(k) => Some((arsenal.0[k].level, std::cmp::Reverse(k))),
            _ => None,
        })
        .max()
        .map(|(_, std::cmp::Reverse(k))| Offer::WeaponUp(k))
}
