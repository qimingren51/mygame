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
    /// 闪避的冷却、段数、距离倍率在 `stats.ron`
    pub dash: DashDef,
    pub ult: UltDef,
    pub reveal: RevealDef,
    pub charms: CharmTuning,
    pub rescue: RescueDef,
}

/// 灯坠的局内机制参数（docs/GAMEPLAY.md 第 5.7 节）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CharmTuning {
    /// 定海神针：站着不动多久算“站定”
    pub still_after: f32,
    /// 风火轮的火痕：闪避每走这么远留一段；半径、持续时间。
    /// 每秒伤害 = TrailDamage × 单次伤害最高的那件法器的基础伤害
    pub trail_gap: f32,
    pub trail_radius: f32,
    pub trail_life: f32,
    /// 霜瓷灯：冻住攻击者几秒（再乘冰冻时长）
    pub thorn_freeze: f32,
}

/// 倒下前的救命：回光（心灯）、九转金丹（灯坠）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct RescueDef {
    /// 回光 2 级时回复生命上限的比例；九转金丹回复的比例（都不受回复倍率影响）
    pub last_stand_heal: f32,
    pub revive_heal: f32,
    /// 回光震退周围这么大一圈；九转金丹震退全屏
    pub radius: f32,
    pub knockback: f32,
    /// 之后的无敌时间
    pub iframe: f32,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct DashDef {
    pub duration: f32,
    pub speed: f32,
    pub iframe: f32,
}

/// 照见圈与灯焰带（docs/GAMEPLAY.md 第 4.2 节，docs/BALANCE.md 第 7.3 节）。
/// 照见圈的基础半径和上限在 `stats.ron` 的 Reveal。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct RevealDef {
    /// 每升一级，照见圈、灯光各乘上多少
    pub per_level: f32,
    pub light_per_level: f32,
    /// 灯焰带：照见圈最外面一圈的宽度；每秒伤害（x 为主角等级），灯芯每多一级再乘 (1 + per_rank)
    pub band_width: f32,
    pub band_dps: Quad,
    pub band_per_rank: f32,
}

/// 燃灯（大招）：按清怪量充能，充满后对视野内所有妖物造成伤害并清掉弹幕（docs/BALANCE.md 第 4.5 节）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct UltDef {
    /// 击杀一只妖物充 它的最大生命 ÷（基础刷怪曲线每秒刷出的总血量 × clear_seconds）
    pub clear_seconds: f32,
    /// 精英额外充多少（满为 1）
    pub charge_elite: f32,
    /// 伤害（x 为分钟）
    pub damage: Quad,
    pub knockback: f32,
    /// 对夜主每次不超过它最大生命的这个比例
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
    /// 以下几条的 x 是分钟数。精英和小头目用单独的生命曲线
    pub enemy_hp_scale: Quad,
    pub elite_hp_scale: Quad,
    pub enemy_damage_scale: Quad,
    pub gem_value_scale: Quad,
    pub spawn: SpawnDef,
    /// 精英、妖潮、夜主的出场时间表，按时间排列
    pub schedule: Vec<PlanStepDef>,
    /// 击败夜主后多少秒进入结算
    pub win_delay: f32,
    pub gems: GemsDef,
    pub drops: DropsDef,
    pub gold: GoldDef,
    pub lanterns: LanternsDef,
    pub choices: ChoicesDef,
    pub combo: ComboDef,
    pub oil: OilDef,
    /// 10 分钟以后的刷怪、生命曲线
    pub late: LateDef,
    pub endless: EndlessDef,
    pub bench: BenchDef,
}

impl RunDef {
    /// 第 m 分钟的曲线值：after 分钟以前照 q，之后 = after 时的值 × (1 + slope × (m − after))。
    pub fn late_at(&self, q: Quad, slope: f32, m: f32) -> f32 {
        let after = self.late.after;
        if m <= after { q.at(m) } else { q.at(after) * (1.0 + slope * (m - after)) }
    }
}

/// 10 分钟以后（无尽夜、长更、终章）刷怪和生命改成线性增长（docs/BALANCE.md 第 4.1 节）。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct LateDef {
    /// 从第几分钟起
    pub after: f32,
    /// 刷怪、杂兵和精英生命每分钟涨 after 时的值的这么多
    pub spawn: f32,
    pub hp: f32,
}

