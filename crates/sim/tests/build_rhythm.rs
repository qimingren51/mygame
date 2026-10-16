//! 初期构筑：类别预算、已有法器选择、进化钥匙、最终展示计数与旧配置兼容。
mod common;

use lantern_content::{Content, Stat};
use lantern_core::Pcg32;
use lantern_sim::build::{Banned, offers, pick_choice_offers, roll_choices};
use lantern_sim::{InputFrame, Offer, RunMode, RunSetup, SimCommand, SimHarness};

fn arena(content: Content, seed: u64) -> SimHarness {
    let mut sim = SimHarness::with_setup(content, RunSetup::new(seed, RunMode::Normal));
    sim.quiet();
    sim
}

fn category(offer: Offer) -> u8 {
    match offer {
        Offer::NewWeapon(_) => 1,
        Offer::NewPassive(_) => 2,
        _ => 0,
    }
}

#[test]
fn added_content_does_not_dilute_owned_upgrades_or_category_budgets() {
    let c = common::content();
    let sim = arena(c.clone(), 42);
    let original = offers(&c, sim.arsenal(), sim.build(), 0.0);
    let mut expanded = c.clone();
    for i in 0..12 {
        let mut weapon = c.weapons[1].clone();
        weapon.id = format!("test_weapon_{i}");
        expanded.weapons.push(weapon);
        let mut passive = c.passives[0].clone();
        passive.id = format!("test_passive_{i}");
        expanded.passives.push(passive);
    }
    let more = offers(&expanded, sim.arsenal(), sim.build(), 0.0);
    let sum = |pool: &[(Offer, f32)], kind| {
        pool.iter().filter(|(o, _)| category(*o) == kind).map(|(_, w)| w).sum::<f32>()
    };
    for kind in 0..=2 {
        assert!((sum(&original, kind) - sum(&more, kind)).abs() < 0.001);
    }
    assert!((sum(&original, 0) - 12.0).abs() < 0.001, "法器升级base10，红灯火系×1.2");
    assert!((sum(&original, 1) - 18.0).abs() < 0.001);
    assert!((sum(&original, 2) - 12.0).abs() < 0.001);
    let late = offers(&expanded, sim.arsenal(), sim.build(), 180.0);
    assert!((sum(&late, 1) - 9.0).abs() < 0.001);
    let weight = |id| {
        let offer = Offer::NewPassive(c.passive_index(id).unwrap());
        original.iter().find(|(o, _)| *o == offer).unwrap().1
    };
    assert!((weight("changming") / weight("luxin") - 2.0).abs() < 0.001, "同属火系，已有法器钥匙偏向×2");

    // 两类始终都有余牌。增加条目不能改变同一随机流的类别节奏，包括同一屏的第二、三抽。
    let pool = |count| {
        let mut pool = vec![(Offer::WeaponUp(0), 12.0)];
        pool.extend((0..count).map(|i| (Offer::NewWeapon(i), 9.0)));
        pool.extend((0..count).map(|i| (Offer::NewPassive(i), 5.0)));
        pool
    };
    for seed in [1, 7, 42, 87] {
        let small = pick_choice_offers(&c, &mut Pcg32::new(seed, 3), &pool(3), 0.0, 3);
        let large = pick_choice_offers(&c, &mut Pcg32::new(seed, 3), &pool(30), 0.0, 3);
        assert_eq!(
            small.iter().copied().map(category).collect::<Vec<_>>(),
            large.iter().copied().map(category).collect::<Vec<_>>()
        );
        for choices in [small, large] {
            for (k, offer) in choices.iter().enumerate() {
                assert!(!choices[k + 1..].contains(offer), "同一屏不重复：{choices:?}");
            }
        }
    }
}

#[test]
fn first_five_choices_offer_a_real_owned_upgrade_and_count_only_shown_weapons() {
    for seed in [1, 7, 42] {
        let mut sim = arena(common::content(), seed);
        let mut seen = std::collections::BTreeSet::new();
        for level in 2..=6 {
            sim.progress_mut().level = level;
            sim.progress_mut().pending_levels = 1;
            sim.step(InputFrame::default(), &[]);
            let choices = &sim.flow().choice.as_ref().unwrap().offers;
            let up = choices
                .iter()
                .position(|o| matches!(o, Offer::WeaponUp(0)))
                .expect("仍可升级的起手法器应留一席");
            seen.extend(
                choices.iter().filter_map(|o| if let Offer::NewWeapon(d) = o { Some(*d) } else { None }),
            );
            assert_eq!(
                sim.build().early_new.iter().copied().collect::<std::collections::BTreeSet<_>>(),
                seen
            );
            assert_eq!(sim.build().levelups, level - 1);
            sim.step(InputFrame::default(), &[SimCommand::Choose(up as u8)]);
        }
        assert_eq!(sim.arsenal().0[0].level, 6);
        assert!(seen.len() >= 2, "保留已有升级不能挤掉累计新法器保底");
    }
}

