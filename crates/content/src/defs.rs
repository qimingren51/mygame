//! 数据文件对应的结构。字段含义写在 `assets/data/*.ron` 的注释里。

use serde::{Deserialize, Serialize};

use crate::Effect;

/// 二次曲线 a + b·x + c·x²。x 通常是分钟数或等级。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
pub struct Quad(pub f32, pub f32, pub f32);

impl Quad {
    pub fn at(self, x: f32) -> f32 {
        self.0 + self.1 * x + self.2 * x * x
    }
}

/// 主角（`player.ron`）。可成长的数值（移速、生命、拾取范围、暴击……）在 `stats.ron`。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PlayerDef {
    pub radius: f32,
    /// 受伤后的无敌时间
    pub hurt_iframe: f32,
    /// 开局携带的法器 ID
    pub start_weapon: String,
    pub dash: DashDef,
    pub ult: UltDef,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct DashDef {
    pub duration: f32,
    pub speed: f32,
    pub cooldown: f32,
    pub iframe: f32,
}

/// 燃灯（大招）：击杀充能，充满后对视野内所有妖物造成伤害并清掉弹幕。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct UltDef {
    /// 击杀一只普通妖物、精英各充多少（满为 1）
    pub charge_normal: f32,
    pub charge_elite: f32,
    /// 伤害（x 为分钟）
    pub damage: Quad,
    pub knockback: f32,
    /// 对夜主改为最大生命的这个比例
    pub boss_fraction: f32,
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
    /// 精英、妖潮、夜主的出场时间表，按时间排列
    pub schedule: Vec<PlanStepDef>,
    /// 击败夜主后多少秒进入结算
    pub win_delay: f32,
    pub gems: GemsDef,
    pub drops: DropsDef,
    pub choices: ChoicesDef,
    pub combo: ComboDef,
    pub oil: OilDef,
    pub bench: BenchDef,
}

/// 时间表的一项：在 at 范围内随机一个时刻出场。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PlanStepDef {
    pub at: (f32, f32),
    pub event: PlanEvent,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub enum PlanEvent {
    /// 从列表里随机一种精英（数量见 [`crate::Stat::EliteCount`]）
    Elite(Vec<String>),
    /// 妖潮：持续一段时间，刷怪倍率提高，同时出一只精英
    Surge { duration: f32, rate_mult: f32, elites: Vec<String> },
    /// 夜主出场，此后刷怪倍率乘以 spawn_mult
    Boss { enemy: String, spawn_mult: f32 },
}

/// 掉落物。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct DropsDef {
    /// 拾取距离 = 主角半径 + reach
    pub reach: f32,
    /// 普通妖物掉引魂铃（吸来全部魂火）、莲子（回复）的概率
    pub bell_chance: f32,
    pub lotus_chance: f32,
    /// 莲子回复生命上限的比例
    pub lotus_heal: f32,
}

/// 升级选项与宝箱（docs/PORTING-NOTES.md 第 4.4 节）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ChoicesDef {
    /// 法器、心法各最多几个
    pub slots: u32,
    pub weight_evolve: f32,
    pub weight_weapon_up: f32,
    pub weight_new_weapon: f32,
    /// late_after 秒之后新法器的权重
    pub weight_new_weapon_late: f32,
    pub late_after: f32,
    pub weight_passive_up: f32,
    pub weight_new_passive: f32,
    /// 已有 2 点以上的五行，选项权重乘以它
    pub owned_element_mult: f32,
    /// 夜签偏重：同系、其他系的权重倍率
    pub favor_mult: f32,
    pub unfavor_mult: f32,
    /// “灵光一闪”：三选一时变成四选一的概率
    pub inspiration: f32,
    /// 什么都满了时的补给：回复生命上限的比例、灯油
    pub heal: f32,
    pub oil: u32,
    /// 跳过一次得到的灯油
    pub skip_oil: u32,
    /// 宝箱：随机数（加上运气）超过阈值时开出的个数，从高到低
    pub chest_odds: Vec<(f32, u32)>,
}

/// 连斩：两次击杀间隔不超过 window 秒时连续计数。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ComboDef {
    pub window: f32,
    /// 达到这些数时提示
    pub milestones: Vec<u32>,
}

/// 灯油结算：(存活秒数 × per_second + 击杀 × per_kill + 胜利奖励 + 局内额外) × 灯油倍率。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct OilDef {
    pub per_second: f32,
    pub per_kill: f32,
    pub win: u32,
    /// 存活时间最多计这么多秒
    pub max_seconds: f32,
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
    /// 出场提示里的称号（例如“小头目”），不写时按 rank 显示
    #[serde(default)]
    pub title: Option<String>,
    /// 夜主的招式
    #[serde(default)]
    pub boss: Option<BossDef>,
    /// 奇遇小动物被打死时的奖励
    #[serde(default)]
    pub loot: Option<CritterLoot>,
}

