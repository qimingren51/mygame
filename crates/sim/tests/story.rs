//! 叙事的保底、主动操作、跨局接续与回放契约。
mod common;
use bevy_math::Vec2;
use common::{bot_step, content};
use lantern_content::StoryBeat;
use lantern_core::Streams;
use lantern_sim::story::{ARRIVE_TICK, GUARD_TICKS, LEAVE_TICKS, Story, StorySeed, VillageStage};
use lantern_sim::{
    Health, InputFrame, Player, Pos, Replay, RunMode, RunSetup, SimCommand, SimEvent, SimHarness, SimOutbox,
    SimRng, Tick,
};

fn setup(seed: u64) -> RunSetup {
    let mut setup = RunSetup::new(seed, RunMode::Normal);
    setup.god = true;
    setup.story = Some(StorySeed { chapter: 1, ..Default::default() });
    setup
}

fn at(sim: &mut SimHarness, pos: Vec2) {
    let world = sim.world_mut();
    let mut q = world.query_filtered::<&mut Pos, bevy_ecs::prelude::With<Player>>();
    q.single_mut(world).unwrap().0 = pos;
}
fn step(sim: &mut SimHarness, cmd: &[SimCommand]) {
    bot_step(sim, InputFrame::default(), cmd);
}
fn wait(sim: &mut SimHarness, ticks: u32) {
    let end = sim.tick() + u64::from(ticks);
    while sim.tick() < end {
        step(sim, &[]);
    }
}
fn story(sim: &SimHarness) -> &Story {
    sim.world().resource::<Story>()
}

#[test]
fn every_seed_schedules_unfinished_beats_and_requires_two_deliberate_stops() {
    for seed in [1, 2, 31, 999] {
        let mut sim = SimHarness::with_setup(content(), setup(seed));
        sim.quiet();
        sim.world_mut().resource_mut::<Tick>().0 = ARRIVE_TICK - 1;
        step(&mut sim, &[]);
        assert!(story(&sim).village.is_none());
        step(&mut sim, &[]);
        let pos = story(&sim).village.unwrap().pos;
        assert_eq!(story(&sim).village.unwrap().stage, VillageStage::Guard);
        step(&mut sim, &[SimCommand::Interact]);
        assert!(!story(&sim).village.unwrap().tending, "远处按键无效");
        at(&mut sim, pos);
        wait(&mut sim, GUARD_TICKS + LEAVE_TICKS);
        assert!(!story(&sim).has(StoryBeat::GuardedFire), "路过或自动停留不算选择");
        step(&mut sim, &[SimCommand::Interact]);
        wait(&mut sim, 60);
        at(&mut sim, pos + Vec2::splat(200.0));
        step(&mut sim, &[]);
        assert_eq!(story(&sim).village.unwrap().ticks, 0, "离开可中断");
        at(&mut sim, pos);
        step(&mut sim, &[SimCommand::Interact]);
        wait(&mut sim, GUARD_TICKS);
        assert!(story(&sim).has(StoryBeat::GuardedFire));
        wait(&mut sim, LEAVE_TICKS + 10);
        assert!(!story(&sim).has(StoryBeat::LeftLantern), "护火不能自动变成留灯");
        step(&mut sim, &[SimCommand::Interact]);
        wait(&mut sim, LEAVE_TICKS);
        assert!(story(&sim).has(StoryBeat::LeftLantern));
        assert!(story(&sim).owns(13), "留下自己的灯时必拾前辈狐村页");
        let events = sim.take_events();
        assert!(events.contains(&SimEvent::StoryBeat { beat: StoryBeat::LeftLantern }));
        assert!(events.contains(&SimEvent::JournalFound { page: 13 }));
    }
}

