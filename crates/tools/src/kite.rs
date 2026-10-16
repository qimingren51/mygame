//! 会躲的风筝机器人（玩法与数值会话写的，docs/BALANCE.md 第 2.6、11 节的验收用它）。
//!
//! 走位：每步在 16 个方向里挑威胁最小的一个。威胁 = 前方几个采样点附近的妖物、弹幕（按速度外推）、
//! 夜主的扇形和落点预警、结界边缘。安全时去点石灯笼。快被碰到时闪避。`--skill circle` 换成绕圈走位。
//! 选择阶段交给 `bot::respond`；`--school`、`--combo` 换成流派机器人、组合机器人（见 `school.rs`）。
//!
//!   cargo run --release -p lantern-tools -- kite [--runs 40] [--seed 1] [--tier 1] [--meta none|half|full]
//!       [--skill novice|regular|expert|circle] [--lamp <id>] [--school <流派>|all] [--combo <反应>|all]
//!       [--fusion <合璧 ID>|all] [--transformations]（打开异化与合璧；内容里已默认打开，留着兼容旧命令）
//!       [--assert-build-pace]（检查 3／6／9 分钟的构筑节奏）
//!       [--csv <目录>]（每 30 秒一行的 timeline.csv、每局一行的 runs.csv）[--jobs <线程数>]
//!       [--endless]（无尽夜，最多打 40 分钟）[--god]（主角无敌）
//!       [--record <文件>]（把第一局存成回放并打印关键时刻，可以用 `lantern --replay <文件> --from <秒>` 在游戏里看）

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fmt::Write as _;
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;

use bevy_math::{Vec2, ops};
use lantern_content::{Content, Element, Stat};
use lantern_core::step::TICK_HZ;
use lantern_sim::boss::{BossState, Foes};
use lantern_sim::combat::{DamageLog, Source};
use lantern_sim::lanterns::Lanterns;
use lantern_sim::run::Director;
use lantern_sim::{
    Health, HurtBy, InputFrame, Player, Pos, RunMode, RunSetup, SimCommand, SimEvent, SimHarness, SimPhase,
    SimView, bot,
};

use crate::school::{self, Plan, SCHOOL_NAMES};
use crate::{data_dir, flag, median, source_name};

const DIRS: usize = 16;

/// 机器人的手法：反应间隔、留意的范围、会不会预判弹幕、走位的偏差、闪避。
#[derive(Clone, Copy)]
struct Skill {
    /// 每隔几步重新判断一次方向（之间沿用上一次的方向）
    every: u64,
    /// 只留意这个距离以内的妖物和弹幕
    sight: f32,
    /// 按弹幕的速度预判落点
    foresee: bool,
    /// 选好的方向再随机偏转，最多这么多弧度
    wobble: f32,
    /// 妖物离身体多近才想到闪避
    dash_gap: f32,
    /// 想到了也只有这个概率真的按下去
    dash_chance: f32,
    /// 不躲，绕大圈走（`bot::input`，测上限）
    circle: bool,
}

impl Skill {
    fn by_name(name: &str) -> Option<Self> {
        Some(match name {
            // 新手：约 0.35 秒反应一次，只盯着身边，不预判弹幕，走位偏差大，常常忘了闪避
            "novice" => Skill {
                every: 21,
                sight: 170.0,
                foresee: false,
                wobble: 0.6,
                dash_gap: 0.0,
                dash_chance: 0.5,
                circle: false,
            },
            // 熟手：约 0.2 秒反应一次，看得到大半个屏幕
            "regular" => Skill {
                every: 12,
                sight: 240.0,
                foresee: true,
                wobble: 0.25,
                dash_gap: 3.0,
                dash_chance: 0.8,
                circle: false,
            },
            // 高手：每步都判断，全看得见（原来的风筝机器人）
            "expert" => Skill {
                every: 1,
                sight: 340.0,
                foresee: true,
                wobble: 0.0,
                dash_gap: 3.0,
                dash_chance: 1.0,
                circle: false,
            },
            // 绕圈：贴着妖群绕大圈，每 2 秒闪避一次（`balance` 用的走位）
            "circle" => Skill { circle: true, ..Skill::by_name("expert")? },
            _ => return None,
        })
    }
}

struct Kite {
    last: Vec2,
    skill: Skill,
    next: u64,
    held: InputFrame,
    /// 机器人自己的随机数（xorshift），按种子定，不动模拟的随机流
    rng: u64,
}

impl Kite {
    fn new(skill: Skill, seed: u64) -> Self {
        Kite {
            last: Vec2::ZERO,
            skill,
            next: 0,
            held: InputFrame::default(),
            rng: seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1,
        }
    }

    fn rand(&mut self) -> f32 {
        self.rng ^= self.rng << 13;
        self.rng ^= self.rng >> 7;
        self.rng ^= self.rng << 17;
        (self.rng >> 40) as f32 / (1u64 << 24) as f32
    }
}

/// 主角的位置、剩余闪避段数、生命。
fn player(sim: &SimHarness) -> Option<(Vec2, u32, f32, f32)> {
    sim.world().iter_entities().find_map(|e| {
        let (pos, pl, h) = (e.get::<Pos>()?, e.get::<Player>()?, e.get::<Health>()?);
        Some((pos.0, pl.dash_ready, h.hp, h.max))
    })
}

