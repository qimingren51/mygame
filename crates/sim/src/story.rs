//! 青丘檐下的两次停步。旧回放未带叙事快照时不启用，不占用旧路径的随机数。
//! 时间表保底出现，选择仍由玩家作出：护火要留在原地，留灯要另按一次交互。

use std::collections::BTreeSet;

use bevy_ecs::prelude::*;
use bevy_math::Vec2;
use lantern_content::StoryBeat;
use lantern_core::{StateHasher, Stream};
use serde::{Deserialize, Serialize};

use crate::{Health, Player, Pos, SimEvent, SimOutbox, SimRng, Tick};

pub const ARRIVE_TICK: u64 = 35 * 60;
pub const RADIUS: f32 = 64.0;
pub const GUARD_TICKS: u32 = 6 * 60;
pub const LEAVE_TICKS: u32 = 3 * 60;

/// 出发时冻结的存档快照，随回放保存；模拟从不读取 Profile。
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct StorySeed {
    pub events: BTreeSet<String>,
    pub journals: BTreeSet<u8>,
    pub chapter: u8,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VillageStage {
    Guard,
    Leave,
    Lit,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Village {
    pub pos: Vec2,
    pub stage: VillageStage,
    pub tending: bool,
    pub ticks: u32,
}

impl Village {
    pub fn near(&self, pos: Vec2) -> bool {
        self.pos.distance_squared(pos) <= RADIUS * RADIUS
    }

    pub fn duration(&self) -> u32 {
        if self.stage == VillageStage::Guard { GUARD_TICKS } else { LEAVE_TICKS }
    }
}

#[derive(Resource, Clone, Debug, Default)]
pub struct Story {
    pub seed: Option<StorySeed>,
    pub village: Option<Village>,
    pub events: BTreeSet<String>,
    pub journals: BTreeSet<u8>,
}

impl Story {
    pub fn new(seed: Option<StorySeed>) -> Self {
        Self { seed, ..Default::default() }
    }

    pub fn has(&self, beat: StoryBeat) -> bool {
        self.events.contains(beat.id()) || self.seed.as_ref().is_some_and(|s| s.events.contains(beat.id()))
    }

    pub fn chapter(&self) -> u8 {
        self.seed.as_ref().map_or(0, |s| s.chapter.clamp(1, 5)).max(if self.has(StoryBeat::LeftLantern) {
            3
        } else {
            0
        })
    }

    pub fn owns(&self, page: u8) -> bool {
        self.journals.contains(&page) || self.seed.as_ref().is_some_and(|s| s.journals.contains(&page))
    }

    fn found(&mut self, page: u8, outbox: &mut SimOutbox) {
        if !self.owns(page) {
            self.journals.insert(page);
            outbox.0.push(SimEvent::JournalFound { page });
        }
    }

    /// 每夜首次点灯/触碰奇遇必得一页，此后小概率，普通掉落每夜最多三页。
    /// 卷三一旦开放，第一张必为狐村；卷内抽未持有页，先补齐较早的卷。
    pub fn find_journal(&mut self, rng: &mut SimRng, outbox: &mut SimOutbox) {
        if self.seed.is_none() {
            return;
        }
        if self.chapter() >= 3 && !self.owns(13) {
            self.found(13, outbox);
            return;
        }
        if self.journals.len() >= 3 {
            return;
        }
        let candidates: Vec<u8> = (1..=self.chapter() * 6).filter(|&p| !self.owns(p)).collect();
        let Some(&first) = candidates.first() else { return };
        let candidates: Vec<u8> = candidates.into_iter().filter(|p| (p - 1) / 6 == (first - 1) / 6).collect();
        // 手记用自己的叙事流，不挤占奇遇的随机数。
        let rng = rng.0.get(Stream::Story);
        if !self.journals.is_empty() && !rng.chance(0.35) {
            return;
        }
        self.found(candidates[rng.below(candidates.len() as u32) as usize], outbox);
    }

    /// 只受交互命令驱动。路过、远处按键、护火未完都不能直接留灯。
    pub fn interact(&mut self, pos: Vec2) {
        if let Some(v) = &mut self.village
            && v.near(pos)
            && v.stage != VillageStage::Lit
            && !v.tending
        {
            v.tending = true;
            v.ticks = 0;
        }
    }

    /// 只在启用时写哈希（含叙事随机流）；未启用的局哈希与旧版一致。
    pub fn hash_into(&self, rng: &SimRng, h: &mut StateHasher) {
        let Some(seed) = &self.seed else { return };
        h.write_bytes(b"qingqiu-story-v1");
        rng.0.hash_stream(Stream::Story, h);
        h.write_u32(seed.chapter as u32);
        for set in [&seed.events, &self.events] {
            h.write_u32(set.len() as u32);
            for id in set {
                h.write_u32(id.len() as u32);
                h.write_bytes(id.as_bytes());
            }
        }
        for set in [&seed.journals, &self.journals] {
            h.write_u32(set.len() as u32);
            for page in set {
                h.write_u32(*page as u32);
            }
        }
        h.write_u32(u32::from(self.village.is_some()));
        if let Some(v) = &self.village {
            h.write_f32(v.pos.x);
            h.write_f32(v.pos.y);
            h.write_u32(v.stage as u32);
            h.write_u32(v.ticks);
            h.write_u32(u32::from(v.tending));
        }
    }
}

pub(crate) fn update_story(
    tick: Res<Tick>,
    player: Single<(&Pos, &Health), With<Player>>,
    mut story: ResMut<Story>,
    mut outbox: ResMut<SimOutbox>,
) {
    if story.seed.is_none() {
        return;
    }
    // 走进青丘就是可保存的见闻；未完成的故事点每夜固定出现且不消失。
    if !story.events.contains("qingqiu_entered") {
        story.events.insert("qingqiu_entered".into());
    }
    let (pos, hp) = *player;
    if hp.hp <= 0.0 {
        if let Some(v) = &mut story.village {
            v.tending = false;
            v.ticks = 0;
        }
        return;
    }
    if story.village.is_none() && tick.0 >= ARRIVE_TICK && !story.has(StoryBeat::LeftLantern) {
        let stage = if story.has(StoryBeat::GuardedFire) { VillageStage::Leave } else { VillageStage::Guard };
        story.village =
            Some(Village { pos: pos.0 + Vec2::new(96.0, -24.0), stage, tending: false, ticks: 0 });
    }
    let Some(v) = &mut story.village else { return };
    if !v.tending {
        return;
    }
    if !v.near(pos.0) {
        // 可以随时离开；下一次停下来重新护住这一阵风，不惩罚生命或货币。
        v.tending = false;
        v.ticks = 0;
        return;
    }
    v.ticks += 1;
    if v.ticks < v.duration() {
        return;
    }
    let beat = if v.stage == VillageStage::Guard { StoryBeat::GuardedFire } else { StoryBeat::LeftLantern };
    v.stage = if beat == StoryBeat::GuardedFire { VillageStage::Leave } else { VillageStage::Lit };
    v.tending = false;
    v.ticks = 0;
    if story.events.insert(beat.id().into()) {
        outbox.0.push(SimEvent::StoryBeat { beat });
    }
    // 砖缝里压着前辈的纸：留灯时亲手摸到，狐村关键页不受随机数支配。
    if beat == StoryBeat::LeftLantern {
        story.found(13, &mut outbox);
    }
}
