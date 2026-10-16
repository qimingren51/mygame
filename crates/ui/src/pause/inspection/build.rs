//! 当前装备与进化缺口。判定复用模拟的法器接口，名称与钥匙读取内容数据。

use lantern_content::Content;
use lantern_sim::build::Banned;
use lantern_sim::weapons::{Form, WeaponSlot};
use lantern_sim::{Arsenal, Build};

use super::Row;

pub(super) fn rows(c: &Content, arsenal: &Arsenal, build: &Build) -> Vec<Row> {
    let mut rows = Vec::new();
    for w in &arsenal.0 {
        rows.push(weapon(c, w, build));
    }
    for p in &build.passives {
        let d = &c.passives[p.def];
        rows.push(Row {
            label: format!("心法 · {}", d.name),
            value: format!("Lv{} / {}", p.level, d.max_level),
            detail: format!("{}\n当前 {} 级，上限 {} 级。", d.desc, p.level, d.max_level),
            changed: false,
        });
    }
    for &k in &build.charms {
        let d = &c.charms[k];
        rows.push(Row {
            label: format!("灯坠 · {}", d.name),
            value: "已佩戴".into(),
            detail: if d.bad.is_empty() { d.good.clone() } else { format!("{}\n代价：{}", d.good, d.bad) },
            changed: false,
        });
    }
    rows
}

fn weapon(c: &Content, w: &WeaponSlot, build: &Build) -> Row {
    let d = &c.weapons[w.def];
    let (status, detail) = match w.form {
        Form::Evolved => ("已进化", format!("已完成正统进化：{} → {}。\n{}", d.name, w.name(c), w.desc(c))),
        Form::Mutated => ("已异化", format!("已选择异化，不能再次正统进化或合璧。\n{}", w.desc(c))),
        Form::Fused(_) => ("已合璧", format!("已完成合璧，不能再次进化。\n{}", w.desc(c))),
        Form::Base => evolution(c, w, build),
    };
    Row {
        label: format!("法器 · {}", w.name(c)),
        value: format!("Lv{} / {} · {status}", w.level, d.levels.len()),
        detail,
        changed: w.can_evolve(c, build) && !build.banished.contains(&Banned::Weapon(w.def)),
    }
}

fn evolution(c: &Content, w: &WeaponSlot, build: &Build) -> (&'static str, String) {
    let d = &c.weapons[w.def];
    let Some(evo) = &d.evolution else {
        return ("无进化", format!("本件法器没有进化分支。\n{}", w.desc(c)));
    };
    let pd = c.passive_index(&evo.passive).expect("内容已校验的进化钥匙");
    let key = &c.passives[pd];
    let lv = build.passive_level(pd);
    let requirements = format!(
        "进化为 {}：法器满级 {}/{}；钥匙 {} 至少 1 级，当前 {} 级。",
        evo.name,
        w.level,
        d.levels.len(),
        key.name,
        lv
    );
    if build.banished.contains(&Banned::Weapon(w.def)) {
        return ("已封印", format!("{requirements}\n法器已封印，本局不会出现它的升级或进化选项。"));
    }
    if w.can_evolve(c, build) {
        return ("可进化", format!("{requirements}\n条件已齐，之后的升级或宝箱可能给出进化选项。"));
    }
    let mut missing = Vec::new();
    if !w.is_max_level(c) {
        missing.push(format!("法器还差 {} 级", (d.levels.len() as u32).saturating_sub(w.level)));
    }
    if lv == 0 {
        missing.push(format!("尚未持有{}", key.name));
        if build.banished.contains(&Banned::Passive(pd)) {
            missing.push("钥匙已封印，本局不能再获得".into());
        } else if build.passives.len() as u32 >= c.run.choices.slots {
            missing.push("心法栏已满，无法再选新钥匙".into());
        }
    }
    (if lv == 0 { "缺钥匙" } else { "待满级" }, format!("{requirements}\n缺口：{}。", missing.join("；")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use lantern_sim::build::PassiveSlot;

    #[test]
    fn evolution_reports_level_key_ready_and_banished_from_real_content() {
        let c = Content::load(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
            .unwrap();
        let k = c.weapons.iter().position(|w| w.evolution.is_some()).unwrap();
        let d = &c.weapons[k];
        let pd = c.passive_index(&d.evolution.as_ref().unwrap().passive).unwrap();
        let mut w = WeaponSlot::new(k);
        let mut build = Build::default();
        assert_eq!(evolution(&c, &w, &build).0, "缺钥匙");
        assert!(evolution(&c, &w, &build).1.contains("法器还差"));
        build.passives.push(PassiveSlot { def: pd, level: 1 });
        assert_eq!(evolution(&c, &w, &build).0, "待满级");
        w.level = d.levels.len() as u32;
        assert!(w.can_evolve(&c, &build));
        assert_eq!(evolution(&c, &w, &build).0, "可进化");
        build.banished.push(Banned::Weapon(k));
        assert_eq!(evolution(&c, &w, &build).0, "已封印");
        w.form = Form::Evolved;
        assert!(weapon(&c, &w, &build).value.contains("已进化"));
        assert!(!weapon(&c, &w, &build).changed);
    }
}