fn decide(sim: &SimHarness, k: &mut Kite, player_r: f32) -> (InputFrame, Vec<SimCommand>) {
    let Some((p, dash_ready, hp, hp_max)) = player(sim) else {
        return (InputFrame::default(), Vec::new());
    };
    let sk = k.skill;
    if sim.tick() < k.next {
        return (k.held, Vec::new());
    }
    k.next = sim.tick() + sk.every;
    let speed = sim.stats().get(Stat::Speed).max(30.0);
    let w = sim.world();
    let en = sim.enemies();
    let mut near: Vec<(Vec2, f32, f32)> = Vec::new();
    let mut nearest = f32::MAX;
    for i in 0..en.hi {
        if !en.alive[i] {
            continue;
        }
        let q = Vec2::new(en.x[i], en.y[i]);
        let d = q.distance(p);
        if d < sk.sight {
            nearest = nearest.min(d - en.r[i] - player_r);
            let wgt = if en.max_hp[i] > 2000.0 {
                6.0
            } else if en.max_hp[i] > 150.0 {
                3.0
            } else {
                1.0
            };
            near.push((q, en.r[i], wgt));
        }
    }
    let shots: Vec<(Vec2, Vec2, f32)> = w
        .resource::<Foes>()
        .0
        .iter()
        .filter(|f| f.pos.distance(p) < sk.sight)
        .map(|f| (f.pos, if sk.foresee { f.vel } else { Vec2::ZERO }, f.radius))
        .collect();
    let bullet_close = shots
        .iter()
        .any(|&(s, v, r)| [0.0f32, 0.1, 0.2].iter().any(|&t| (s + v * t).distance(p) - r - player_r < 6.0));
    let boss = w.resource::<BossState>();
    let barrier = w.resource::<Director>().barrier;
    let safe = nearest > 90.0 && shots.iter().all(|&(s, _, _)| s.distance(p) > 120.0);
    let low = hp < hp_max * 0.35;
    // 最近的一盏没点亮的灯
    let lamp = w
        .resource::<Lanterns>()
        .0
        .iter()
        .filter(|l| !l.lit)
        .map(|l| l.pos)
        .min_by(|a, b| a.distance_squared(p).total_cmp(&b.distance_squared(p)));
    let in_hazard = |q: Vec2| -> bool {
        boss.sweeps.iter().any(|sw| {
            let d = q - sw.origin;
            let mut diff = ops::atan2(d.y, d.x) - sw.dir;
            while diff > std::f32::consts::PI {
                diff -= std::f32::consts::TAU;
            }
            while diff < -std::f32::consts::PI {
                diff += std::f32::consts::TAU;
            }
            d.length() <= sw.radius + player_r + 10.0 && diff.abs() <= sw.angle * 0.5 + 0.15
        }) || boss.drops.iter().any(|r| q.distance(r.pos) <= r.radius + player_r + 10.0)
    };
    // 点灯：安全、站在灯旁就不动
    if let Some(l) = lamp
        && safe
        && !low
        && l.distance(p) < 40.0
        && !in_hazard(p)
    {
        return (InputFrame::default(), Vec::new());
    }
    let lamp_dir = lamp.filter(|l| l.distance(p) < 1500.0).map(|l| (l - p).normalize_or_zero());
    let reach = if low { 150.0 } else { 115.0 };
    let mut best = (f32::MAX, Vec2::X);
    for j in 0..DIRS {
        let a = j as f32 / DIRS as f32 * std::f32::consts::TAU;
        let d = Vec2::new(ops::cos(a), ops::sin(a));
        let mut threat = 0.0f32;
        for step in [20.0f32, 48.0, 90.0] {
            let q = p + d * step;
            let t = step / speed;
            for &(e, r, wgt) in &near {
                let dist = (q.distance(e) - r - player_r).max(0.0);
                if dist < reach {
                    let x = 1.0 - dist / reach;
                    threat += wgt * x * x * x;
                }
            }
            for &(s, v, r) in &shots {
                let dist = ((s + v * t).distance(q) - r - player_r).max(0.0);
                if dist < 40.0 {
                    threat += 4.0 * (1.0 - dist / 40.0);
                }
            }
            if in_hazard(q) {
                threat += 25.0;
            }
            if let Some((c, rad)) = barrier {
                let out = q.distance(c) - (rad - 60.0);
                if out > 0.0 {
                    threat += out * 0.15;
                }
            }
        }
        threat -= 0.25 * d.dot(k.last);
        if let Some(ld) = lamp_dir {
            threat -= if safe { 1.2 } else { 0.25 } * d.dot(ld);
        }
        if threat < best.0 {
            best = (threat, d);
        }
    }
    k.last = best.1;
    let mut dir = best.1;
    if sk.wobble > 0.0 {
        let a = (k.rand() * 2.0 - 1.0) * sk.wobble;
        let (s, c) = ops::sin_cos(a);
        dir = Vec2::new(dir.x * c - dir.y * s, dir.x * s + dir.y * c);
    }
    let mut cmds = Vec::new();
    if dash_ready > 0 && (nearest < sk.dash_gap || bullet_close || in_hazard(p)) && k.rand() < sk.dash_chance
    {
        cmds.push(SimCommand::Dash);
    }
    k.held = InputFrame::quantize(dir);
    (k.held, cmds)
}

/// 三档局外成长：none 新手；half 约第 35 局；full 全满（docs/BALANCE.md 第 2.6 节）。
fn meta_setup(setup: &mut RunSetup, meta: &str) {
    let initial = ["wind_wheel", "pillar", "longevity", "ice_soul"];
    setup.charm_pool = initial.iter().map(|s| s.to_string()).collect();
    let set = |v: &[(&str, u32)]| v.iter().map(|&(k, n)| (k.to_string(), n)).collect::<BTreeMap<_, _>>();
    match meta {
        "none" => {}
        "half" => {
            setup.attributes = set(&[
                ("damage", 5),
                ("health", 5),
                ("armor", 2),
                ("speed", 2),
                ("magnet", 3),
                ("crit", 2),
                ("cooldown", 2),
                ("xp", 3),
            ]);
            setup.meta =
                set(&[("luck", 3), ("seal", 1), ("wick", 2), ("afterglow", 1), ("ember", 1), ("oil", 1)]);
            setup.charms = vec!["longevity".into()];
            setup.charm_pool.extend(["night_pearl", "elixir", "five_coins"].iter().map(|s| s.to_string()));
        }
        _ => {
            setup.attributes = set(&[
                ("damage", 10),
                ("health", 10),
                ("armor", 5),
                ("speed", 5),
                ("magnet", 5),
                ("crit", 5),
                ("cooldown", 5),
                ("xp", 5),
            ]);
            setup.meta = set(&[
                ("luck", 5),
                ("seal", 3),
                ("wick", 3),
                ("afterglow", 2),
                ("ember", 3),
                ("slot", 1),
                ("oil", 3),
            ]);
            setup.charms = vec!["longevity".into()];
            setup.charm_pool.extend(
                ["night_pearl", "elixir", "five_coins", "broken_sword"].iter().map(|s| s.to_string()),
            );
        }
    }
}