/// 无尽夜（docs/BALANCE.md 第 4.7 节）：夜主倒下不天明。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct EndlessDef {
    /// 10 分钟以后每隔这么多分钟一次妖潮（照时间表里的妖潮），妖潮结束时夜主再来
    pub every: f32,
    /// 第 k 次再来的夜主生命 × boss_growth^k
    pub boss_growth: f32,
    /// 10 分钟以后的灯油：每秒、每次击杀、每个再来的夜主（第一个夜主照常算 oil.win）
    pub oil_per_second: f32,
    pub oil_per_kill: f32,
    pub oil_boss: u32,
    /// 10 分钟以后铜钱掉落乘它
    pub gold: f32,
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
    /// 小头目：固定出场，不带词缀；掉的宝箱至少 chest_min 连，优先升级最接近进化的法器，
    /// charm 为 true 时再给一次灯坠三选一
    MiniBoss { enemy: String, chest_min: u32, charm: bool },
    /// 合围：count 只妖物在视野外围成一圈（半径 = 视野半对角线 + extra），以 speed_mult 倍速合拢，
    /// 进入 release 以内恢复原速；出现前 warn 秒先预警。不受常规刷怪上限限制
    Encircle { count: Quad, extra: f32, speed_mult: f32, release: f32, warn: f32, enemy: String },
    /// 夜主出场，此后刷怪倍率乘以 spawn_mult；以主角为中心生成半径 barrier 的结界
    Boss { enemy: String, spawn_mult: f32, barrier: f32 },
}

/// 铜钱（docs/BALANCE.md 第 10.2 节）：掉在地上要走过去捡，拾取范围会把它吸过来，天明时全部飞来。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct GoldDef {
    /// 普通妖物掉一枚的概率
    pub normal_chance: f32,
    pub elite: u32,
    pub miniboss: u32,
    pub boss: u32,
    /// 每个宝箱附带
    pub chest: (u32, u32),
    /// 大额掉落拆成每枚这么多
    pub coin_value: u32,
    pub scatter: f32,
    /// 场上铜钱上限，超过后并入最近的一枚
    pub cap: u32,
}

/// 点灯（docs/GAMEPLAY.md 第 8.3 节）：每夜几盏熄灭的石灯笼，站在旁边一会儿就点亮。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct LanternsDef {
    pub count: u32,
    /// 离出生点的距离范围（每个扇区一盏）
    pub distance: (f32, f32),
    /// 站在这个距离以内计时；累计 light_time 秒点亮（中途离开不清零）
    pub light_radius: f32,
    pub light_time: f32,
    /// 点亮后的光区：半径、区里妖物的减速、易伤
    pub zone_radius: f32,
    pub zone_slow: f32,
    pub zone_vuln: f32,
    /// 每盏结算的灯油
    pub oil: u32,
    /// 全部点亮时夜主的生命倍率
    pub boss_hp: f32,
    /// 三选一奖励：回复生命上限的比例、铜钱
    pub heal: f32,
    pub gold: u32,
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
    /// 灯的本命五行、悟·五行的选项权重倍率
    pub lamp_mult: f32,
    pub insight_mult: f32,
    /// 保底（docs/GAMEPLAY.md 第 5.8 节）
    pub pity: PityDef,
    /// 什么都满了时的补给：回复生命上限的比例、灯油
    pub heal: f32,
    pub oil: u32,
    /// 跳过一次得到的灯油
    pub skip_oil: u32,
    /// 宝箱：随机数（加上运气）超过阈值时开出的个数，从高到低
    pub chest_odds: Vec<(f32, u32)>,
    /// 局内灯坠三选一给几个选项；精英宝箱附带一次的概率；没有可给的灯坠时改给的铜钱
    pub charm_offers: u32,
    pub elite_charm: f32,
    pub charm_gold: u32,
}

