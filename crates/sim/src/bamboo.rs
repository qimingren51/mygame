//! 竹丛（docs/BALANCE.md 第 12.7 节）：青丘的软障碍，不挡路，主角和妖物穿过时减速，可以打碎。
//!
//! 地图按块生成：主角走到哪，周围 5 × 5 块还没长过的就按“种子 + 块坐标”长出竹丛，同一个种子地图一样，
//! 不消耗模拟的随机流。长过的块一直记着（打碎、烧平的状态不丢）。
//! 查询用主角周围的一张格子表（[`Window`]），主角换块时重建。
//!
//! 法器、飞剑、范围打击、反应、灯焰带打到竹丛时往 [`Bamboo::hits`] 里记一笔，Status 阶段统一结算。
//! 打竹丛不算命中妖物：不打印记、不触发心法和灯坠、不计连斩。

use std::collections::BTreeSet;

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::BambooDef;
use lantern_core::step::DT;
use lantern_core::{Pcg32, StateHasher, Stream};

use crate::encounters::Encounters;
use crate::gold::Coins;
use crate::lanterns::Lanterns;
use crate::run::Director;
use crate::{GameContent, Player, Pos, SimEvent, SimOutbox, SimRng};

const TAU: f32 = std::f32::consts::TAU;
/// 主角周围几圈块要长好竹丛
const KEEP: i32 = 2;
/// 查询格子的边长
const CELL: f32 = 64.0;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ClumpState {
    Standing,
    /// 打碎了，还要多久长回来
    Broken(f32),
    /// 夜主登场时被狐火烧平，这一夜不再长
    Burned,
    /// 奇遇、货郎出现在旁边，让开了
    Cleared,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Clump {
    pub pos: Vec2,
    pub hp: f32,
    pub state: ClumpState,
    /// 受伤间隔
    pub cd: f32,
    /// 本步打到它的最大一笔（结算时清零）
    pending: f32,
}

impl Clump {
    pub fn standing(&self) -> bool {
        self.state == ClumpState::Standing
    }
}

/// 一笔打到竹丛的伤害：以 pos 为圆心、inner 到 outer 之间的环（实心圆 inner = 0）。
#[derive(Clone, Copy, Debug)]
pub struct BambooHit {
    pub pos: Vec2,
    pub inner: f32,
    pub outer: f32,
    pub damage: f32,
}

/// 主角周围的格子表：每格记着压到这一格的竹丛（下标）。
#[derive(Debug, Default)]
struct Window {
    /// 中心块；None 表示还没建
    center: Option<(i32, i32)>,
    /// 左下角（世界坐标）和每边格数
    origin: Vec2,
    side: usize,
    /// 压缩存储：第 k 格的竹丛是 items[start[k]..start[k + 1]]
    start: Vec<u32>,
    items: Vec<u32>,
    /// 窗口里的全部竹丛（打击查询用）
    near: Vec<u32>,
}

#[derive(Resource, Debug, Default)]
pub struct Bamboo {
    pub clumps: Vec<Clump>,
    /// 本步打到竹丛的伤害
    pub hits: Vec<BambooHit>,
    /// 已经长过竹丛的块
    chunks: BTreeSet<(i32, i32)>,
    /// 最近一次烧平的结界
    burned: Option<(Vec2, f32)>,
    window: Window,
    /// 判定半径、减速（开局从数据里抄来，查询时用）
    radius: f32,
    slow: f32,
}

impl Bamboo {
    pub fn new(def: Option<&BambooDef>) -> Self {
        Bamboo {
            radius: def.map_or(0.0, |d| d.radius),
            slow: def.map_or(0.0, |d| d.slow),
            ..Default::default()
        }
    }

    /// 站在 p 处的移速倍率：在立着的竹丛里是 1 − slow，否则 1。
    pub fn speed_at(&self, p: Vec2) -> f32 {
        if self.inside(p) { 1.0 - self.slow } else { 1.0 }
    }

    fn inside(&self, p: Vec2) -> bool {
        let w = &self.window;
        if w.side == 0 {
            return false;
        }
        let rel = (p - w.origin) / CELL;
        if rel.x < 0.0 || rel.y < 0.0 || rel.x >= w.side as f32 || rel.y >= w.side as f32 {
            return false;
        }
        let k = rel.y as usize * w.side + rel.x as usize;
        let r2 = self.radius * self.radius;
        w.items[w.start[k] as usize..w.start[k + 1] as usize].iter().any(|&i| {
            let c = &self.clumps[i as usize];
            c.standing() && c.pos.distance_squared(p) <= r2
        })
    }

    /// 记一笔圆形范围的伤害。
    pub fn circle(&mut self, pos: Vec2, radius: f32, damage: f32) {
        self.ring(pos, 0.0, radius, damage);
    }

    /// 记一笔环形范围的伤害（灯焰带）。
    pub fn ring(&mut self, pos: Vec2, inner: f32, outer: f32, damage: f32) {
        if damage > 0.0 && !self.clumps.is_empty() {
            self.hits.push(BambooHit { pos, inner, outer, damage });
        }
    }

    /// 视野附近的竹丛（画面用）。
    pub fn near(&self) -> impl Iterator<Item = &Clump> {
        self.window.near.iter().map(|&i| &self.clumps[i as usize])
    }

    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.clumps.len() as u32);
        for c in &self.clumps {
            h.write_f32(c.hp);
            h.write_f32(c.cd);
            match c.state {
                ClumpState::Standing => h.write_u32(0),
                ClumpState::Broken(t) => {
                    h.write_u32(1);
                    h.write_f32(t);
                }
                ClumpState::Burned => h.write_u32(2),
                ClumpState::Cleared => h.write_u32(3),
            }
        }
    }

    /// 长出一块的竹丛。
    fn grow_chunk(&mut self, def: &BambooDef, rng: &mut Pcg32, (cx, cy): (i32, i32), lanterns: &Lanterns) {
        let blocked = |p: Vec2| {
            p.length_squared() < def.clear_spawn * def.clear_spawn
                || lanterns
                    .0
                    .iter()
                    .any(|l| l.pos.distance_squared(p) < def.clear_lantern * def.clear_lantern)
        };
        let n = def.per_chunk.0 + rng.below(def.per_chunk.1 - def.per_chunk.0 + 1);
        for _ in 0..n {
            let at = Vec2::new(cx as f32 + rng.next_f32(), cy as f32 + rng.next_f32()) * def.chunk;
            let place = |p: Vec2, clumps: &mut Vec<Clump>| {
                if !blocked(p) {
                    clumps.push(Clump {
                        pos: p,
                        hp: def.hp,
                        state: ClumpState::Standing,
                        cd: 0.0,
                        pending: 0.0,
                    });
                }
            };
            place(at, &mut self.clumps);
            if rng.chance(def.cluster_chance) {
                let extra = def.cluster.0 + rng.below(def.cluster.1 - def.cluster.0 + 1);
                for _ in 0..extra {
                    let a = rng.range_f32(0.0, TAU);
                    let r = rng.range_f32(def.radius, def.cluster_radius);
                    let (s, c) = bevy_math::ops::sin_cos(a);
                    place(at + Vec2::new(c, s) * r, &mut self.clumps);
                }
            }
        }
    }

    /// 以 center 块为中心重建格子表。
    fn rebuild(&mut self, def: &BambooDef, center: (i32, i32)) {
        let w = &mut self.window;
        w.center = Some(center);
        let span = (2 * KEEP + 1) as f32 * def.chunk;
        w.origin = Vec2::new((center.0 - KEEP) as f32, (center.1 - KEEP) as f32) * def.chunk;
        w.side = (span / CELL).ceil() as usize;
        let cells = w.side * w.side;
        let r = self.radius;
        let lo = w.origin - Vec2::splat(r);
        let hi = w.origin + Vec2::splat(span + r);
        w.near.clear();
        w.near.extend((0..self.clumps.len() as u32).filter(|&i| {
            let p = self.clumps[i as usize].pos;
            p.x >= lo.x && p.y >= lo.y && p.x < hi.x && p.y < hi.y
        }));
        // 每格先数个数，再填
        let side = w.side as i32;
        let cover = |p: Vec2| {
            let a = ((p - Vec2::splat(r) - w.origin) / CELL).floor();
            let b = ((p + Vec2::splat(r) - w.origin) / CELL).floor();
            let (x0, y0) = ((a.x as i32).max(0), (a.y as i32).max(0));
            let (x1, y1) = ((b.x as i32).min(side - 1), (b.y as i32).min(side - 1));
            (x0, y0, x1, y1)
        };
        let mut count = vec![0u32; cells + 1];
        for &i in &w.near {
            let (x0, y0, x1, y1) = cover(self.clumps[i as usize].pos);
            for y in y0..=y1 {
                for x in x0..=x1 {
                    count[y as usize * w.side + x as usize + 1] += 1;
                }
            }
        }
        for k in 0..cells {
            count[k + 1] += count[k];
        }
        let mut fill = count.clone();
        w.items.clear();
        w.items.resize(count[cells] as usize, 0);
        for &i in &w.near {
            let (x0, y0, x1, y1) = cover(self.clumps[i as usize].pos);
            for y in y0..=y1 {
                for x in x0..=x1 {
                    let k = y as usize * w.side + x as usize;
                    w.items[fill[k] as usize] = i;
                    fill[k] += 1;
                }
            }
        }
        w.start = count;
    }
}