/// 回放时间线上要标出的关键时刻。
fn moment(ev: &SimEvent) -> Option<&'static str> {
    Some(match ev {
        SimEvent::Evolve { form, .. } => match form {
            lantern_sim::weapons::Form::Mutated => "异化",
            lantern_sim::weapons::Form::Fused(_) => "合璧",
            _ => "进化",
        },
        SimEvent::Resonance { tier, .. } if *tier >= 2 => "共鸣跨阶",
        SimEvent::Reaction { first: true, .. } => "反应初见",
        SimEvent::Elite { .. } => "精英",
        SimEvent::EncircleWarn { .. } => "合围",
        SimEvent::Surge => "妖潮",
        SimEvent::NightDeeper { .. } => "夜深",
        SimEvent::Ult => "燃灯",
        SimEvent::Combo { .. } => "连斩",
        SimEvent::BossArrived { .. } => "夜主登场",
        SimEvent::BossPhase { .. } => "夜主换阶段",
        SimEvent::BossDefeated { dawn: true, .. } => "夜主伏诛",
        SimEvent::BossDefeated { dawn: false, .. } => "夜主退去",
        SimEvent::PlayerDied => "倒下",
        _ => return None,
    })
}

/// 一组局的设置。
#[derive(Clone, Copy)]
struct Cfg<'a> {
    tier: u8,
    meta: &'a str,
    lamp: Option<&'a str>,
    skill: Skill,
    skill_name: &'a str,
    plan: Option<&'a Plan>,
    /// 无尽夜
    endless: bool,
    /// 主角无敌（看完整一局的画面用）
    god: bool,
    /// 随机选卡（模拟不懂配对的新手）：有进化、异化、合璧就选，否则随便挑一张
    random_pick: bool,
}

/// 每 30 秒一行（docs/BALANCE.md 第 11 节）。
struct Row {
    /// 第几秒
    t: u32,
    level: u32,
    /// 累计击杀
    kills: u32,
    /// 场上妖物
    alive: u32,
    /// 这 30 秒：刷出的血量、各来源的有效伤害（按 [`columns`] 的顺序）、受到的伤害
    spawned: f64,
    damage: Vec<f64>,
    taken: f64,
    /// 清场时间（秒）：屏幕内妖物的血量 ÷ 这 30 秒的平均秒伤
    clear: Option<f32>,
}

struct KiteRun {
    /// 实际结算灯油；打满工具时限而未结算时留空。
    oil: Option<u32>,
    seed: u64,
    /// 实际带的灯（流派机器人会换灯）
    lamp: String,
    won: bool,
    secs: f32,
    kills: u32,
    level: u32,
    rows: Vec<Row>,
    /// 每次进化：时刻（秒）、法器下标
    evolutions: Vec<(f32, u16)>,
    fusions: Vec<(f32, usize)>,
    boss_time: Option<f32>,
    alive7: Option<u32>,
    surge_peak: u32,
    /// 9:30 前的燃灯次数、全部燃灯次数
    ults: u32,
    ults_total: u32,
    lamps: u32,
    damage: Vec<(Source, f64)>,
    /// 倒下时最后一下是谁打的；赢了或超时为 None
    cause: Option<HurtBy>,
    /// 各系（按 [`Element::ALL`]）到一、二、三阶、极境的时刻
    tiers: [[Option<f32>; 4]; 5],
    taiji: Option<f32>,
    /// 各种反应的次数（`elements.ron` 里 reactions 的顺序）
    reactions: Vec<u32>,
    /// 结束时的法器、心法、灯坠
    build: [String; 3],
    /// 打倒的夜主
    bosses: u32,
}

/// 无尽夜最多打这么多秒。
const ENDLESS_CAP: f32 = 40.0 * 60.0;

/// 伤害来源里除了法器和反应的那些，CSV 的列名。
const OTHERS: [(Source, &str); 9] = [
    (Source::BonusSword, "bonus_sword"),
    (Source::Burn, "burn"),
    (Source::Blast, "blast"),
    (Source::Quake, "quake"),
    (Source::Screen, "taiji"),
    (Source::Ult, "ult"),
    (Source::Band, "band"),
    (Source::Dash, "dash"),
    (Source::Trail, "trail"),
];

/// 伤害来源在 CSV 里的列号：法器、[`OTHERS`]、反应。
fn column(content: &Content, s: Source) -> usize {
    let w = content.weapons.len();
    match s {
        Source::Weapon(i) => i as usize,
        Source::Reaction(r) => w + OTHERS.len() + r as usize,
        // 新增来源时这里会报错：记得补进 OTHERS
        Source::BonusSword
        | Source::Burn
        | Source::Blast
        | Source::Quake
        | Source::Screen
        | Source::Ult
        | Source::Band
        | Source::Dash
        | Source::Trail => w + OTHERS.iter().position(|o| o.0 == s).expect("OTHERS 里列全了"),
    }
}

/// 伤害列的名字（ASCII，方便表格软件和脚本读）。
fn columns(content: &Content) -> Vec<String> {
    let mut v: Vec<String> = content.weapons.iter().map(|w| w.id.clone()).collect();
    v.extend(OTHERS.iter().map(|o| o.1.to_string()));
    v.extend(content.elements.reactions.iter().map(|r| format!("react_{}", r.id)));
    v
}