#[test]
fn guard_survives_a_failed_night_and_next_night_starts_at_leave() {
    let mut s = setup(3);
    s.god = false;
    s.story.as_mut().unwrap().events.insert(StoryBeat::GuardedFire.id().into());
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    sim.world_mut().resource_mut::<Tick>().0 = ARRIVE_TICK;
    step(&mut sim, &[]);
    assert_eq!(story(&sim).village.unwrap().stage, VillageStage::Leave);
    let pos = story(&sim).village.unwrap().pos;
    at(&mut sim, pos);
    step(&mut sim, &[SimCommand::Interact]);
    wait(&mut sim, LEAVE_TICKS);
    let w = sim.world_mut();
    let mut q = w.query_filtered::<&mut Health, bevy_ecs::prelude::With<Player>>();
    q.single_mut(w).unwrap().hp = 0.0;
    step(&mut sim, &[]);
    let r = sim.world().resource::<lantern_sim::Flow>().result.as_ref().unwrap();
    assert!(!r.won);
    assert!(r.events.contains(StoryBeat::LeftLantern.id()));
    assert_eq!(r.journals.iter().copied().collect::<Vec<_>>(), [13]);
}

#[test]
fn death_on_the_last_tending_tick_cancels_without_awarding_the_beat() {
    for stage in [VillageStage::Guard, VillageStage::Leave] {
        let mut s = setup(7);
        s.god = false;
        if stage == VillageStage::Leave {
            s.story.as_mut().unwrap().events.insert(StoryBeat::GuardedFire.id().into());
        }
        let mut sim = SimHarness::with_setup(content(), s);
        sim.quiet();
        sim.world_mut().resource_mut::<Tick>().0 = ARRIVE_TICK;
        step(&mut sim, &[]);
        let village = story(&sim).village.unwrap();
        at(&mut sim, village.pos);
        step(&mut sim, &[SimCommand::Interact]);
        while story(&sim).village.unwrap().ticks < village.duration() - 1 {
            step(&mut sim, &[]);
        }
        let w = sim.world_mut();
        let mut q = w.query_filtered::<&mut Health, bevy_ecs::prelude::With<Player>>();
        q.single_mut(w).unwrap().hp = 0.0;
        step(&mut sim, &[]);
        let village = story(&sim).village.unwrap();
        assert_eq!(village.stage, stage);
        assert!(!village.tending);
        assert_eq!(village.ticks, 0);
        let r = sim.flow().result.as_ref().unwrap();
        assert!(!r.won);
        assert!(r.events.contains("qingqiu_entered"));
        assert!(!r.events.contains(StoryBeat::GuardedFire.id()));
        assert!(!r.events.contains(StoryBeat::LeftLantern.id()));
        assert!(!r.journals.contains(&13));
    }
}

#[test]
fn death_before_the_village_arrives_still_records_the_journey() {
    let mut s = setup(7);
    s.god = false;
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    let w = sim.world_mut();
    let mut q = w.query_filtered::<&mut Health, bevy_ecs::prelude::With<Player>>();
    q.single_mut(w).unwrap().hp = 0.0;
    step(&mut sim, &[]);
    assert!(story(&sim).village.is_none());
    assert_eq!(sim.flow().result.as_ref().unwrap().events, ["qingqiu_entered".into()].into());
}

#[test]
fn leaving_mid_lighting_requires_a_fresh_interaction_and_full_duration() {
    let mut s = setup(11);
    s.story.as_mut().unwrap().events.insert(StoryBeat::GuardedFire.id().into());
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    sim.world_mut().resource_mut::<Tick>().0 = ARRIVE_TICK;
    step(&mut sim, &[]);
    let pos = story(&sim).village.unwrap().pos;
    at(&mut sim, pos);
    step(&mut sim, &[SimCommand::Interact]);
    wait(&mut sim, LEAVE_TICKS / 2);
    at(&mut sim, pos + Vec2::X * (lantern_sim::story::RADIUS + 1.0));
    step(&mut sim, &[SimCommand::Interact]);
    assert_eq!(story(&sim).village.unwrap().ticks, 0);
    assert!(!story(&sim).village.unwrap().tending);
    at(&mut sim, pos + Vec2::X * lantern_sim::story::RADIUS);
    wait(&mut sim, LEAVE_TICKS);
    assert!(!story(&sim).has(StoryBeat::LeftLantern));
    step(&mut sim, &[SimCommand::Interact]);
    wait(&mut sim, LEAVE_TICKS - 2);
    assert!(!story(&sim).has(StoryBeat::LeftLantern));
    step(&mut sim, &[]);
    assert!(story(&sim).has(StoryBeat::LeftLantern));
    let events = sim.take_events();
    assert_eq!(events.iter().filter(|e| **e == SimEvent::JournalFound { page: 13 }).count(), 1);
    step(&mut sim, &[SimCommand::Interact]);
    assert!(!story(&sim).village.unwrap().tending);
    assert!(sim.take_events().is_empty());
}