/// 块坐标打成随机数的键；异或一个常数区分用途，以后别的地图元素用别的常数。
fn chunk_key((cx, cy): (i32, i32)) -> u64 {
    (((cx as u32 as u64) << 32) | cy as u32 as u64) ^ 0xB4B0_0C1A_0000_0000
}

/// 每步：主角附近长竹丛；奇遇旁边的让开；夜主的结界里烧平；打碎的到时间长回来。
pub(crate) fn update_bamboo(
    content: Res<GameContent>,
    rng: Res<SimRng>,
    director: Res<Director>,
    lanterns: Res<Lanterns>,
    encounters: Res<Encounters>,
    player: Single<&Pos, With<Player>>,
    mut bamboo: ResMut<Bamboo>,
    mut outbox: ResMut<SimOutbox>,
) {
    let Some(def) = &content.0.run.bamboo else { return };
    let p = player.0;
    let b = &mut *bamboo;
    // 长竹丛、换窗口
    let center = ((p.x / def.chunk).floor() as i32, (p.y / def.chunk).floor() as i32);
    if b.window.center != Some(center) {
        for cy in center.1 - KEEP..=center.1 + KEEP {
            for cx in center.0 - KEEP..=center.0 + KEEP {
                if b.chunks.insert((cx, cy)) {
                    let mut chunk_rng = rng.0.derive(chunk_key((cx, cy)));
                    b.grow_chunk(def, &mut chunk_rng, (cx, cy), &lanterns);
                }
            }
        }
        b.rebuild(def, center);
    }
    let reach =
        |c: &Clump, at: Vec2, r: f32| c.pos.distance_squared(at) < (r + def.radius) * (r + def.radius);
    // 奇遇、货郎旁边不长
    for e in &encounters.list {
        for &i in &b.window.near {
            let c = &mut b.clumps[i as usize];
            if c.state != ClumpState::Cleared
                && c.state != ClumpState::Burned
                && reach(c, e.pos, def.clear_event)
            {
                c.state = ClumpState::Cleared;
            }
        }
    }
    // 夜主登场：结界里的竹丛烧平
    if let Some((at, r)) = director.barrier
        && b.burned != Some((at, r))
    {
        b.burned = Some((at, r));
        let mut count = 0;
        for &i in &b.window.near {
            let c = &mut b.clumps[i as usize];
            if c.pos.distance_squared(at) < r * r
                && matches!(c.state, ClumpState::Standing | ClumpState::Broken(_))
            {
                c.state = ClumpState::Burned;
                count += 1;
            }
        }
        if count > 0 {
            outbox.0.push(SimEvent::BambooBurned { pos: at, radius: r });
        }
    }
    // 长回来：主角离得够远才长，免得从脚下冒出来
    let clear2 = def.regrow_clear * def.regrow_clear;
    for c in &mut b.clumps {
        c.cd -= DT;
        if let ClumpState::Broken(t) = &mut c.state {
            *t -= DT;
            if *t <= 0.0 && c.pos.distance_squared(p) > clear2 {
                c.state = ClumpState::Standing;
                c.hp = def.hp;
            }
        }
    }
}