fn by_column(content: &Content, log: &DamageLog) -> Vec<f64> {
    let mut v = vec![0.0; columns(content).len()];
    for &(s, d) in &log.0 {
        v[column(content, s)] += d;
    }
    v
}

fn hurt_name(content: &Content, by: HurtBy) -> String {
    match by {
        HurtBy::Contact { kind } => content.enemies[kind as usize].name.clone(),
        HurtBy::Charge { kind } => format!("{}·冲锋", content.enemies[kind as usize].name),
        HurtBy::Shot => "弹幕".into(),
        HurtBy::Sweep => "九尾扫".into(),
        HurtBy::Rain => "狐火雨".into(),
    }
}

fn element_id(e: Element) -> &'static str {
    match e {
        Element::Metal => "metal",
        Element::Wood => "wood",
        Element::Water => "water",
        Element::Fire => "fire",
        Element::Earth => "earth",
    }
}

/// 屏幕内妖物的血量。
fn screen_hp(sim: &SimHarness) -> f64 {
    let Some((p, ..)) = player(sim) else { return 0.0 };
    let view = sim.world().resource::<SimView>();
    let en = sim.enemies();
    (0..en.hi)
        .filter(|&i| {
            en.alive[i] && (en.x[i] - p.x).abs() <= view.half_w && (en.y[i] - p.y).abs() <= view.half_h
        })
        .map(|i| f64::from(en.hp[i].max(0.0)))
        .sum()
}

fn kite_one(content: &Content, seed: u64, cfg: Cfg, record: Option<&Path>) -> KiteRun {
    let mut setup = RunSetup::new(seed, if cfg.endless { RunMode::Endless } else { RunMode::Normal });
    setup.tier = cfg.tier;
    setup.god = cfg.god;
    setup.lamp = cfg.lamp.map(str::to_string);
    meta_setup(&mut setup, cfg.meta);
    if let Some(plan) = cfg.plan {
        plan.apply(content, &mut setup);
    }
    let lamp = content.lamps[setup.lamp_index(content)].id.clone();
    let player_r = content.player.radius;
    let mut sim = SimHarness::with_setup(content.clone(), setup);
    if record.is_some() {
        sim.record(env!("CARGO_PKG_VERSION"));
    }
    let mut k = Kite::new(cfg.skill, seed);
    let hz = u64::from(TICK_HZ);
    let mut rows = Vec::new();
    let mut fusions = Vec::new();
    let (mut evolutions, mut alive7, mut surge_peak, mut ults, mut ults_total) =
        (Vec::new(), None, 0u32, 0, 0);
    let (mut last_hurt, mut cause, mut taiji) = (None, None, None);
    // 第一个夜主：登场时刻、从登场到倒下用了多久
    let (mut boss_at, mut boss_time) = (None, None);
    let mut tiers = [[None; 4]; 5];
    // 录回放时顺带记下关键时刻，方便用 --from 跳过去看
    let mut marks: Vec<String> = Vec::new();
    let mut reactions = vec![0u32; content.elements.reactions.len()];
    let (mut last_dmg, mut last_spawned, mut taken) = (by_column(content, sim.damage_log()), 0.0, 0.0);
    // 一夜最多打 15 分钟；无尽夜最多 40 分钟（再长就算撑满）
    let cap = if cfg.endless { ENDLESS_CAP } else { 15.0 * 60.0 } as u64 * hz;
    while !sim.is_over() && sim.tick() < cap {
        let tick = sim.tick();
        let (input, cmds) = match sim.phase() {
            SimPhase::Play if cfg.skill.circle => bot::input(tick),
            SimPhase::Play => decide(&sim, &mut k, player_r),
            _ => (InputFrame::default(), Vec::new()),
        };
        if cfg.random_pick
            && sim.phase() == SimPhase::LevelUp
            && let Some(choice) = &sim.flow().choice
        {
            let offers = &choice.offers;
            let form = offers.iter().position(|o| {
                matches!(o, lantern_sim::Offer::Evolve(_) | lantern_sim::Offer::Mutate(_) | lantern_sim::Offer::Fuse { .. })
            });
            // 按种子和时刻散列，结果固定
            let mut h = seed ^ tick.wrapping_mul(0x9E37_79B9_7F4A_7C15);
            h ^= h >> 33;
            h = h.wrapping_mul(0xFF51_AFD7_ED55_8CCD);
            h ^= h >> 33;
            let i = form.unwrap_or((h % offers.len().max(1) as u64) as usize);
            sim.step(InputFrame::default(), &[SimCommand::Choose(i as u8)]);
        } else {
            school::step(&mut sim, content, cfg.plan, input, &cmds);
        }
        let t = sim.tick();
        let now = t as f32 / TICK_HZ as f32;
        for ev in sim.take_events() {
            if record.is_some()
                && let Some(what) = moment(&ev)
            {
                let s = t / hz;
                let line = format!("{:02}:{:02} {what}", s / 60, s % 60);
                if marks.last() != Some(&line) {
                    marks.push(line);
                }
            }
            match ev {
                SimEvent::Evolve { form: lantern_sim::weapons::Form::Fused(f), .. } => fusions.push((now, f)),
                SimEvent::Evolve { weapon, .. } => evolutions.push((now, weapon)),
                SimEvent::Ult => {
                    ults_total += 1;
                    if t < 570 * hz {
                        ults += 1;
                    }
                }
                SimEvent::PlayerHurt { amount, by, .. } => {
                    taken += f64::from(amount);
                    last_hurt = Some(by);
                }
                SimEvent::PlayerDied => cause = last_hurt,
                SimEvent::Resonance { element, tier } => {
                    for slot in tiers[element.index()].iter_mut().take(tier as usize) {
                        slot.get_or_insert(now);
                    }
                }
                SimEvent::Taiji => {
                    taiji.get_or_insert(now);
                }
                SimEvent::Reaction { kind, .. } => reactions[kind as usize] += 1,
                SimEvent::BossArrived { .. } => {
                    boss_at.get_or_insert(now);
                }
                SimEvent::BossDefeated { .. } if boss_time.is_none() => {
                    boss_time = boss_at.map(|a| now - a);
                }
                _ => {}
            }
        }
        if t == tick {
            continue;
        }
        let alive = sim.enemies().count as u32;
        if t == 420 * hz {
            alive7 = Some(alive);
        }
        if (480 * hz..=515 * hz).contains(&t) {
            surge_peak = surge_peak.max(alive);
        }
        if t.is_multiple_of(30 * hz) {
            let dmg = by_column(content, sim.damage_log());
            let window: Vec<f64> = dmg.iter().zip(&last_dmg).map(|(a, b)| a - b).collect();
            let dps = window.iter().sum::<f64>() / 30.0;
            let spawned = sim.enemies().spawned_hp;
            rows.push(Row {
                t: (t / hz) as u32,
                level: sim.progress().level,
                kills: sim.progress().kills,
                alive,
                spawned: spawned - last_spawned,
                damage: window,
                taken,
                clear: (dps > 0.0).then(|| (screen_hp(&sim) / dps) as f32),
            });
            (last_dmg, last_spawned, taken) = (dmg, spawned, 0.0);
        }
    }
    if let (Some(path), Some(replay)) = (record, sim.replay()) {
        eprintln!("{}", marks.join("\n"));
        match std::fs::write(path, replay.to_ron()) {
            Ok(()) => eprintln!("回放已保存：{}", path.display()),
            Err(e) => eprintln!("保存回放失败：{e}"),
        }
    }
    let won = sim.flow().result.as_ref().is_some_and(|r| r.won);
    // 打满时长还没倒下的局没有结算，从无尽夜的进度里读
    let bosses = sim.world().resource::<Director>().endless.map_or(u32::from(won), |e| e.downs);
    let secs = sim.tick() as f32 / TICK_HZ as f32;
    let join = |v: Vec<String>| v.join(" ");
    let build = [
        join(
            sim.arsenal()
                .0
                .iter()
                .map(|w| {
                    format!(
                        "{}{}{}",
                        content.weapons[w.def].id,
                        w.level,
                        if w.transformed() { "*" } else { "" }
                    )
                })
                .collect(),
        ),
        join(
            sim.build()
                .passives
                .iter()
                .map(|p| format!("{}{}", content.passives[p.def].id, p.level))
                .collect(),
        ),
        join(sim.build().charms.iter().map(|&c| content.charms[c].id.clone()).collect()),
    ];
    KiteRun {
        oil: sim.flow().result.as_ref().map(|r| r.oil),
        seed,
        lamp,
        won,
        secs,
        kills: sim.progress().kills,
        level: sim.progress().level,
        rows,
        evolutions,
        fusions,
        boss_time,
        alive7,
        surge_peak,
        ults,
        ults_total,
        lamps: sim.world().resource::<Lanterns>().lit(),
        damage: sim.damage_log().0.clone(),
        cause: if won { None } else { cause },
        tiers,
        taiji,
        reactions,
        build,
        bosses,
    }
}

