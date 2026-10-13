//! 会躲的风筝机器人（玩法与数值会话写的，docs/BALANCE.md 第 2.6、11 节的验收用它）。
//!
//! 走位：每步在 16 个方向里挑威胁最小的一个。威胁 = 前方几个采样点附近的妖物、弹幕（按速度外推）、
//! 夜主的扇形和落点预警、结界边缘。安全时去点石灯笼。快被碰到时闪避。选择阶段交给 `bot::respond`。
//!
//!   cargo run --release -p lantern-tools -- kite [--runs 40] [--seed 1] [--tier 1] [--meta none|half|full] [--lamp <id>]
//!       [--record <文件>]（把第一局存成回放，可以用 `lantern --replay <文件>` 在游戏里看）

use std::collections::BTreeMap;
use std::time::Instant;

use bevy_math::{Vec2, ops};
use lantern_content::{Content, Stat};
use lantern_core::step::TICK_HZ;
use lantern_sim::boss::{BossState, Foes};
use lantern_sim::combat::Source;
use lantern_sim::lanterns::Lanterns;
use lantern_sim::run::Director;
use lantern_sim::{
    Health, InputFrame, Player, Pos, RunMode, RunSetup, SimCommand, SimEvent, SimHarness, SimPhase, bot,
};

use crate::{data_dir, flag, median, source_name};

const DIRS: usize = 16;

#[derive(Default)]
struct Kite {
    last: Vec2,
}

/// 主角的位置、剩余闪避段数、生命。
fn player(sim: &SimHarness) -> Option<(Vec2, u32, f32, f32)> {
    sim.world().iter_entities().find_map(|e| {
        let (pos, pl, h) = (e.get::<Pos>()?, e.get::<Player>()?, e.get::<Health>()?);
        Some((pos.0, pl.dash_ready, h.hp, h.max))
    })
}