/// 结算本步打到竹丛的伤害：每丛取打到它的最大一笔，打完隔 hit_every 秒才能再受伤。
pub(crate) fn hit_bamboo(
    content: Res<GameContent>,
    mut rng: ResMut<SimRng>,
    mut bamboo: ResMut<Bamboo>,
    mut coins: ResMut<Coins>,
    mut outbox: ResMut<SimOutbox>,
) {
    let Some(def) = &content.0.run.bamboo else { return };
    let b = &mut *bamboo;
    if b.hits.is_empty() {
        return;
    }
    let gold = &content.0.run.gold;
    let drop = rng.0.get(Stream::Drop);
    // 每丛记下打到它的最大一笔；只查伤害范围压到的格子
    let w = &b.window;
    let side = w.side as i32;
    for h in &b.hits {
        let reach = h.outer + def.radius;
        let a = ((h.pos - Vec2::splat(reach) - w.origin) / CELL).floor();
        let z = ((h.pos + Vec2::splat(reach) - w.origin) / CELL).floor();
        for y in (a.y as i32).max(0)..=(z.y as i32).min(side - 1) {
            for x in (a.x as i32).max(0)..=(z.x as i32).min(side - 1) {
                let k = y as usize * w.side + x as usize;
                for &i in &w.items[w.start[k] as usize..w.start[k + 1] as usize] {
                    let c = &mut b.clumps[i as usize];
                    if !c.standing() || c.cd > 0.0 || c.pending >= h.damage {
                        continue;
                    }
                    let d = c.pos.distance(h.pos);
                    if d < reach && d + def.radius > h.inner {
                        c.pending = h.damage;
                    }
                }
            }
        }
    }
    for &i in &w.near {
        let c = &mut b.clumps[i as usize];
        let dmg = std::mem::take(&mut c.pending);
        if dmg <= 0.0 {
            continue;
        }
        c.hp -= dmg;
        c.cd = def.hit_every;
        if c.hp <= 0.0 {
            c.state = ClumpState::Broken(def.regrow);
            outbox.0.push(SimEvent::BambooBroken { pos: c.pos });
            if drop.chance(def.coin_chance) {
                coins.drop(c.pos, gold.coin_value as f32, gold.cap);
            }
        }
    }
    b.hits.clear();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn def() -> BambooDef {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data");
        lantern_content::Content::load(&dir).unwrap().run.bamboo.unwrap()
    }

    /// 同一个种子、同一块，长出来的竹丛一样；出生点附近不长。
    #[test]
    fn chunks_grow_the_same_for_a_seed() {
        let d = def();
        let lanterns = Lanterns::default();
        let grow = |seed: u64, chunk: (i32, i32)| {
            let mut b = Bamboo::new(Some(&d));
            let streams = lantern_core::Streams::new(seed);
            b.grow_chunk(&d, &mut streams.derive(chunk_key(chunk)), chunk, &lanterns);
            b.clumps.iter().map(|c| c.pos).collect::<Vec<_>>()
        };
        assert_eq!(grow(3, (4, -2)), grow(3, (4, -2)));
        assert_ne!(grow(3, (4, -2)), grow(4, (4, -2)));
        for k in -1..=0 {
            assert!(grow(5, (k, k)).iter().all(|p| p.length() >= d.clear_spawn));
        }
    }

    /// 站在竹丛里减速；格子表跨格、跨块都查得到。
    #[test]
    fn standing_in_a_clump_slows() {
        let d = def();
        let mut b = Bamboo::new(Some(&d));
        for &pos in &[Vec2::new(700.0, 700.0), Vec2::new(512.0 + 10.0, -3.0), Vec2::new(-64.0, 128.0)] {
            b.clumps.push(Clump { pos, hp: d.hp, state: ClumpState::Standing, cd: 0.0, pending: 0.0 });
        }
        b.rebuild(&d, (0, 0));
        assert_eq!(b.speed_at(Vec2::new(720.0, 690.0)), 1.0 - d.slow);
        assert_eq!(b.speed_at(Vec2::new(512.0 - 20.0, 10.0)), 1.0 - d.slow);
        assert_eq!(b.speed_at(Vec2::new(-64.0 + 30.0, 128.0 - 10.0)), 1.0 - d.slow);
        assert_eq!(b.speed_at(Vec2::new(300.0, 300.0)), 1.0);
        // 窗口外的不算
        assert_eq!(b.speed_at(Vec2::new(5000.0, 0.0)), 1.0);
        b.clumps[0].state = ClumpState::Broken(10.0);
        assert_eq!(b.speed_at(Vec2::new(720.0, 690.0)), 1.0, "打碎的不减速");
    }
}