/// 用 `jobs` 个线程打 `runs` 局（结果按种子顺序排好；每局只看种子，和线程数无关）。
fn run_all(
    content: &Content,
    seed0: u64,
    runs: usize,
    jobs: usize,
    cfg: Cfg,
    record: Option<&Path>,
) -> Vec<KiteRun> {
    let next = AtomicUsize::new(0);
    let mut done: Vec<(usize, KiteRun)> = std::thread::scope(|s| {
        let workers: Vec<_> = (0..jobs.clamp(1, runs.max(1)))
            .map(|_| {
                s.spawn(|| {
                    let mut mine = Vec::new();
                    loop {
                        let k = next.fetch_add(1, Ordering::Relaxed);
                        if k >= runs {
                            break mine;
                        }
                        let rec = record.filter(|_| k == 0);
                        mine.push((k, kite_one(content, seed0 + k as u64, cfg, rec)));
                    }
                })
            })
            .collect();
        workers.into_iter().flat_map(|w| w.join().expect("机器人线程出错")).collect()
    });
    done.sort_by_key(|d| d.0);
    done.into_iter().map(|d| d.1).collect()
}

/// 时刻的中位数；一个都没有时是 NaN（显示成“—”）。
fn when(v: Vec<f32>) -> f32 {
    if v.is_empty() { f32::NAN } else { median(v) }
}

fn mmss(s: f32) -> String {
    if s.is_nan() { "—".into() } else { format!("{}:{:02}", (s / 60.0) as u32, (s % 60.0) as u32) }
}

