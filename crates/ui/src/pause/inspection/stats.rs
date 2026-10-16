//! 局内属性说明。数值直接读取模拟；这里只维护标签、单位与分组。

use lantern_content::{Content, Stat};
use lantern_sim::{Arsenal, Build, Flow, Stats};

use super::Row;

// 标签与短说明沿用 docs/LORE-TEXT.md 第 8 节；灯焰带倍率并入灯焰带。
const LABELS: &[(Stat, &str, &str, usize)] = &[
    (Stat::MaxHp, "生命", "生命上限，归零就倒下", 0),
    (Stat::Armor, "护甲", "每次受伤减去的固定值", 0),
    (Stat::Reduction, "减伤", "受到的伤害按比例减少", 0),
    (Stat::RegenFlat, "回复", "每秒回复的生命", 0),
    (Stat::Speed, "移速", "走动的快慢", 0),
    (Stat::Damage, "伤害", "所有法器的伤害加成", 0),
    (Stat::Cooldown, "冷却", "法器出手的间隔，越低越快", 0),
    (Stat::Area, "范围", "法器的攻击范围", 0),
    (Stat::Amount, "数量", "法器一次多出几发、几只", 0),
    (Stat::CritChance, "暴击率", "打出暴击的机会", 0),
    (Stat::CritMult, "暴击伤害", "暴击时伤害的倍数", 0),
    (Stat::Magnet, "拾取", "魂火、铜钱自己飞来的距离", 0),
    (Stat::Knockback, "击退", "把妖物打退的距离", 1),
    (Stat::BurnDamage, "灼烧", "灼烧每秒伤害的倍数", 1),
    (Stat::BurnStacks, "灼烧层数", "灼烧最多叠几层", 1),
    (Stat::FrozenVuln, "冰冻易伤", "冻住的妖物多受的伤害", 1),
    (Stat::StunCrit, "击晕必暴", "打晕的妖物必定暴击", 1),
    (Stat::ProjSpeed, "飞行速度", "飞剑、金刃飞得多快", 1),
    (Stat::ProjLife, "飞行时长", "飞剑、金刃能飞多久", 1),
    (Stat::SlowPower, "减速效果", "减速让妖物慢多少", 1),
    (Stat::SlowTime, "减速时长", "减速持续多久", 1),
    (Stat::FreezeTime, "冰冻时长", "冰冻持续多久", 1),
    (Stat::ReactionDamage, "反应伤害", "五行反应的伤害倍数", 1),
    (Stat::ShengReaction, "相生反应", "相生反应另乘的倍数", 1),
    (Stat::KeReaction, "相克反应", "相克反应另乘的倍数", 1),
    (Stat::DarkDamage, "暗处加伤", "对照见圈外妖物的加伤", 1),
    (Stat::SummonMult, "召唤数量", "纸鹤等召唤物的数量倍数", 1),
    (Stat::ArmorToDamage, "以甲增伤", "每点护甲加的伤害", 1),
    (Stat::TrailDamage, "火痕", "闪避留下的火痕伤害", 1),
    (Stat::StillDamage, "站定加伤", "站定一秒后多出的伤害", 1),
    (Stat::MovingDamage, "移动伤害", "走动时伤害的增减", 1),
    (Stat::DashStrike, "闪避伤害", "闪避穿过妖物时的伤害", 1),
    (Stat::Regen, "比例回复", "每秒回复生命上限的几成", 2),
    (Stat::ShieldCooldown, "护盾间隔", "护盾破后多久重新长出", 2),
    (Stat::ShieldMult, "护盾", "护盾的厚度倍数", 2),
    (Stat::Healing, "治疗", "所有回复的倍数，0 时不能回血", 2),
    (Stat::OverhealShield, "溢疗成盾", "满血时多回的血化成护盾", 2),
    (Stat::LotusHeal, "莲子", "吃莲子回复的多少", 2),
    (Stat::StillReduction, "站定减伤", "站定一秒后少受的伤害", 2),
    (Stat::ThornFreeze, "受击冻敌", "挨打时冻住对方的机会", 2),
    (Stat::LastStand, "回光", "濒死时留一口气（心灯）", 2),
    (Stat::DashCooldown, "闪避冷却", "两次闪避之间的间隔", 2),
    (Stat::DashCharges, "闪避段数", "连着能闪几次", 2),
    (Stat::DashDistance, "闪避距离", "一次闪多远", 2),
    (Stat::Reveal, "照见圈", "灯照见妖物的范围", 3),
    (Stat::RevealVuln, "照见易伤", "照见圈里的妖物多受的伤害", 3),
    (Stat::UltCharge, "燃灯充能", "燃灯蓄满的快慢", 3),
    (Stat::FlameBand, "灯焰带", "照见圈边上燃着的一圈火", 3),
    (Stat::Light, "灯光", "灯照亮的范围，只管看得见", 3),
    (Stat::XpGain, "魂火", "每颗魂火值多少", 4),
    (Stat::Rerolls, "重抽", "升级时还能重抽几次", 4),
    (Stat::Banishes, "封印", "能把不要的选项封掉几次", 4),
    (Stat::WeaponSlots, "法器栏", "最多带几件法器", 4),
    (Stat::CharmSlots, "灯坠栏", "最多挂几枚灯坠", 4),
    (Stat::StartPassive, "余烬", "开局先选的心法等级", 4),
    (Stat::Choices, "选项数", "升级时有几个选项", 4),
    (Stat::Inspiration, "灵光一闪", "升级时多一个选项的机会", 4),
    (Stat::ChestMin, "宝箱连开", "一个宝箱至少开几样", 4),
    (Stat::ChestLuck, "宝箱多开", "宝箱多开一样的机会", 4),
    (Stat::FrozenXp, "冻杀魂火", "冻死的妖多给的魂火", 4),
    (Stat::OilGain, "灯油", "本局结算灯油的倍数", 4),
    (Stat::GoldGain, "铜钱", "拾到铜钱的倍数", 4),
    (Stat::SpawnRate, "妖物数量", "妖物来得多快多密", 5),
    (Stat::EnemyHp, "妖物生命", "妖物的生命倍数", 5),
    (Stat::EnemySpeed, "妖物移速", "妖物的移速倍数", 5),
    (Stat::EnemyDamage, "妖物伤害", "妖物打你多疼", 5),
    (Stat::BossHp, "夜主生命", "夜主的生命倍数", 5),
    (Stat::Affixes, "精英词缀", "每只精英带几个词缀", 5),
    (Stat::EliteCount, "精英数量", "精英出现的多少", 5),
    (Stat::EventRate, "奇遇", "奇遇出现的多少", 5),
    (Stat::DarkSpeed, "暗处妖速", "照见圈外妖物加快多少", 5),
];