#[test]
fn reroll_and_banish_keep_the_real_flow_and_seen_cards_consistent() {
    let mut sim = arena(common::content(), 42);
    sim.progress_mut().level = 2;
    sim.progress_mut().pending_levels = 1;
    sim.step(InputFrame::default(), &[]);
    sim.flow_mut().rerolls = 1;
    sim.step(InputFrame::default(), &[SimCommand::Reroll]);
    assert_eq!(sim.build().levelups, 1, "重抽不消耗新的升级次数");
    let up =
        sim.flow().choice.as_ref().unwrap().offers.iter().position(|o| *o == Offer::WeaponUp(0)).unwrap();
    sim.flow_mut().banishes = 1;
    sim.step(InputFrame::default(), &[SimCommand::Banish(up as u8)]);
    let choices = &sim.flow().choice.as_ref().unwrap().offers;
    assert!(!choices.contains(&Offer::WeaponUp(0)), "首五次保护不能复活已封印的法器");
    for offer in choices {
        if let Offer::NewWeapon(d) = offer {
            assert!(sim.build().early_new.contains(d), "封印后补入并显示的新法器也算见过");
        }
        if let Some(banned) = offer.banned(sim.arsenal(), sim.build()) {
            assert!(!sim.build().banished.contains(&banned));
        }
    }
}

#[test]
fn last_passive_slot_offers_the_closest_missing_key_without_taking_it() {
    let mut c = common::content();
    c.run.choices.pity.key_chance = 0.0;
    let mut sim = arena(c.clone(), 42);
    sim.set_build(
        &[("lamp", 6, false), ("sword", 4, false)],
        &[("zhezhi", 1), ("houde", 1), ("jingxin", 1), ("jixing", 1), ("yinhun", 1)],
    );
    let key = c.passive_index("changming").unwrap();
    let other_key = c.passive_index("jianyi").unwrap();
    let mut b = sim.build().clone();
    b.levelups = 6;
    for seed in [1, 42, 77] {
        let (choices, _) =
            roll_choices(&c, sim.arsenal(), &mut b, sim.stats(), 90.0, &mut Pcg32::new(seed, 3), true);
        assert!(choices.contains(&Offer::NewPassive(key)));
        assert_eq!(b.passives.len(), 5);
        assert_eq!(b.passive_level(key), 0, "只提供选择，不代玩家领取");
    }
    let mut banned_weapon = b.clone();
    banned_weapon.banished.push(Banned::Weapon(c.weapon_index("lamp").unwrap()));
    let (choices, _) =
        roll_choices(&c, sim.arsenal(), &mut banned_weapon, sim.stats(), 90.0, &mut Pcg32::new(42, 3), true);
    assert!(choices.contains(&Offer::NewPassive(other_key)), "不为已封印法器占用最后一格钥匙机会");
    b.banished.push(Banned::Passive(key));
    let (choices, _) =
        roll_choices(&c, sim.arsenal(), &mut b, sim.stats(), 90.0, &mut Pcg32::new(42, 3), true);
    assert!(!choices.contains(&Offer::NewPassive(key)), "封印的钥匙不能回来");
    assert!(choices.contains(&Offer::NewPassive(other_key)), "另一件持有法器仍有合法钥匙");
    b.passives.push(lantern_sim::build::PassiveSlot { def: c.passive_index("luxin").unwrap(), level: 1 });
    let (choices, _) =
        roll_choices(&c, sim.arsenal(), &mut b, sim.stats(), 360.0, &mut Pcg32::new(42, 3), true);
    assert!(choices.iter().all(|o| !matches!(o, Offer::NewPassive(_))), "满栏后不绕过槽位上限");
}