/// 打印一组局的汇总；返回对照表的一行。
fn report(
    content: &Content,
    label: &str,
    all: &[KiteRun],
    plan: Option<&Plan>,
    endless: bool,
) -> Vec<String> {
    let n = all.len().max(1) as f32;
    let wins = all.iter().filter(|r| r.won).count();
    let early = all.iter().filter(|r| !r.won && r.secs < 180.0).count();
    println!("—— {label} ——");
    println!(
        "胜率 {:.0}%；3 分钟前倒下 {:.0}%；存活中位 {}；击杀中位 {:.0}",
        100.0 * wins as f32 / n,
        100.0 * early as f32 / n,
        mmss(median(all.iter().map(|r| r.secs).collect())),
        median(all.iter().map(|r| r.kills as f32).collect())
    );
    let mut oils: Vec<_> = all.iter().filter_map(|r| r.oil).collect();
    oils.sort_unstable();
    if !oils.is_empty() {
        let pct = |p: usize| oils[(oils.len() - 1) * p / 100];
        println!("结算灯油（{} 局）：P10 {}，中位 {}，P90 {}", oils.len(), pct(10), pct(50), pct(90));
    }
    if endless {
        let over = |m: f32| 100.0 * all.iter().filter(|r| r.secs >= m * 60.0).count() as f32 / n;
        println!(
            "无尽夜：存活中位 {}；撑过 15 分 {:.0}%、20 分 {:.0}%、25 分 {:.0}%、撑满 {} {:.0}%；打退夜主中位 {:.0} 次",
            mmss(median(all.iter().map(|r| r.secs).collect())),
            over(15.0),
            over(20.0),
            over(25.0),
            mmss(ENDLESS_CAP),
            over(ENDLESS_CAP / 60.0),
            median(all.iter().map(|r| r.bosses as f32).collect())
        );
    }
    let lv = |i: usize| {
        let v: Vec<f32> = all.iter().filter_map(|r| r.rows.get(i).map(|row| row.level as f32)).collect();
        let len = v.len();
        (median(v), len)
    };
    let ((l3, n3), (l6, n6), (l9, n9)) = (lv(5), lv(11), lv(17));
    println!(
        "等级中位（活着的局）：3 分 {l3:.0}（{n3} 局），6 分 {l6:.0}（{n6} 局），9 分 {l9:.0}（{n9} 局）"
    );
    let evo: Vec<f32> = all.iter().filter_map(|r| r.evolutions.first().map(|e| e.0)).collect();
    let alive_at = |s: f32| all.iter().filter(|r| r.secs >= s).count();
    println!(
        "第一次进化：活过 6:15 的 {} 局里 {} 局有进化，进化中位 {}",
        alive_at(375.0),
        evo.len(),
        mmss(when(evo.clone()))
    );
    let first: Vec<_> =
        all.iter().filter_map(|r| r.tiers.iter().filter_map(|t| t[0]).min_by(f32::total_cmp)).collect();
    let fused: Vec<_> = all.iter().filter_map(|r| r.fusions.first().map(|f| f.0)).collect();
    println!(
        "构筑节奏：一阶共鸣 {}（{}/{} 局），第一次进化或异化 {}，第一次合璧 {}（{}/{} 局）",
        mmss(when(first.clone())),
        first.len(),
        all.len(),
        mmss(when(evo.clone())),
        mmss(when(fused.clone())),
        fused.len(),
        all.len()
    );
    // 共鸣：流派看本系，太极看太极；不限流派时看每局最高的那一系
    let tier_at = |r: &KiteRun, t: usize| -> Option<f32> {
        match plan.map(|p| p.elements.as_slice()) {
            Some([e]) => r.tiers[e.index()][t],
            _ => r.tiers.iter().filter_map(|x| x[t]).min_by(f32::total_cmp),
        }
    };
    let med_tier = |t: usize| {
        let v: Vec<f32> = all.iter().filter_map(|r| tier_at(r, t)).collect();
        let len = v.len();
        (when(v), len)
    };
    let ((t2, c2), (t3, c3)) = (med_tier(1), med_tier(2));
    let peak = all.iter().filter(|r| tier_at(r, 3).is_some_and(|s| s < 570.0)).count();
    let taiji: Vec<f32> = all.iter().filter_map(|r| r.taiji).collect();
    println!(
        "共鸣：二阶中位 {}（{c2} 局），三阶中位 {}（{c3} 局），9:30 前极境 {:.0}%；太极中位 {}（{} 局）",
        mmss(t2),
        mmss(t3),
        100.0 * peak as f32 / n,
        mmss(when(taiji.clone())),
        taiji.len()
    );
    let bt: Vec<f32> = all.iter().filter_map(|r| r.boss_time).collect();
    let clear9: Vec<f32> = all.iter().filter_map(|r| r.rows.get(17).and_then(|row| row.clear)).collect();
    println!(
        "夜主击杀时间中位 {:.0} 秒（{} 局）；9 分钟清场时间中位 {:.1} 秒（{} 局）",
        median(bt.clone()),
        bt.len(),
        median(clear9.clone()),
        clear9.len()
    );
    let a7: Vec<f32> = all.iter().filter_map(|r| r.alive7.map(|a| a as f32)).collect();
    let sp: Vec<f32> = all.iter().filter(|r| r.secs > 515.0).map(|r| r.surge_peak as f32).collect();
    println!("7 分钟场上妖物中位 {:.0}；妖潮峰值中位 {:.0}", median(a7), median(sp));
    let ult_int: Vec<f32> =
        all.iter().filter(|r| r.ults > 0).map(|r| r.secs.min(570.0) / r.ults as f32).collect();
    println!(
        "燃灯平均间隔中位 {:.0} 秒；石灯笼平均点亮 {:.1} 盏",
        median(ult_int),
        all.iter().map(|r| r.lamps as f32).sum::<f32>() / n
    );
    let mut deaths: Vec<f32> = all.iter().filter(|r| !r.won).map(|r| r.secs).collect();
    deaths.sort_by(f32::total_cmp);
    let bucket = |a: f32, b: f32| deaths.iter().filter(|&&s| s >= a && s < b).count();
    println!(
        "倒下时间分布：0–3 分 {}，3–5 分 {}，5–8 分 {}，8–9:30 分 {}，夜主战 {}",
        bucket(0.0, 180.0),
        bucket(180.0, 300.0),
        bucket(300.0, 480.0),
        bucket(480.0, 570.0),
        bucket(570.0, f32::MAX)
    );
    let mut causes: BTreeMap<String, u32> = BTreeMap::new();
    for r in all.iter().filter(|r| !r.won) {
        let name = r.cause.map_or_else(|| "超时".to_string(), |c| hurt_name(content, c));
        *causes.entry(name).or_default() += 1;
    }
    let mut causes: Vec<(String, u32)> = causes.into_iter().collect();
    causes.sort_by_key(|c| std::cmp::Reverse(c.1));
    if !causes.is_empty() {
        let top: Vec<String> = causes.iter().take(6).map(|(k, v)| format!("{k} {v}")).collect();
        println!("死因：{}", top.join("，"));
    }
    let mut total: Vec<(Source, f64)> = Vec::new();
    for r in all {
        for &(s, d) in &r.damage {
            match total.iter_mut().find(|(t, _)| *t == s) {
                Some((_, v)) => *v += d,
                None => total.push((s, d)),
            }
        }
    }
    let sum: f64 = total.iter().map(|(_, d)| d).sum::<f64>().max(1.0);
    let react: f64 = total.iter().filter(|(s, _)| matches!(s, Source::Reaction(_))).map(|(_, d)| d).sum();
    total.sort_by(|a, b| b.1.total_cmp(&a.1));
    let shares: Vec<String> = total
        .iter()
        .take(12)
        .map(|&(s, d)| format!("{} {:.1}%", source_name(content, s), d / sum * 100.0))
        .collect();
    println!("伤害来源：{}", shares.join("，"));
    let react_n: Vec<f32> = all.iter().map(|r| r.reactions.iter().sum::<u32>() as f32).collect();
    println!("反应：每局次数中位 {:.0}，伤害占比 {:.1}%", median(react_n), react / sum * 100.0);
    vec![
        label.to_string(),
        format!("{:.0}%", 100.0 * wins as f32 / n),
        format!("{l9:.0}"),
        mmss(when(evo)),
        mmss(t2),
        mmss(t3),
        format!("{:.0}%", 100.0 * peak as f32 / n),
        format!("{:.1}", median(clear9)),
        format!("{:.0}", median(bt)),
        format!("{:.1}%", react / sum * 100.0),
    ]
}