pub(super) fn rows(
    c: &Content,
    stats: &Stats,
    flow: &Flow,
    arsenal: &Arsenal,
    build: &Build,
) -> [Vec<Row>; 6] {
    let mut groups: [Vec<Row>; 6] = std::array::from_fn(|_| Vec::new());
    for &(stat, label, hint, group) in LABELS {
        let v = stats.get(stat);
        let def = c.stat(stat);
        let base = def.base.clamp(def.min, def.max);
        let mut row = Row {
            label: label.into(),
            value: value(stat, v),
            detail: format!(
                "{hint}。{}\n基础值 {}；当前 {}。",
                meaning(stat),
                value(stat, base),
                value(stat, v)
            ),
            changed: (v - base).abs() > 0.0001,
        };
        match stat {
            Stat::Rerolls | Stat::Banishes => {
                let remaining = if stat == Stat::Rerolls { flow.rerolls } else { flow.banishes };
                row.value = format!("剩余 {remaining}");
                row.detail = format!("{hint}。\n当前剩余 {remaining} 次；属性配额 {} 次。", number(v));
                row.changed |= (remaining as f32 - v).abs() > 0.0001;
            }
            Stat::RegenFlat => {
                // 与 player::upkeep 的回复口径一致，基础栏显示实际总回复而非仅固定部分。
                let total = (v + stats.get(Stat::Regen) * stats.max_hp()) * stats.get(Stat::Healing);
                row.value = format!("{} / 秒", number(total));
                row.detail = format!(
                    "{hint}。\n固定 {} / 秒 + 生命上限的 {}% / 秒，再乘治疗 ×{}。",
                    number(v),
                    number(stats.get(Stat::Regen) * 100.0),
                    number(stats.get(Stat::Healing))
                );
                row.changed |= (total - base).abs() > 0.0001;
            }
            Stat::WeaponSlots => {
                let occupied = lantern_sim::build::occupied_slots(c, arsenal, build);
                let slots = lantern_sim::build::weapon_slots(c, build);
                row.value = format!("{occupied} / {slots}");
                row.detail =
                    format!("{hint}。\n当前占用 {occupied} 格，容量 {slots} 格；按实际法器栏规则计数。");
            }
            Stat::CharmSlots => {
                row.value = format!("{} / {}", build.charms.len(), number(v));
                row.detail = format!("{hint}。\n已挂 {} 枚，最多 {} 枚。", build.charms.len(), number(v));
            }
            Stat::FlameBand => {
                let mult = stats.get(Stat::FlameBandMult);
                row.value = if v < 1.0 {
                    "未点亮".into()
                } else {
                    format!("{} 级 · {}", number(v), bonus(mult - 1.0))
                };
                row.detail = format!(
                    "{hint}。\n灯芯 {} 级；灯焰带伤害倍率 ×{}，需先点亮才生效。",
                    number(v),
                    number(mult)
                );
                row.changed |= (mult - c.stat(Stat::FlameBandMult).base).abs() > 0.0001;
            }
            _ => {}
        }
        groups[group].push(row);
    }
    groups
}