/// 夜主的招式：每隔一段时间放一圈弹幕、召唤小妖。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct BossDef {
    pub volley_every: f32,
    pub volley_first: f32,
    pub volley_count: u32,
    pub shot_speed: f32,
    pub shot_radius: f32,
    pub shot_damage: f32,
    pub shot_life: f32,
    pub summon_every: f32,
    pub summon: String,
    pub summon_count: u32,
    pub summon_radius: f32,
}

/// 金蟾：打死后散落相当于当前等级所需 xp_levels 倍的魂火，另加灯油。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CritterLoot {
    pub xp_levels: f32,
    pub gems: u32,
    pub scatter: (f32, f32),
    pub oil: u32,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Element {
    Metal,
    Wood,
    Water,
    Fire,
    Earth,
}

impl Element {
    pub const ALL: [Element; 5] =
        [Element::Metal, Element::Wood, Element::Water, Element::Fire, Element::Earth];

    pub fn index(self) -> usize {
        self as usize
    }
}

/// 法器的行为。新增行为 = 加一个变体，再在 `lantern_sim` 的 weapons 模块里实现。
/// 进化后的法器用同一种行为，参数可以不同。
#[derive(Clone, Debug, Deserialize, PartialEq)]
pub enum WeaponBehavior {
    /// 环绕周身（灯火）。spin 是转速（弧度/秒，x 为等级）；同一只妖物 hit_cooldown 秒内只吃一次。
    Orbit { spin: Quad, hit_cooldown: f32, knockback: f32, size: f32 },
    /// 朝最近的妖物齐射追踪飞行物（符剑）。
    Volley {
        /// 找目标的距离
        range: f32,
        speed: f32,
        life: f32,
        /// 追踪转向速度（弧度/秒）
        turn: f32,
        hit_radius: f32,
        knockback: f32,
        /// 齐射时相邻两发的角度间隔
        spread: f32,
        /// 没有目标时多久再找一次
        retry: f32,
    },
    /// 以主角为中心周期震出一圈（霜铃）；toll 是进化后的全屏钟鸣。
    Pulse {
        knockback: f32,
        slow: f32,
        slow_time: f32,
        #[serde(default)]
        toll: Option<TollDef>,
    },
    /// 平时绕身，随机扑向附近的妖物，撞到后折返（纸鹤）。速度 speed 的 x 为等级。
    Seeker {
        orbit_radius: f32,
        orbit_spin: f32,
        range: f32,
        /// 从最近的几只里随机挑
        pick: u32,
        rest: f32,
        knockback: f32,
        speed: Quad,
        /// 转向的跟随系数（每秒）
        steer: f32,
        /// 撞击判定：目标半径 + reach
        reach: f32,
    },
    /// 从天而降的范围伤害（山印）；fissure 是进化后留下的地裂。
    Drop {
        /// 从 range 内最近的 candidates 只里随机选落点
        range: f32,
        candidates: u32,
        /// 预警时间、依次落下的间隔
        delay: f32,
        stagger: f32,
        knockback: f32,
        stun: f32,
        /// 没有目标时在主角周围随机落下的范围（半宽、半高）
        scatter: (f32, f32),
        /// 数量加值每 amount_div 点才多一个
        amount_div: u32,
        #[serde(default)]
        fissure: Option<FissureDef>,
    },
}

/// 全屏钟鸣：冻结视野内的妖物（夜主除外）并造成伤害。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct TollDef {
    pub period: f32,
    pub damage: f32,
    pub freeze: f32,
    pub boss_cap: f32,
}

/// 地裂：持续伤害并减速。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct FissureDef {
    pub radius_scale: f32,
    pub life: f32,
    pub tick: f32,
    pub damage_scale: f32,
    pub slow: f32,
    pub slow_time: f32,
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
    /// 卡片和信息栏上的单字图标
    pub icon: String,
    pub element: Element,
    pub desc: String,
    pub behavior: WeaponBehavior,
    /// 第 1 级到满级
    pub levels: Vec<WeaponLevel>,
    pub evolution: Option<EvolutionDef>,
}

/// 进化：满级并持有对应心法后，下次升级必出。进化后换成另一套行为参数和数值。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct EvolutionDef {
    pub name: String,
    pub desc: String,
    /// 需要的心法 ID
    pub passive: String,
    pub behavior: WeaponBehavior,
    pub level: WeaponLevel,
}