/// CSV 的一个格子：有逗号、引号的加引号。
fn cell(s: impl ToString) -> String {
    let s = s.to_string();
    if s.contains([',', '"', '\n']) { format!("\"{}\"", s.replace('"', "\"\"")) } else { s }
}

fn opt(v: Option<f32>) -> String {
    v.map_or_else(String::new, |s| format!("{s:.1}"))
}

/// 写 timeline.csv（每局每 30 秒一行）和 runs.csv（每局一行）。
fn write_csv(content: &Content, dir: &Path, groups: &[(String, Cfg, Vec<KiteRun>)]) -> Result<(), String> {
    std::fs::create_dir_all(dir).map_err(|e| format!("建不了 {}：{e}", dir.display()))?;
    let cols = columns(content);
    let mut tl =
        String::from("bot,mode,skill,meta,tier,seed,t,level,kills,alive,spawned_hp,taken,clear_secs");
    for c in &cols {
        let _ = write!(tl, ",dmg_{c}");
    }
    tl.push('\n');
    let mut rs = String::from(
        "bot,mode,skill,meta,tier,lamp,seed,won,secs,cause,kills,level,evolutions,first_evolution,first_fusion,boss_secs,bosses,ults,ults_before_930,lamps,alive_7min,surge_peak",
    );
    for e in Element::ALL {
        for t in 1..=4 {
            let _ = write!(rs, ",{}_{t}", element_id(e));
        }
    }
    rs.push_str(",taiji,reactions,reaction_share");
    for r in &content.elements.reactions {
        let _ = write!(rs, ",n_{}", r.id);
    }
    rs.push_str(",weapons,passives,charms,oil\n");
    for (label, cfg, all) in groups {
        let mode = if cfg.endless { "endless" } else { "night" };
        let head = [cell(label), cell(mode), cell(cfg.skill_name), cell(cfg.meta), cell(cfg.tier)].join(",");
        for r in all {
            for row in &r.rows {
                let _ = write!(
                    tl,
                    "{head},{},{},{},{},{},{:.0},{:.1},{}",
                    r.seed,
                    row.t,
                    row.level,
                    row.kills,
                    row.alive,
                    row.spawned,
                    row.taken,
                    opt(row.clear)
                );
                for d in &row.damage {
                    let _ = write!(tl, ",{d:.0}");
                }
                tl.push('\n');
            }
            let evo: Vec<String> = r
                .evolutions
                .iter()
                .map(|&(s, w)| format!("{}@{s:.0}", content.weapons[w as usize].id))
                .collect();
            let total: f64 = r.damage.iter().map(|d| d.1).sum::<f64>().max(1.0);
            let react: f64 =
                r.damage.iter().filter(|d| matches!(d.0, Source::Reaction(_))).map(|d| d.1).sum();
            let cause = if r.won {
                String::new()
            } else {
                r.cause.map_or_else(|| "超时".to_string(), |c| hurt_name(content, c))
            };
            let _ = write!(
                rs,
                "{head},{},{},{},{:.1},{},{},{},{},{},{},{},{},{},{},{},{},{}",
                cell(&r.lamp),
                r.seed,
                u8::from(r.won),
                r.secs,
                cell(cause),
                r.kills,
                r.level,
                cell(evo.join(" ")),
                opt(r.evolutions.first().map(|e| e.0)),
                opt(r.fusions.first().map(|e| e.0)),
                opt(r.boss_time),
                r.bosses,
                r.ults_total,
                r.ults,
                r.lamps,
                r.alive7.map_or_else(String::new, |a| a.to_string()),
                r.surge_peak
            );
            for e in &r.tiers {
                for t in e {
                    let _ = write!(rs, ",{}", opt(*t));
                }
            }
            let _ = write!(rs, ",{},{},{:.4}", opt(r.taiji), r.reactions.iter().sum::<u32>(), react / total);
            for n in &r.reactions {
                let _ = write!(rs, ",{n}");
            }
            let _ = writeln!(
                rs,
                ",{},{},{},{}",
                cell(&r.build[0]),
                cell(&r.build[1]),
                cell(&r.build[2]),
                r.oil.map_or_else(String::new, |n| n.to_string())
            );
        }
    }
    for (name, text) in [("timeline.csv", &tl), ("runs.csv", &rs)] {
        let path = dir.join(name);
        std::fs::write(&path, text).map_err(|e| format!("写不了 {}：{e}", path.display()))?;
    }
    eprintln!("CSV 已写到 {}（timeline.csv、runs.csv）", dir.display());
    Ok(())
}