pub(super) fn number(v: f32) -> String {
    let s = format!("{:.2}", if v.abs() < 0.005 { 0.0 } else { v });
    s.trim_end_matches('0').trim_end_matches('.').to_string()
}

fn bonus(v: f32) -> String {
    let pct = v * 100.0;
    format!("{}{}%", if pct >= -0.005 { "+" } else { "" }, number(pct))
}

fn value(stat: Stat, v: f32) -> String {
    use Stat::*;
    match stat {
        Damage | Area | Cooldown | Knockback | BurnDamage | ProjSpeed | ProjLife | SlowTime | FreezeTime
        | ReactionDamage | ShengReaction | KeReaction | SummonMult | Healing | ShieldMult | LotusHeal
        | Light | FlameBandMult | UltCharge | DashDistance | XpGain | SpawnRate | EnemyHp | EnemySpeed
        | EnemyDamage | BossHp | EliteCount | EventRate | OilGain | GoldGain => bonus(v - 1.0),
        FrozenVuln | DarkDamage | ArmorToDamage | StillDamage | MovingDamage | DarkSpeed | FrozenXp
        | RevealVuln => bonus(v),
        CritChance | Reduction | OverhealShield | StillReduction | ThornFreeze | Inspiration | ChestLuck => {
            format!("{}%", number(v * 100.0))
        }
        Regen => format!("{}% / 秒", number(v * 100.0)),
        RegenFlat => format!("{} / 秒", number(v)),
        Speed => format!("{} / 秒", number(v)),
        Magnet | Reveal => format!("{} 单位", number(v)),
        ShieldCooldown | DashCooldown => format!("{} 秒", number(v)),
        CritMult | DashStrike | TrailDamage => format!("×{}", number(v)),
        SlowPower => format!("{}{} 百分点", if v >= 0.0 { "+" } else { "" }, number(v * 100.0)),
        StunCrit => if v > 0.0 { "生效" } else { "未获得" }.into(),
        MaxHp | Armor => number(v),
        DashCharges | Choices | ChestMin | Affixes => format!("{}", v.round() as u32),
        Amount | BurnStacks | FlameBand | LastStand | Rerolls | Banishes | WeaponSlots | CharmSlots
        | StartPassive => format!("{}", v as u32),
    }
}