/// 心法（`passives.ron`）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PassiveDef {
    pub id: String,
    pub name: String,
    pub element: Element,
    pub desc: String,
    pub max_level: u32,
    /// 每级都加一次的效果
    #[serde(default)]
    pub per_level: Vec<Effect>,
    /// 或者逐级写：第 k 项是升到 k+1 级时新加的效果
    #[serde(default)]
    pub levels: Vec<Vec<Effect>>,
}

/// 五行（`elements.ron`）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ElementsDef {
    /// 一、二、三阶共鸣需要的点数
    pub thresholds: Vec<u32>,
    /// 按 [`Element::ALL`] 的顺序
    pub elements: Vec<ElementDef>,
    /// 相生：相邻两系都至少一阶时点亮
    pub sheng: Vec<ShengDef>,
    /// 太极：五系都至少一阶时点亮
    pub taiji: TaijiDef,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ElementDef {
    pub id: Element,
    /// 金、木、水、火、土
    pub name: String,
    /// 共鸣名：锐、生、凝、焚、固
    pub resonance: String,
    pub color: String,
    pub tiers: Vec<TierDef>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct TierDef {
    pub desc: String,
    pub effects: Vec<Effect>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ShengDef {
    pub from: Element,
    pub to: Element,
    pub name: String,
    pub desc: String,
    pub effects: Vec<Effect>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct TaijiDef {
    pub name: String,
    pub desc: String,
    pub effects: Vec<Effect>,
}

/// 夜签（`omens.ron`）：开局三选一的本局规则，有好处也有代价。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct OmenDef {
    pub id: String,
    pub name: String,
    /// 好处；pick_element 时其中的 {el} 换成选定的五行名
    pub good: String,
    pub bad: String,
    /// 抽到时随机选定一种五行（[`Effect::Points`]、[`Effect::Favor`] 作用于它）
    #[serde(default)]
    pub pick_element: bool,
    pub effects: Vec<Effect>,
}

/// 奇遇（`events.ron`）：地图上随机出现的事件。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct EventsDef {
    /// 第一个奇遇出现的时刻范围、之后的间隔（再除以 [`crate::Stat::EventRate`]）
    pub first: (f32, f32),
    pub interval: (f32, f32),
    pub kinds: Vec<EventDef>,
    /// 古灯的随机增益
    pub buffs: Vec<BuffDef>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct EventDef {
    pub id: String,
    pub name: String,
    pub hint: String,
    pub color: String,
    pub weight: f32,
    /// 出现在离主角多远的地方
    pub distance: f32,
    /// 存在多少秒
    pub life: f32,
    pub kind: EventKind,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub enum EventKind {
    /// 会逃跑的小动物，打死有奖励（distance 是视野半对角线的倍数）
    Critter { enemy: String },
    /// 站在泉里每秒回复生命上限的 heal 比例；无法回复生命时不出现
    Spring { radius: f32, heal: f32 },
    /// 碰到后获得随机增益
    Shrine { radius: f32, duration: f32 },
    /// 碰到后失去 cost 比例的生命上限（至少留 1），换宝箱
    Altar { radius: f32, cost: f32, chests: u32 },
    /// 一群妖物加一个守卫精英（守卫掉宝箱）
    Rift {
        minions: Quad,
        spread: (f32, f32),
        base: String,
        alt: String,
        alt_share: f32,
        guards: Vec<String>,
        /// late_minute 分钟后守卫还可能是这些
        late_guards: Vec<String>,
        late_minute: f32,
    },
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct BuffDef {
    pub id: String,
    pub name: String,
    pub desc: String,
    pub color: String,
    pub effects: Vec<Effect>,
}

/// 心灯（`meta.ron`）：局外成长。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct MetaDef {
    pub max_level: u32,
    /// 点亮第 n 级（从 1 起）的花费 = round(base × n^exp / round_to) × round_to
    pub cost_base: f32,
    pub cost_exp: f32,
    pub cost_round: f32,
    pub lines: Vec<MetaLineDef>,
}

impl MetaDef {
    /// 从 level 级升到 level + 1 级的花费。
    pub fn cost(&self, level: u32) -> u32 {
        let n = (level + 1) as f32;
        let raw = self.cost_base * n.powf(self.cost_exp) / self.cost_round;
        (raw.round() * self.cost_round) as u32
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct MetaLineDef {
    pub id: String,
    pub name: String,
    pub icon: String,
    pub desc: String,
    pub per_level: Vec<Effect>,
}