fn decide(sim: &SimHarness, k: &mut Kite, player_r: f32) -> (InputFrame, Vec<SimCommand>) {
    let Some((p, dash_ready, hp, hp_max)) = player(sim) else {
        return (InputFrame::default(), Vec::new());
    };
    let speed = sim.stats().get(Stat::Speed).max(30.0);
    let w = sim.world();
    let en = sim.enemies();
    let mut near: Vec<(Vec2, f32, f32)> = Vec::new();
    let mut nearest = f32::MAX;
    for i in 0..en.hi {
        if !en.alive[i] {
            continue;
        }
        let q = Vec2::new(en.x[i], en.y[i]);
        let d = q.distance(p);
        if d < 340.0 {
            nearest = nearest.min(d - en.r[i] - player_r);
            let wgt = if en.max_hp[i] > 2000.0 {
                6.0
            } else if en.max_hp[i] > 150.0 {
                3.0
            } else {
                1.0
            };
            near.push((q, en.r[i], wgt));
        }
    }
    let shots: Vec<(Vec2, Vec2, f32)> = w
        .resource::<Foes>()
        .0
        .iter()
        .filter(|f| f.pos.distance(p) < 320.0)
        .map(|f| (f.pos, f.vel, f.radius))
        .collect();
    let bullet_close = shots
        .iter()
        .any(|&(s, v, r)| [0.0f32, 0.1, 0.2].iter().any(|&t| (s + v * t).distance(p) - r - player_r < 6.0));
    let boss = w.resource::<BossState>();
    let barrier = w.resource::<Director>().barrier;
    let safe = nearest > 90.0 && shots.iter().all(|&(s, _, _)| s.distance(p) > 120.0);
    let low = hp < hp_max * 0.35;
    // 最近的一盏没点亮的灯
    let lamp = w
        .resource::<Lanterns>()
        .0
        .iter()
        .filter(|l| !l.lit)
        .map(|l| l.pos)
        .min_by(|a, b| a.distance_squared(p).total_cmp(&b.distance_squared(p)));
    let in_hazard = |q: Vec2| -> bool {
        boss.sweeps.iter().any(|sw| {
            let d = q - sw.origin;
            let mut diff = ops::atan2(d.y, d.x) - sw.dir;
            while diff > std::f32::consts::PI {
                diff -= std::f32::consts::TAU;
            }
            while diff < -std::f32::consts::PI {
                diff += std::f32::consts::TAU;
            }
            d.length() <= sw.radius + player_r + 10.0 && diff.abs() <= sw.angle * 0.5 + 0.15
        }) || boss.drops.iter().any(|r| q.distance(r.pos) <= r.radius + player_r + 10.0)
    };
    // 点灯：安全、站在灯旁就不动
    if let Some(l) = lamp
        && safe
        && !low
        && l.distance(p) < 40.0
        && !in_hazard(p)
    {
        return (InputFrame::default(), Vec::new());
    }
    let lamp_dir = lamp.filter(|l| l.distance(p) < 1500.0).map(|l| (l - p).normalize_or_zero());
    let reach = if low { 150.0 } else { 115.0 };
    let mut best = (f32::MAX, Vec2::X);
    for j in 0..DIRS {
        let a = j as f32 / DIRS as f32 * std::f32::consts::TAU;
        let d = Vec2::new(ops::cos(a), ops::sin(a));
        let mut threat = 0.0f32;
        for step in [20.0f32, 48.0, 90.0] {
            let q = p + d * step;
            let t = step / speed;
            for &(e, r, wgt) in &near {
                let dist = (q.distance(e) - r - player_r).max(0.0);
                if dist < reach {
                    let x = 1.0 - dist / reach;
                    threat += wgt * x * x * x;
                }
            }
            for &(s, v, r) in &shots {
                let dist = ((s + v * t).distance(q) - r - player_r).max(0.0);
                if dist < 40.0 {
                    threat += 4.0 * (1.0 - dist / 40.0);
                }
            }
            if in_hazard(q) {
                threat += 25.0;
            }
            if let Some((c, rad)) = barrier {
                let out = q.distance(c) - (rad - 60.0);
                if out > 0.0 {
                    threat += out * 0.15;
                }
            }
        }
        threat -= 0.25 * d.dot(k.last);
        if let Some(ld) = lamp_dir {
            threat -= if safe { 1.2 } else { 0.25 } * d.dot(ld);
        }
        if threat < best.0 {
            best = (threat, d);
        }
    }
    k.last = best.1;
    let mut cmds = Vec::new();
    if dash_ready > 0 && (nearest < 3.0 || bullet_close || in_hazard(p)) {
        cmds.push(SimCommand::Dash);
    }
    (InputFrame::quantize(best.1), cmds)
}

struct KiteRun {
    won: bool,
    secs: f32,
    kills: u32,
    levels: Vec<u32>,
    evolutions: Vec<f32>,
    boss_time: Option<f32>,
    alive7: Option<u32>,
    surge_peak: u32,
    ults: u32,
    lamps: u32,
    damage: Vec<(Source, f64)>,
}

/// 三档局外成长：none 新手；half 约第 35 局；full 全满（docs/BALANCE.md 第 2.6 节）。
fn meta_setup(setup: &mut RunSetup, meta: &str) {
    let initial = ["wind_wheel", "pillar", "longevity", "ice_soul"];
    setup.charm_pool = initial.iter().map(|s| s.to_string()).collect();
    let set = |v: &[(&str, u32)]| v.iter().map(|&(k, n)| (k.to_string(), n)).collect::<BTreeMap<_, _>>();
    match meta {
        "none" => {}
        "half" => {
            setup.attributes = set(&[
                ("damage", 5),
                ("health", 5),
                ("armor", 2),
                ("speed", 2),
                ("magnet", 3),
                ("crit", 2),
                ("cooldown", 2),
                ("xp", 3),
            ]);
            setup.meta =
                set(&[("luck", 3), ("seal", 1), ("wick", 2), ("afterglow", 1), ("ember", 1), ("oil", 1)]);
            setup.charms = vec!["longevity".into()];
            setup.charm_pool.extend(["night_pearl", "elixir", "five_coins"].iter().map(|s| s.to_string()));
        }
        _ => {
            setup.attributes = set(&[
                ("damage", 10),
                ("health", 10),
                ("armor", 5),
                ("speed", 5),
                ("magnet", 5),
                ("crit", 5),
                ("cooldown", 5),
                ("xp", 5),
            ]);
            setup.meta = set(&[
                ("luck", 5),
                ("seal", 3),
                ("wick", 3),
                ("afterglow", 2),
                ("ember", 3),
                ("slot", 1),
                ("oil", 3),
            ]);
            setup.charms = vec!["longevity".into()];
            setup.charm_pool.extend(
                ["night_pearl", "elixir", "five_coins", "broken_sword"].iter().map(|s| s.to_string()),
            );
        }
    }
}