fn meaning(stat: Stat) -> &'static str {
    use Stat::*;
    match stat {
        Damage => "加成区，+30% 即乘 1.3；暴击与易伤另算，条件加成见输出组。",
        Cooldown => "相对法器原始间隔；-20% 即乘 0.8，越低越快。",
        CritMult => "实际暴击乘数，×2 即两倍伤害。",
        FrozenVuln | RevealVuln => "与其他易伤相加，再受易伤上限约束。",
        DarkDamage | StillDamage | MovingDamage => "满足条件时加入伤害加成区。",
        SlowPower => "增加减速的百分点，不是相乘倍率。",
        ArmorToDamage => "每点护甲加入伤害加成区；已计入基础栏的伤害。",
        RegenFlat => "固定回复部分；比例回复与治疗倍率见生存组。",
        Regen => "生命上限的比例；与固定回复相加后再乘治疗倍率。",
        OverhealShield => "显示溢疗护盾占生命上限的容量比例。",
        Healing => "相对原始治疗量；-100% 即不能回复。",
        TrailDamage => "每秒以最高法器基础伤害乘此值，命中加成另算。",
        DashStrike => "每次以最高法器基础伤害乘此值，命中加成另算。",
        LastStand => "心灯等级；不是本局剩余次数。",
        Speed => "世界单位 / 秒，未计竹丛等地形减速。",
        Magnet | Reveal => "世界单位的半径。",
        ShieldCooldown | DashCooldown => "秒数，越低恢复越快。",
        ReactionDamage => "反应伤害倍率；相生或相克还要另乘对应倍率。",
        ShengReaction | KeReaction => "与反应伤害倍率相乘。",
        Area | Knockback | BurnDamage | ProjSpeed | ProjLife | SlowTime | FreezeTime | SummonMult
        | ShieldMult | LotusHeal | Light | FlameBandMult | UltCharge | DashDistance | XpGain | SpawnRate
        | EnemyHp | EnemySpeed | EnemyDamage | BossHp | EliteCount | EventRate | OilGain | GoldGain => {
            "相对原始数值；+30% 即乘 1.3，0% 即乘 1。"
        }
        DarkSpeed | FrozenXp => "条件满足时，在原值上加此比例。",
        _ => "显示当前汇总值。",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn labels_cover_each_stat_once_except_merged_flame_multiplier() {
        for stat in Stat::ALL {
            assert_eq!(
                LABELS.iter().filter(|x| x.0 == stat).count(),
                usize::from(stat != Stat::FlameBandMult)
            );
        }
    }

    #[test]
    fn formats_do_not_confuse_multipliers_probabilities_and_percentage_points() {
        assert_eq!(value(Stat::Damage, 1.3), "+30%");
        assert_eq!(value(Stat::Cooldown, 0.8), "-20%");
        assert_eq!(value(Stat::CritChance, 0.05), "5%");
        assert_eq!(value(Stat::CritMult, 2.0), "×2");
        assert_eq!(value(Stat::SlowPower, 0.06), "+6 百分点");
        assert_eq!(value(Stat::Healing, 0.0), "-100%");
        assert_eq!(value(Stat::Regen, 0.005), "0.5% / 秒");
    }

    #[test]
    fn inspection_uses_collected_stats_and_remaining_flow_counters() {
        let mut c =
            Content::load(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
                .unwrap();
        let setup = lantern_sim::RunSetup::new(1, lantern_sim::RunMode::Normal);
        let lamp = setup.lamp_index(&c);
        c.lamps[lamp].effects = vec![
            lantern_content::Effect::Add(Stat::Damage, 0.25),
            lantern_content::Effect::Add(Stat::FlameBand, 1.0),
            lantern_content::Effect::Mul(Stat::FlameBandMult, 0.5),
            lantern_content::Effect::Add(Stat::RegenFlat, 2.0),
            lantern_content::Effect::Mul(Stat::Healing, -1.0),
        ];
        let arsenal = Arsenal::default();
        let build = Build::default();
        let (stats, _) = lantern_sim::stats::collect(&c, &setup, &build, None, 1);
        let flow = Flow { rerolls: 1, banishes: 0, ..Default::default() };
        let groups = rows(&c, &stats, &flow, &arsenal, &build);
        assert_eq!(groups[0].iter().find(|r| r.label == "伤害").unwrap().value, "+25%");
        assert_eq!(groups[0].iter().find(|r| r.label == "回复").unwrap().value, "0 / 秒");
        assert_eq!(groups[3].iter().find(|r| r.label == "灯焰带").unwrap().value, "1 级 · +50%");
        assert_eq!(groups[4].iter().find(|r| r.label == "重抽").unwrap().value, "剩余 1");
        assert_ne!(stats.get(Stat::Rerolls), flow.rerolls as f32);
        assert_eq!(groups[4].iter().find(|r| r.label == "封印").unwrap().value, "剩余 0");
    }
}