pub fn kite_cmd(args: &[OsString]) -> Result<(), String> {
    let runs = flag(args, "--runs", 40)? as usize;
    let seed0 = flag(args, "--seed", 1)?;
    let tier = flag(args, "--tier", 1)? as u8;
    let jobs =
        flag(args, "--jobs", std::thread::available_parallelism().map_or(1, |n| n.get()) as u64)? as usize;
    let value = |name: &str| args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned();
    let text = |name: &str| {
        value(name)
            .map(|v| v.into_string().map_err(|v| format!("{name} 后面必须是有效的 UTF-8 文字：{v:?}")))
            .transpose()
    };
    let meta = text("--meta")?.unwrap_or_else(|| "none".into());
    if !["none", "half", "full"].contains(&meta.as_str()) {
        return Err("--meta 只能是 none、half、full".into());
    }
    let lamp = text("--lamp")?;
    let record = value("--record").map(std::path::PathBuf::from);
    let skill_name = text("--skill")?.unwrap_or_else(|| "expert".into());
    let skill = Skill::by_name(&skill_name).ok_or("--skill 只能是 novice、regular、expert、circle")?;
    let mut content = Content::load(&data_dir()).map_err(|e| e.to_string())?;
    // 异化与合璧在内容里默认打开；旧命令带 --transformations 或 --fusion 时照样打开
    let transformations = args.iter().any(|a| a == "--transformations") || value("--fusion").is_some();
    if transformations {
        content.enable_transformations();
    }
    // 要跑的机器人：不带选卡偏好的一组，或者流派、组合（all 表示全部）
    let mut plans: Vec<Plan> = Vec::new();
    if let Some(name) = text("--school")? {
        if name == "all" {
            plans.extend(SCHOOL_NAMES.split('、').filter_map(Plan::school));
        } else {
            plans.push(Plan::school(&name).ok_or(format!("--school 只能是 {SCHOOL_NAMES} 或 all"))?);
        }
    }
    if let Some(name) = text("--combo")? {
        if name == "all" {
            plans.extend(content.elements.reactions.iter().filter_map(|r| Plan::combo(&content, &r.id)));
        } else {
            let ids: Vec<&str> = content.elements.reactions.iter().map(|r| r.id.as_str()).collect();
            plans.push(
                Plan::combo(&content, &name)
                    .ok_or(format!("--combo 是反应的 ID 或名字（{}）或 all", ids.join("、")))?,
            );
        }
    }
    if let Some(name) = text("--fusion")? {
        if name == "all" {
            plans.extend(content.fusions.iter().filter_map(|f| Plan::fusion(&content, &f.id)));
        } else {
            plans.push(Plan::fusion(&content, &name).ok_or("--fusion 需要合璧的 ID、名字或 all")?);
        }
    }
    let endless = args.iter().any(|a| a == "--endless");
    let mut groups: Vec<(String, Cfg, Vec<KiteRun>)> = Vec::new();
    let start = Instant::now();
    println!(
        "风筝机器人每组 {runs} 局，{}，手法 {skill_name}，{tier} 更，局外成长 {meta}，灯 {}，{jobs} 个线程{}",
        if endless { "无尽夜" } else { "夜行" },
        lamp.as_deref().unwrap_or("默认"),
        if transformations { "，异化与合璧打开" } else { "" }
    );
    let god = args.iter().any(|a| a == "--god");
    let base = Cfg {
        tier,
        meta: &meta,
        lamp: lamp.as_deref(),
        skill,
        skill_name: &skill_name,
        plan: None,
        endless,
        god,
        random_pick: text("--picker")?.as_deref() == Some("random"),
    };
    let todo: Vec<Option<&Plan>> =
        if plans.is_empty() { vec![None] } else { plans.iter().map(Some).collect() };
    let mut table = Vec::new();
    for (g, plan) in todo.into_iter().enumerate() {
        let cfg = Cfg { plan, ..base };
        let label = plan.map_or_else(|| "不限流派".to_string(), |p| p.name.clone());
        let rec = record.as_deref().filter(|_| g == 0);
        let all = run_all(&content, seed0, runs, jobs, cfg, rec);
        table.push(report(&content, &label, &all, plan, endless));
        if args.iter().any(|a| a == "--assert-build-pace") {
            let first: Vec<_> = all
                .iter()
                .filter_map(|r| r.tiers.iter().filter_map(|t| t[0]).min_by(f32::total_cmp))
                .collect();
            let evolved: Vec<_> = all.iter().filter_map(|r| r.evolutions.first().map(|v| v.0)).collect();
            if first.len() * 2 < all.len()
                || when(first) > 180.0
                || evolved.len() * 2 < all.len()
                || !(240.0..=420.0).contains(&when(evolved))
            {
                return Err(format!("{label} 未达到 3／6 分钟节奏；检查等级、存活率和选卡投入"));
            }
            if plan.is_some_and(|p| p.name.starts_with("合璧·")) {
                let fused: Vec<_> = all.iter().filter_map(|r| r.fusions.first().map(|v| v.0)).collect();
                if fused.len() * 2 < all.len() || when(fused) > 570.0 {
                    return Err(format!("{label} 未达到 9 分钟前后的合璧窗口"));
                }
            }
            println!("{label}：构筑节奏断言通过（真实刷怪、无赠送等级）");
        }
        groups.push((label, cfg, all));
    }
    if table.len() > 1 {
        println!("—— 对照 ——");
        println!("机器人 | 胜率 | 9 分等级 | 首次进化 | 二阶 | 三阶 | 极境 | 9 分清场 | 夜主 | 反应占比");
        for row in &table {
            println!("{}", row.join(" | "));
        }
    }
    println!("用时 {:.1} 秒", start.elapsed().as_secs_f64());
    if let Some(dir) = value("--csv") {
        write_csv(&content, Path::new(&dir), &groups)?;
    }
    Ok(())
}