#[test]
fn level_four_weapon_can_offer_its_key_before_five_minutes() {
    let mut c = common::content();
    c.run.choices.pity.key_chance = 1.0;
    let mut sim = arena(c.clone(), 7);
    sim.set_build(&[("lamp", 4, false)], &[]);
    let mut b = sim.build().clone();
    b.levelups = 6;
    let (choices, _) =
        roll_choices(&c, sim.arsenal(), &mut b, sim.stats(), 90.0, &mut Pcg32::new(7, 3), true);
    assert!(choices.contains(&Offer::NewPassive(c.passive_index("changming").unwrap())));
    assert_eq!(b.passives.len(), 0);
}

#[test]
fn final_forms_do_not_create_phantom_seen_weapons_and_pity_can_expand_choices() {
    let mut c = common::content();
    c.run.choices.weight_evolve = 0.001;
    c.run.choices.build_rhythm.as_mut().unwrap().new_passive = 0.001;
    let mut sim = arena(c.clone(), 42);
    sim.set_build(&[("lamp", 8, false), ("bell", 8, false)], &[("changming", 1)]);
    let key = Offer::NewPassive(c.passive_index("jingxin").unwrap());
    for prior_levelups in [0, 4] {
        let mut b = sim.build().clone();
        b.levelups = prior_levelups;
        let (choices, _) =
            roll_choices(&c, sim.arsenal(), &mut b, sim.stats(), 300.0, &mut Pcg32::new(42, 3), true);
        assert!(choices.contains(&Offer::Evolve(0)) && choices.contains(&Offer::Mutate(0)));
        assert!(choices.contains(&key));
        let seen = choices
            .iter()
            .filter_map(|o| if let Offer::NewWeapon(d) = o { Some(*d) } else { None })
            .collect::<std::collections::BTreeSet<_>>();
        assert_eq!(b.early_new.iter().copied().collect::<std::collections::BTreeSet<_>>(), seen);
        if prior_levelups == 4 {
            assert!(!seen.is_empty(), "最后一次累计保底仍应展示新法器");
            assert!(
                choices.len() > sim.stats().get(Stat::Choices) as usize,
                "分岔、钥匙、新法器都保留，显式扩展选项"
            );
        }
    }
}

#[test]
fn naturally_drawn_keys_survive_later_pity() {
    let c = common::content();
    let mut sim = arena(c.clone(), 160);
    sim.set_build(&[("lamp", 4, false), ("sword", 4, false)], &[]);
    let mut b = sim.build().clone();
    b.levelups = 7;
    let (choices, _) =
        roll_choices(&c, sim.arsenal(), &mut b, sim.stats(), 90.0, &mut Pcg32::new(160, 3), true);
    assert!(choices.contains(&Offer::NewPassive(c.passive_index("changming").unwrap())));
    assert!(
        choices.contains(&Offer::NewPassive(c.passive_index("jianyi").unwrap())),
        "符剑钥匙已自然抽中，灯火的钥匙补牌不能把它挤掉：{choices:?}"
    );

    sim.set_build(&[("lamp", 4, false)], &[]);
    let mut b = sim.build().clone();
    b.levelups = 3;
    let (choices, _) =
        roll_choices(&c, sim.arsenal(), &mut b, sim.stats(), 90.0, &mut Pcg32::new(66, 3), true);
    assert!(choices.contains(&Offer::WeaponUp(0)));
    assert!(
        choices.contains(&Offer::NewPassive(c.passive_index("changming").unwrap())),
        "自然抽中的长明也应在早期法器升级补牌之前受保护：{choices:?}"
    );
}

#[test]
fn absent_rhythm_preserves_the_legacy_seed_42_opening() {
    let mut c = common::content();
    // 固定当时的六件法器池，新增内容不属于旧抽样算法的兼容范围。
    c.weapons.retain(|w| ["lamp", "sword", "bell", "crane", "seal", "coin_sword"].contains(&w.id.as_str()));
    c.run.choices.build_rhythm = None;
    let expected = vec![
        Offer::NewPassive(c.passive_index("zhezhi").unwrap()),
        Offer::NewWeapon(c.weapon_index("seal").unwrap()),
        Offer::NewPassive(c.passive_index("jianyi").unwrap()),
    ];
    let mut sim = arena(c, 42);
    sim.progress_mut().level = 2;
    sim.progress_mut().pending_levels = 1;
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.flow().choice.as_ref().unwrap().offers, expected);
}