fn kite_one(
    content: &Content,
    seed: u64,
    tier: u8,
    meta: &str,
    lamp: Option<&str>,
    record: Option<&std::path::Path>,
) -> KiteRun {
    let mut setup = RunSetup::new(seed, RunMode::Normal);
    setup.tier = tier;
    setup.lamp = lamp.map(str::to_string);
    meta_setup(&mut setup, meta);
    let player_r = content.player.radius;
    let mut sim = SimHarness::with_setup(content.clone(), setup);
    if record.is_some() {
        sim.record(env!("CARGO_PKG_VERSION"));
    }
    let mut k = Kite::default();
    let (mut levels, mut evolutions, mut alive7, mut surge_peak, mut ults) =
        (Vec::new(), Vec::new(), None, 0u32, 0u32);
    let hz = u64::from(TICK_HZ);
    while !sim.is_over() && sim.tick() < 15 * 60 * hz {
        let tick = sim.tick();
        let (input, cmds) = if sim.phase() == SimPhase::Play {
            decide(&sim, &mut k, player_r)
        } else {
            (InputFrame::default(), Vec::new())
        };
        bot::step(&mut sim, input, &cmds);
        let t = sim.tick();
        if t != tick {
            if t.is_multiple_of(30 * hz) {
                levels.push(sim.progress().level);
            }
            let alive = sim.enemies().count as u32;
            if t == 420 * hz {
                alive7 = Some(alive);
            }
            if (480 * hz..=515 * hz).contains(&t) {
                surge_peak = surge_peak.max(alive);
            }
        }
        for ev in sim.take_events() {
            match ev {
                SimEvent::Evolve { .. } => evolutions.push(sim.tick() as f32 / TICK_HZ as f32),
                SimEvent::Ult if sim.tick() < 570 * hz => ults += 1,
                _ => {}
            }
        }
    }
    if let (Some(path), Some(replay)) = (record, sim.replay()) {
        match std::fs::write(path, replay.to_ron()) {
            Ok(()) => eprintln!("回放已保存：{}", path.display()),
            Err(e) => eprintln!("保存回放失败：{e}"),
        }
    }
    let won = sim.flow().result.as_ref().is_some_and(|r| r.won);
    let secs = sim.tick() as f32 / TICK_HZ as f32;
    let since = sim.world().resource::<Director>().boss_since;
    KiteRun {
        won,
        secs,
        kills: sim.progress().kills,
        levels,
        evolutions,
        boss_time: won.then_some(secs - since),
        alive7,
        surge_peak,
        ults,
        lamps: sim.world().resource::<Lanterns>().lit(),
        damage: sim.damage_log().0.clone(),
    }
}