/// 保底：前 early_levels 次升级至少出现 early_new_weapons 件不同的新法器；
/// 法器到 key_level 级以上但缺进化心法时，每次升级有 key_chance 的概率把那门心法放进选项。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PityDef {
    pub early_levels: u32,
    pub early_new_weapons: u32,
    pub key_level: u32,
    pub key_chance: f32,
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
    /// 过渡系数：常规刷怪、妖群、合围的数量都乘它（P0 是 0.7，docs/BALANCE.md 第 4.1 节）
    pub scale: f32,
    /// 常规刷怪的上限：(从第几分钟起, 场上超过这么多只就停刷)
    pub soft_cap: Vec<(f32, u32)>,
    /// 硬上限：任何事件都不超过
    pub hard_cap: u32,
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
    /// 妖物的五行（抢先体验起用，决定克制倍率）
    #[serde(default)]
    pub element: Option<Element>,
    /// 夜主的招式
    #[serde(default)]
    pub boss: Option<BossDef>,
    /// 奇遇小动物被打死时的奖励
    #[serde(default)]
    pub loot: Option<CritterLoot>,
    /// 冲锋（扑击、冲撞）
    #[serde(default)]
    pub charge: Option<ChargeDef>,
}

/// 精英的冲锋（docs/BALANCE.md 第 12.6 节）：离主角 range 以内、冷却好了就原地蓄力 windup 秒
/// （转向跟着主角，出手前 lock 秒锁定方向），然后以 speed 冲 duration 秒，接触伤害乘 damage_mult；
/// 冲完原地停 recover 秒，再冷却 every 秒。冲锋速度不吃词缀“疾”“狂”的移速加成。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ChargeDef {
    pub range: f32,
    pub every: f32,
    pub windup: f32,
    /// 出手前多少秒锁定方向（不超过 windup）
    pub lock: f32,
    pub speed: f32,
    pub duration: f32,
    pub damage_mult: f32,
    pub recover: f32,
}

/// 夜主的招式（docs/BALANCE.md 第 12.2 节）：一阶段放狐火环、召唤小妖；
/// 生命降到 illusions.at 以下分出幻身，降到 sweep.at 以下开始扫击；登场 enrage_after 秒后狂暴。
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
    #[serde(default)]
    pub illusions: Option<IllusionDef>,
    #[serde(default)]
    pub sweep: Option<SweepDef>,
    /// 狂暴：登场多少秒后，所有攻击间隔乘 enrage_mult
    pub enrage_after: f32,
    pub enrage_mult: f32,
    /// 三更起多的一招（“夜主多一招”）
    #[serde(default)]
    pub rain: Option<RainDef>,
    /// 台词（docs/LORE.md 第 7 节）
    #[serde(default)]
    pub lines: Option<BossLines>,
}

/// 夜主的台词：登场、第二阶段、第三阶段、倒下；无尽夜里倒下改说“退去”，再来时说“再来”。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct BossLines {
    pub arrive: String,
    pub phase2: String,
    pub phase3: String,
    pub defeat: String,
    pub retreat: String,
    pub again: String,
}

/// 幻身：没有影子、打不死；在照见圈里待满 dispel 秒就散；每 refill 秒补满。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct IllusionDef {
    /// 生命比例低于它时进入这一阶段
    pub at: f32,
    pub count: u32,
    pub distance: f32,
    /// 绕主角转的角速度（弧度/秒）
    pub spin: f32,
    pub volley_every: f32,
    pub volley_count: u32,
    pub dispel: f32,
    pub refill: f32,
}

/// 扫击：朝主角方向的扇形，预警后造成伤害；这一阶段狐火环间隔改为 volley_every。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct SweepDef {
    pub at: f32,
    pub every: f32,
    /// 扇形角度（弧度）、半径、伤害、预警时间
    pub angle: f32,
    pub radius: f32,
    pub damage: f32,
    pub warn: f32,
    pub volley_every: f32,
}

/// 狐火雨：每隔 every 秒，在主角周围 spread 以内随机落下 count 团，预警 warn 秒。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct RainDef {
    pub every: f32,
    pub count: u32,
    pub spread: f32,
    pub radius: f32,
    pub damage: f32,
    pub warn: f32,
}

/// 精英词缀（`affixes.ron`，docs/GAMEPLAY.md 第 9.2 节）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AffixDef {
    pub id: String,
    pub name: String,
    pub desc: String,
    pub kind: AffixKind,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub enum AffixKind {
    /// 疾：移速加成
    Swift { speed: f32 },
    /// 坚：生命高于 above 时受到的伤害乘 (1 − reduction)
    Tough { above: f32, reduction: f32 },
    /// 分：死后分成 count 只小号（生命、半径按比例，不算精英，魂火各 xp）
    Split { count: u32, hp: f32, radius: f32, xp: f32 },
    /// 召：每 every 秒在身边召出一圈 count 只 enemy（计入常规刷怪上限）
    Summon { every: f32, count: u32, enemy: String, radius: f32 },
    /// 隐：在照见圈外隐身，自动瞄准的法器锁定不到它
    Cloak,
    /// 狂：生命低于 below 后移速、接触伤害乘 (1 + boost)
    Frenzy { below: f32, boost: f32 },
}