#[test]
fn journal_pool_is_gated_unique_and_prioritizes_the_fox_village() {
    for seed in 0..32 {
        for chapter in 1..=5 {
            let mut story = Story::new(Some(StorySeed { chapter, ..Default::default() }));
            let mut rng = SimRng(Streams::new(seed));
            let mut out = SimOutbox::default();
            story.find_journal(&mut rng, &mut out);
            assert!(!story.journals.is_empty(), "每夜第一次有效拾取保底");
            if chapter >= 3 {
                assert!(story.owns(13));
            }
            for _ in 0..100 {
                story.find_journal(&mut rng, &mut out);
            }
            assert!(story.journals.iter().all(|&p| p <= chapter * 6));
            assert_eq!(out.0.len(), story.journals.len(), "不会重复掉已持有页");
        }
    }
    let seed = StorySeed { chapter: 2, journals: (1..=6).collect(), ..Default::default() };
    let mut story = Story::new(Some(seed));
    let mut rng = SimRng(Streams::new(1));
    story.find_journal(&mut rng, &mut SimOutbox::default());
    assert!(story.journals.iter().all(|p| (7..=12).contains(p)));
}

#[test]
fn old_setup_and_bench_never_schedule_story() {
    let old: RunSetup = ron::from_str("(seed: 1, mode: Normal, god: true)").unwrap();
    assert!(old.story.is_none(), "旧回放没有叙事字段也照常加载");
    for s in [old, RunSetup { mode: RunMode::Bench { enemies: 0 }, ..setup(1) }] {
        let mut sim = SimHarness::with_setup(content(), s);
        sim.world_mut().resource_mut::<Tick>().0 = ARRIVE_TICK;
        step(&mut sim, &[]);
        assert!(story(&sim).village.is_none());
        assert!(story(&sim).events.is_empty());
    }
}

#[test]
fn story_choices_and_new_journals_replay_with_identical_hashes() {
    let mut s = setup(19);
    s.story = Some(StorySeed {
        events: ["qingqiu_entered".into(), "qingqiu_asked_dark".into()].into(),
        journals: [1, 4].into(),
        chapter: 2,
    });
    let snapshot = s.story.clone();
    let mut sim = SimHarness::with_setup(content(), s);
    sim.record("story-test");
    // 实际走到故事点，不能靠直接改位置，否则无法证明输入回放。
    let mut steps = 0;
    while sim.tick() < ARRIVE_TICK + 18 * 60 {
        let village = story(&sim).village;
        let pos = {
            let w = sim.world_mut();
            let mut q = w.query_filtered::<&Pos, bevy_ecs::prelude::With<Player>>();
            q.single(w).unwrap().0
        };
        let dir = village
            .map_or(Vec2::ZERO, |v| if v.near(pos) { Vec2::ZERO } else { (v.pos - pos).normalize_or_zero() });
        let commands = if village.is_some_and(|v| v.near(pos) && !v.tending && v.stage != VillageStage::Lit) {
            vec![SimCommand::Interact]
        } else {
            vec![]
        };
        bot_step(&mut sim, InputFrame::quantize(dir), &commands);
        steps += 1;
        assert!(steps < 10000);
    }
    assert!(story(&sim).has(StoryBeat::LeftLantern));
    let expected_events = story(&sim).events.clone();
    let expected_pages = story(&sim).journals.clone();
    let hashes = sim.hashes().to_vec();
    let replay = Replay::parse(&sim.replay().unwrap().to_ron()).unwrap();
    assert_eq!(replay.setup.story, snapshot, "已见事件、已拾页和章节都随回放冻结");
    assert!(replay.commands.iter().any(|(_, c)| *c == SimCommand::Interact));
    let mut played = SimHarness::from_replay(content(), replay);
    while !played.playback().unwrap().finished {
        played.step(InputFrame::default(), &[]);
    }
    assert_eq!(played.playback().unwrap().diverged_at, None);
    assert_eq!(played.hashes(), hashes);
    assert_eq!(story(&played).events, expected_events);
    assert_eq!(story(&played).journals, expected_pages);
}