pub fn kite_cmd(args: &[String]) -> Result<(), String> {
    let runs = flag(args, "--runs", 40)?;
    let seed0 = flag(args, "--seed", 1)?;
    let tier = flag(args, "--tier", 1)? as u8;
    let text = |name: &str| args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned();
    let meta = text("--meta").unwrap_or_else(|| "none".into());
    if !["none", "half", "full"].contains(&meta.as_str()) {
        return Err("--meta 只能是 none、half、full".into());
    }
    let lamp = text("--lamp");
    let record = text("--record").map(std::path::PathBuf::from);
    let content = Content::load(&data_dir()).map_err(|e| e.to_string())?;
    let start = Instant::now();
    let all: Vec<KiteRun> = (0..runs)
        .map(|k| {
            let rec = record.as_deref().filter(|_| k == 0);
            kite_one(&content, seed0 + k, tier, &meta, lamp.as_deref(), rec)
        })
        .collect();
    let n = runs as f32;
    let wins = all.iter().filter(|r| r.won).count();
    let early = all.iter().filter(|r| !r.won && r.secs < 180.0).count();
    let mmss = |s: f32| format!("{}:{:02}", (s / 60.0) as u32, (s % 60.0) as u32);
    println!(
        "风筝机器人 {runs} 局，{tier} 更，局外成长 {meta}，灯 {}，用时 {:.1} 秒",
        lamp.as_deref().unwrap_or("默认"),
        start.elapsed().as_secs_f64()
    );
    println!(
        "胜率 {:.0}%；3 分钟前倒下 {:.0}%；存活中位 {}；击杀中位 {:.0}",
        100.0 * wins as f32 / n,
        100.0 * early as f32 / n,
        mmss(median(all.iter().map(|r| r.secs).collect())),
        median(all.iter().map(|r| r.kills as f32).collect())
    );
    let lv = |i: usize| {
        let v: Vec<f32> = all.iter().filter_map(|r| r.levels.get(i).map(|&l| l as f32)).collect();
        let len = v.len();
        (median(v), len)
    };
    let ((l3, n3), (l6, n6), (l9, n9)) = (lv(5), lv(11), lv(17));
    println!(
        "等级中位（活着的局）：3 分 {l3:.0}（{n3} 局），6 分 {l6:.0}（{n6} 局），9 分 {l9:.0}（{n9} 局）"
    );
    let evo: Vec<f32> = all.iter().filter_map(|r| r.evolutions.first().copied()).collect();
    let alive_at = |s: f32| all.iter().filter(|r| r.secs >= s).count();
    println!(
        "第一次进化：活过 6:15 的 {} 局里 {} 局有进化，进化中位 {}",
        alive_at(375.0),
        evo.len(),
        mmss(median(evo.clone()))
    );
    let bt: Vec<f32> = all.iter().filter_map(|r| r.boss_time).collect();
    println!("夜主击杀时间中位 {:.0} 秒（{} 局）", median(bt.clone()), bt.len());
    let a7: Vec<f32> = all.iter().filter_map(|r| r.alive7.map(|a| a as f32)).collect();
    let sp: Vec<f32> = all.iter().filter(|r| r.secs > 515.0).map(|r| r.surge_peak as f32).collect();
    println!("7 分钟场上妖物中位 {:.0}；妖潮峰值中位 {:.0}", median(a7), median(sp));
    let ult_int: Vec<f32> =
        all.iter().filter(|r| r.ults > 0).map(|r| r.secs.min(570.0) / r.ults as f32).collect();
    println!(
        "燃灯平均间隔中位 {:.0} 秒；石灯笼平均点亮 {:.1} 盏",
        median(ult_int),
        all.iter().map(|r| r.lamps as f32).sum::<f32>() / n
    );
    let mut deaths: Vec<f32> = all.iter().filter(|r| !r.won).map(|r| r.secs).collect();
    deaths.sort_by(f32::total_cmp);
    let bucket = |a: f32, b: f32| deaths.iter().filter(|&&s| s >= a && s < b).count();
    println!(
        "倒下时间分布：0–3 分 {}，3–5 分 {}，5–8 分 {}，8–9:30 分 {}，夜主战 {}",
        bucket(0.0, 180.0),
        bucket(180.0, 300.0),
        bucket(300.0, 480.0),
        bucket(480.0, 570.0),
        bucket(570.0, f32::MAX)
    );
    let mut total: Vec<(Source, f64)> = Vec::new();
    for r in &all {
        for &(s, d) in &r.damage {
            match total.iter_mut().find(|(t, _)| *t == s) {
                Some((_, v)) => *v += d,
                None => total.push((s, d)),
            }
        }
    }
    let sum: f64 = total.iter().map(|(_, d)| d).sum::<f64>().max(1.0);
    total.sort_by(|a, b| b.1.total_cmp(&a.1));
    let shares: Vec<String> = total
        .iter()
        .take(12)
        .map(|&(s, d)| format!("{} {:.1}%", source_name(&content, s), d / sum * 100.0))
        .collect();
    println!("伤害来源：{}", shares.join("，"));
    Ok(())
}
