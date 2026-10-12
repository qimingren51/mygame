//! 数据文件对应的结构。字段含义写在 `assets/data/*.ron` 的注释里。

use serde::Deserialize;

/// 二次曲线 a + b·x + c·x²。x 通常是分钟数或等级。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
pub struct Quad(pub f32, pub f32, pub f32);

impl Quad {
    pub fn at(self, x: f32) -> f32 {
        self.0 + self.1 * x + self.2 * x * x
    }
}

/// 主角基础数值（`player.ron`）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PlayerDef {
    pub radius: f32,
    pub speed: f32,
    pub max_hp: f32,
    pub magnet: f32,
    /// 受伤后的无敌时间
    pub hurt_iframe: f32,
    pub crit_chance: f32,
    pub crit_mult: f32,
    /// 开局携带的法器 ID
    pub start_weapon: String,
    pub dash: DashDef,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct DashDef {
    pub duration: f32,
    pub speed: f32,
    pub cooldown: f32,
    pub iframe: f32,
}

/// 单局节奏（`run.ron`）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct RunDef {
    pub duration: f32,
    pub view_height: f32,
    pub max_aspect: f32,
    /// 第 n 级升到 n+1 级所需魂火
    pub xp_need: Quad,
    /// 以下三条的 x 是分钟数
    pub enemy_hp_scale: Quad,
    pub enemy_damage_scale: Quad,
    pub gem_value_scale: Quad,
    pub spawn: SpawnDef,
    pub gems: GemsDef,
    pub bench: BenchDef,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct SpawnDef {
    /// 每秒刷怪数（x 为分钟）
    pub rate: Quad,
    /// 场上超过这么多只就停止常规刷怪
    pub soft_cap: u32,
    /// 刷在视野外多远
    pub ring_extra: f32,
    /// 普通妖物离玩家超过“视野半对角线 × relocate”就绕到玩家前方
    pub relocate: f32,
    /// 绕到前方时的角度抖动（弧度）
    pub relocate_spread: f32,
    /// 每只妖物速度的随机倍率范围
    pub speed_jitter: (f32, f32),
    /// 默认刷出的妖物
    pub base: String,
    pub mix: Vec<MixDef>,
    pub packs: PackDef,
}

/// 混进常规刷怪的其他妖物。每局开局时在 share 范围内随机取一个比例。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct MixDef {
    pub enemy: String,
    pub from_minute: f32,
    pub share: (f32, f32),
    pub late_minute: f32,
    pub late_mult: f32,
}

/// 成群从同一方向涌来的妖物。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PackDef {
    /// 开局多少秒后开始
    pub start: f32,
    pub interval: (f32, f32),
    /// 每群只数（x 为分钟）
    pub size: Quad,
    /// 场上少于这么多只时才来
    pub max_alive: u32,
    pub spread: f32,
    /// 群里混入的其他妖物：比例是本局常规配比里该妖物的比例 × share_scale
    pub mix: Vec<PackMixDef>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PackMixDef {
    pub enemy: String,
    pub from_minute: f32,
    pub share_scale: f32,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct GemsDef {
    /// 场上魂火上限，超过后并入最近的一颗
    pub cap: u32,
    /// 落地多少秒没捡会自己飞回
    pub return_after: f32,
    pub accel: f32,
    pub max_speed: f32,
    /// 拾取距离 = 主角半径 + reach
    pub reach: f32,
    /// 精英掉落拆成几颗
    pub elite_split: u32,
    pub elite_scatter: f32,
}

/// 跑分模式：保持场上妖物数量，不升级。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct BenchDef {
    pub refill_per_tick: u32,
    pub enemy: String,
    pub alt_enemy: String,
    pub alt_share: f32,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
pub enum Rank {
    Normal,
    Elite,
    Boss,
    /// 奇遇里的小动物（金蟾），不计击杀
    Critter,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
pub enum Movement {
    /// 直奔玩家
    Chase,
    /// 背着玩家逃，路线左右摇摆
    Flee,
}

/// 妖物（`enemies.ron`）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct EnemyDef {
    pub id: String,
    pub name: String,
    pub rank: Rank,
    pub movement: Movement,
    pub radius: f32,
    pub hp: f32,
    pub speed: f32,
    pub damage: f32,
    pub xp: f32,
    /// 图集里的素材名
    pub sprite: String,
    /// 妖眼颜色（#RRGGBB）
    pub eye: String,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
pub enum Element {
    Metal,
    Wood,
    Water,
    Fire,
    Earth,
}

/// 法器的行为。新增行为 = 加一个变体，再在 `lantern_sim` 的 weapons 模块里实现。
#[derive(Clone, Debug, Deserialize, PartialEq)]
pub enum WeaponBehavior {
    /// 环绕周身（灯火）。spin 是转速（弧度/秒，x 为等级）。
    Orbit { spin: Quad, hit_cooldown: f32, knockback: f32, size: f32 },
}

/// 每一级的数值；没用到的字段省略。
#[derive(Clone, Debug, Default, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct WeaponLevel {
    pub count: u32,
    pub radius: f32,
    pub damage: f32,
    pub cooldown: f32,
    pub pierce: u32,
}

/// 法器（`weapons.ron`）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct WeaponDef {
    pub id: String,
    pub name: String,
    pub element: Element,
    pub behavior: WeaponBehavior,
    /// 第 1 级到满级
    pub levels: Vec<WeaponLevel>,
}