/// 难度“更”（`difficulty.ron`，docs/GAMEPLAY.md 第 12.2 节）：每一更的修正写成效果列表。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct DifficultyDef {
    pub name: String,
    pub desc: String,
    pub effects: Vec<Effect>,
}

/// 金蟾：打死后散落相当于当前等级所需 xp_levels 倍的魂火，另掉铜钱。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CritterLoot {
    pub xp_levels: f32,
    pub gems: u32,
    pub scatter: (f32, f32),
    pub gold: u32,
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

    /// 相克：木克土、土克水、水克火、火克金、金克木。
    pub fn overcomes(self, other: Element) -> bool {
        use Element::*;
        matches!(
            (self, other),
            (Wood, Earth) | (Earth, Water) | (Water, Fire) | (Fire, Metal) | (Metal, Wood)
        )
    }
}

impl ElementsDef {
    /// a、b 两系之间的反应（不分先后）。
    pub fn reaction_between(&self, a: Element, b: Element) -> Option<usize> {
        self.reactions.iter().position(|r| (r.a, r.b) == (a, b) || (r.a, r.b) == (b, a))
    }

    /// 计点：第 level 级的法器（进化后另算）。
    pub fn weapon_points(&self, level: u32, evolved: bool) -> u32 {
        if evolved {
            return self.points.evolved;
        }
        let i = (level.max(1) as usize - 1).min(self.points.weapon.len().saturating_sub(1));
        self.points.weapon.get(i).copied().unwrap_or(0)
    }

    pub fn passive_points(&self, level: u32) -> u32 {
        let i = (level.max(1) as usize - 1).min(self.points.passive.len().saturating_sub(1));
        self.points.passive.get(i).copied().unwrap_or(0)
    }
}

/// 法器的行为。新增行为 = 加一个变体，再在 `lantern_sim` 的 weapons 模块里实现。
/// 进化后的法器用同一种行为，参数可以不同。
#[derive(Clone, Debug, Deserialize, PartialEq)]
pub enum WeaponBehavior {
    /// 环绕周身（灯火）。spin 是转速（弧度/秒，x 为等级）；同一只妖物 hit_cooldown 秒内只吃一次。
    /// inner 是不夜城的内环火海。
    Orbit {
        spin: Quad,
        hit_cooldown: f32,
        knockback: f32,
        size: f32,
        #[serde(default)]
        inner: Option<InnerFireDef>,
    },
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

/// 内环火海：每隔 every 秒对周身 radius 内的妖物造成“当前等级伤害 × ratio”。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct InnerFireDef {
    pub radius: f32,
    pub every: f32,
    pub ratio: f32,
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

/// 心法（`passives.ron`）。per_level 和 levels 可以同时写。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PassiveDef {
    pub id: String,
    pub name: String,
    /// 无属性心法不计五行点数
    #[serde(default)]
    pub element: Option<Element>,
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
    /// 一阶、二阶、三阶、极境需要的点数
    pub thresholds: Vec<u32>,
    /// 按投入计点
    pub points: PointsDef,
    /// 印记与反应的通则
    pub marks: MarksDef,
    /// 易伤区上限、克制倍率
    pub zones: ZonesDef,
    /// 追加飞剑每秒最多几把（金·极境）
    pub bonus_sword_rate: f32,
    /// 按 [`Element::ALL`] 的顺序
    pub elements: Vec<ElementDef>,
    /// 相生：相邻两系都至少一阶时点亮
    pub sheng: Vec<ShengDef>,
    /// 太极：五系都至少一阶时点亮
    pub taiji: TaijiDef,
    /// 五行反应：十种两两组合
    pub reactions: Vec<ReactionDef>,
}

