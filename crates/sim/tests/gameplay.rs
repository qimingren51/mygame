//! 玩法场景测试：搭一局最小的模拟，跑若干步，断言结果（docs/DESIGN.md 第 13 节）。

use std::path::Path;

use bevy_math::{Vec2, ops};
use lantern_content::Content;
use lantern_sim::{InputFrame, RunMode, SimEvent, SimHarness};

fn content() -> Content {
    Content::load(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data")).expect("内容数据")
}

/// 绕大圈走（像玩家放风筝），返回这一步的输入。
fn kite(tick: u64) -> InputFrame {
    let t = tick as f32 / 60.0;
    InputFrame::quantize(Vec2::new(ops::cos(t * 0.5), ops::sin(t * 0.5)))
}

#[test]
fn a_normal_run_spawns_kills_and_levels_up() {
    let mut sim = SimHarness::new(content(), 7);
    let mut kills = 0;
    let mut hits = 0;
    for tick in 0..90 * 60 {
        if sim.is_over() {
            break;
        }
        sim.step(kite(tick), &[]);
        for ev in sim.take_events() {
            match ev {
                SimEvent::Kill { .. } => kills += 1,
                SimEvent::Hit { .. } => hits += 1,
                _ => {}
            }
        }
    }
    assert!(sim.enemies().count > 10, "90 秒后场上应该有妖物，现在 {}", sim.enemies().count);
    // 影妖血量 10、灯火伤害 15，前期基本一击必杀，所以命中数可以等于击杀数
    assert!(hits >= kills && kills > 20, "灯火应该命中并击杀妖物：命中 {hits}，击杀 {kills}");
    assert_eq!(sim.progress().kills, kills);
    assert!(sim.progress().level >= 3, "应该捡到魂火升级，现在 {} 级", sim.progress().level);
}

#[test]
fn standing_still_eventually_gets_the_player_killed() {
    let mut sim = SimHarness::new(content(), 3);
    for _ in 0..10 * 60 * 60 {
        if sim.is_over() {
            break;
        }
        sim.step(InputFrame::default(), &[]);
    }
    assert!(sim.is_over(), "站着不动 10 分钟应该会倒下");
    assert_eq!(sim.player_hp(), 0.0);
}

#[test]
fn bench_mode_keeps_enemy_count_and_player_alive() {
    let mut sim = SimHarness::with_mode(content(), 1, RunMode::Bench { enemies: 1000 });
    for tick in 0..20 * 60 {
        sim.step(kite(tick), &[]);
    }
    let count = sim.enemies().count;
    assert!((950..=1000).contains(&count), "跑分模式应保持约 1000 只，现在 {count}");
    assert!(!sim.is_over());
    assert_eq!(sim.player_hp(), content().player.max_hp);
    assert_eq!(sim.progress().level, 1, "跑分模式不升级");
}