/// 共鸣计点（docs/GAMEPLAY.md 第 5.6 节）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PointsDef {
    /// 法器第 1 级到满级各计几点
    pub weapon: Vec<u32>,
    pub evolved: u32,
    /// 心法第 1 级到满级各计几点
    pub passive: Vec<u32>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct MarksDef {
    /// 印记持续时间
    pub duration: f32,
    /// 每只妖物两次反应的最短间隔
    pub react_cooldown: f32,
    /// 每一步最多结算几次反应，超出的丢弃
    pub max_per_step: u32,
    /// 余印：带印记的妖物死时，印记传给 spread_radius 以内还没有印记的妖物，最多 spread_count 只
    pub spread_radius: f32,
    pub spread_count: u32,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ZonesDef {
    /// 易伤区最多 +多少
    pub vuln_cap: f32,
    /// 克制、同系的伤害倍率
    pub counter: f32,
    pub same: f32,
}

/// 一种五行反应：带着 a 系印记的妖物被 b 系命中（或反过来）时发生。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ReactionDef {
    pub a: Element,
    pub b: Element,
    pub id: String,
    pub name: String,
    pub desc: String,
    pub effect: ReactionEffect,
}

/// 反应的效果。“触发伤害”指触发那一击在加成区之后、暴击和易伤之前的值。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
pub enum ReactionEffect {
    /// 燎原：目标和附近 count 只妖物灼烧 duration 秒，层数取目标的（至少 1 层），
    /// 每层每秒 = max(目标的灼烧, 触发伤害 × burn_ratio × 灼烧倍率) × mult
    Spread { count: u32, radius: f32, mult: f32, duration: f32, burn_ratio: f32 },
    /// 地面区域（赤地、淤泥）：每秒伤害 = 触发伤害 × dps_ratio；区里的妖物减速、受到的击退乘 knock_mult
    Zone { zone: ZoneKind, radius: f32, duration: f32, dps_ratio: f32, slow: f32, knock_mult: f32 },
    /// 铸兵：从妖物身上四散迸出 count 片金刃，每片伤害 = 触发伤害 × ratio
    Blades { count: u32, ratio: f32, pierce: u32, speed: f32, life: f32, hit_radius: f32 },
    /// 凝霜：冻结目标；周围减速
    Frost { freeze: f32, radius: f32, slow: f32, slow_time: f32 },
    /// 滋生：缠住附近妖物；长出一株灵草，主角碰到回复生命（每秒最多 heal_per_second）
    Bloom { radius: f32, root: f32, herb_life: f32, heal: f32, heal_per_second: f32 },
    /// 蒸腾：范围伤害 = 触发伤害 × ratio + 主角等级 × per_level；炸到的晕头乱走
    Steam { radius: f32, ratio: f32, per_level: f32, confuse: f32 },
    /// 熔金：目标易伤
    Melt { vuln: f32, duration: f32 },
    /// 断木：追加一次 ratio 倍的斩击；生命低于 execute 的普通妖物直接斩杀
    Sever { ratio: f32, execute: f32 },
    /// 裂土：范围击晕并造成触发伤害 × ratio
    Rupture { radius: f32, stun: f32, ratio: f32 },
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum ZoneKind {
    Lava,
    Mud,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ElementDef {
    pub id: Element,
    /// 金、木、水、火、土
    pub name: String,
    /// 共鸣名：锐、生、凝、焚、固
    pub resonance: String,
    /// 对应的星（太白、岁星、辰星、荧惑、镇星）：夜签“五星”抽到哪一系，界面就显示哪颗星
    pub star: String,
    pub color: String,
    pub tiers: Vec<TierDef>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct TierDef {
    pub desc: String,
    pub effects: Vec<Effect>,
    /// 到了下一阶就不再生效（下一阶写了加强版）
    #[serde(default)]
    pub superseded: bool,
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
    /// 货郎：碰到后用铜钱买宝箱、灯坠三选一（买完就走）
    Merchant { radius: f32, chest_cost: u32, charm_cost: u32 },
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

/// 心灯（`meta.ron`，docs/GAMEPLAY.md 第 11.3 节）：用灯油点亮的功能节点。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct MetaDef {
    /// 第 n 级（从 1 起）的花费 = round(base_cost × exp^(n−1) / round_to) × round_to
    pub cost_exp: f32,
    pub cost_round: f32,
    pub nodes: Vec<MetaNodeDef>,
}

impl MetaDef {
    pub fn node(&self, id: &str) -> Option<&MetaNodeDef> {
        self.nodes.iter().find(|n| n.id == id)
    }

    /// 某个节点从 level 级升到 level + 1 级的花费。
    pub fn cost(&self, node: &MetaNodeDef, level: u32) -> u32 {
        let raw = node.base_cost * self.cost_exp.powi(level as i32) / self.cost_round;
        (raw.round() * self.cost_round) as u32
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct MetaNodeDef {
    pub id: String,
    pub name: String,
    pub icon: String,
    pub desc: String,
    pub max_level: u32,
    pub base_cost: f32,
    #[serde(default)]
    pub per_level: Vec<Effect>,
    /// 逐级写的效果：第 k 项是升到 k+1 级时新加的
    #[serde(default)]
    pub levels: Vec<Vec<Effect>>,
    /// 悟·五行：出发前选一个生效，那一系的选项更容易出现
    #[serde(default)]
    pub insight: Option<Element>,
}

/// 局外属性（`attributes.ron`，docs/GAMEPLAY.md 第 11.2 节，docs/BALANCE.md 第 10.3 节）：用铜钱买。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AttributesDef {
    /// 每买过一级，所有属性的价格再涨这么多
    pub inflation: f32,
    /// 价格取整到它的倍数
    pub round: u32,
    pub list: Vec<AttributeDef>,
}

impl AttributesDef {
    /// 第 level + 1 级的价格（已经买过 bought 级）。
    pub fn price(&self, a: &AttributeDef, level: u32, bought: u32) -> u32 {
        let raw = a.base as f32 * (level + 1) as f32 * (1.0 + self.inflation * bought as f32);
        let r = self.round.max(1) as f32;
        ((raw / r).round() * r) as u32
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AttributeDef {
    pub id: String,
    pub name: String,
    pub desc: String,
    pub max_level: u32,
    pub base: u32,
    pub per_level: Vec<Effect>,
    /// 默认关闭（招妖）
    #[serde(default)]
    pub off_by_default: bool,
}

/// 灯（`lamps.ron`，docs/GAMEPLAY.md 第 11.4 节）：相当于选角色。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct LampDef {
    pub id: String,
    pub name: String,
    /// 对应的流派
    pub school: String,
    /// 本命五行：这一系的升级选项权重 ×1.2
    pub element: Element,
    pub start_weapon: String,
    /// 光色（#RRGGBB）
    pub color: String,
    pub good: String,
    pub bad: String,
    pub effects: Vec<Effect>,
    /// 一开始就能用
    #[serde(default)]
    pub initial: bool,
}

/// 灯坠（`charms.ron`，docs/GAMEPLAY.md 第 5.7 节）：挂在灯上、改写规则，每一枚都有代价。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CharmDef {
    pub id: String,
    pub name: String,
    pub good: String,
    pub bad: String,
    pub effects: Vec<Effect>,
    #[serde(default)]
    pub initial: bool,
    /// 法器多于这么多件时不出现（断剑）
    #[serde(default)]
    pub max_weapons: Option<u32>,
}

/// 成就（`achievements.ron`，docs/GAMEPLAY.md 第 13.1 节）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AchievementDef {
    pub id: String,
    pub name: String,
    pub desc: String,
    pub when: AchievementWhen,
    pub rewards: Vec<Reward>,
}

/// 成就的条件。“通关”指击败夜主、天明。
#[derive(Clone, Debug, Deserialize, PartialEq)]
pub enum AchievementWhen {
    /// 完成了几局（倒下也算）
    Runs(u32),
    /// 通关第几更
    Clear(u8),
    /// 一夜点亮全部石灯笼
    AllLanterns,
    /// 第一次倒下
    Died,
    /// 第一次触发太极
    Taiji,
    /// 通关，且这一局手上的法器从没超过几件
    ClearWithWeapons(u32),
    /// 第一次触发五行反应
    Reaction,
    /// 见过全部反应（跨局累计）
    AllReactions,
    /// 第一次有一系到第几阶
    ResonanceTier(u8),
    /// 第一次进化法器
    Evolution,
    /// 不受伤击败一只精英
    FlawlessElite,
    /// 通关，且所有属性都不生效
    ClearNoAttributes,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub enum Reward {
    /// 开放心灯、属性、夜签、出发前挂灯坠
    Basics,
    Lamp(String),
    Charm(String),
    /// 开放第几更
    Tier(u8),
    Gold(u32),
    Oil(u32),
}
