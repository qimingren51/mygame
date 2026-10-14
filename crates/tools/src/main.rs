//! 命令行工具（不开窗口）：跑分、内容检查。见 docs/DESIGN.md 第 13 节。
//!
//!   cargo run --release -p lantern-tools -- bench [--enemies 5000] [--seconds 20] [--seed 1]
//!   cargo run -p lantern-tools -- check-content
//!   cargo run --release -p lantern-tools -- replay <回放文件>
//!   cargo run --release -p lantern-tools -- balance [--runs 20] [--seed 1] [--god]
//!   cargo run --release -p lantern-tools -- kite [--runs 40] [--tier 1] [--meta none|half|full] [--lamp <id>]
//!       [--skill novice|regular|expert|circle] [--school <流派>|all] [--combo <反应>|all] [--csv <目录>]

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Instant;

use bevy_math::{Vec2, ops};
use lantern_content::Content;
use lantern_core::step::TICK_HZ;
use lantern_sim::combat::Source;
use lantern_sim::{InputFrame, Replay, RunMode, RunSetup, SimCommand, SimEvent, SimHarness, bot};

const USAGE: &str = "用法：
  lantern-tools bench [--enemies <数量>] [--seconds <秒>] [--seed <种子>]
      跑分：场上保持指定数量的妖物（默认 5000），主角绕圈，统计每步耗时
  lantern-tools check-content
      校验 assets/data
  lantern-tools replay <回放文件>
      不开窗口重放，逐秒核对状态哈希，报告第一次出现分歧的步数
  lantern-tools balance [--runs <局数>] [--seed <起始种子>] [--god]
      机器人自动选卡、绕圈走位打整局，统计等级曲线、击杀、进化时间、伤害来源占比、存活时间
      （--god：主角无敌，看成长曲线和夜主战）
  lantern-tools kite [--runs <局数>] [--seed <起始种子>] [--tier <更>] [--meta none|half|full]
      [--skill novice|regular|expert|circle] [--lamp <灯>] [--school <流派>|all] [--combo <反应>|all]
      [--csv <目录>] [--jobs <线程数>] [--endless] [--god] [--record <文件>]
      会躲的风筝机器人打整局，按更和局外成长（无 / 一半 / 全满）统计胜率、等级、进化、共鸣、夜主战、
      清场时间、场上妖物数、燃灯间隔、死因、伤害来源（docs/BALANCE.md 第 2.6、11 节的验收用它）
      --skill circle：不躲，绕圈走；--school：流派机器人（剑修、百鸟、寒川、星火、不动、身法、照夜、太极）；
      --combo：组合机器人，凑某个反应（反应的 ID 或名字）；all 表示全部跑一遍，最后打一张对照表
      --csv：写出 timeline.csv（每 30 秒一行）和 runs.csv（每局一行）；--endless：打无尽夜（最多 40 分钟）
      --record：第一局存成回放并打印关键时刻（进化、反应初见、夜主……），用 lantern --replay <文件> --from <秒>
      在游戏里看任意时刻的画面；--god：主角无敌，看完整一局
环境变量 LANTERN_DATA 可以换一份数据目录（比较两套数值时用）";

mod kite;
mod school;

fn data_dir() -> PathBuf {
    std::env::var_os("LANTERN_DATA")
        .map_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"), PathBuf::from)
}

fn flag(args: &[OsString], name: &str, default: u64) -> Result<u64, String> {
    match args.iter().position(|a| a == name) {
        Some(i) => args
            .get(i + 1)
            .and_then(|v| v.to_str())
            .and_then(|v| v.parse().ok())
            .ok_or_else(|| format!("{name} 后面要跟一个数字")),
        None => Ok(default),
    }
}

fn bench(args: &[OsString]) -> Result<(), String> {
    let enemies = flag(args, "--enemies", 5000)? as u32;
    let seconds = flag(args, "--seconds", 20)?;
    let seed = flag(args, "--seed", 1)?;
    let content = Content::load(&data_dir()).map_err(|e| e.to_string())?;
    let mut sim = SimHarness::with_mode(content, seed, RunMode::Bench { enemies });
    let input = |tick: u64| {
        let t = tick as f32 / TICK_HZ as f32;
        InputFrame::quantize(Vec2::new(ops::cos(t * 0.5), ops::sin(t * 0.5)))
    };
    // 热身 5 秒：妖物补满、围上来
    let warmup = 5 * u64::from(TICK_HZ);
    for tick in 0..warmup {
        sim.step(input(tick), &[]);
    }
    let ticks = seconds * u64::from(TICK_HZ);
    let mut times = Vec::with_capacity(ticks as usize);
    for tick in warmup..warmup + ticks {
        let cmds: &[SimCommand] = if tick % 120 == 0 { &[SimCommand::Dash] } else { &[] };
        let start = Instant::now();
        sim.step(input(tick), cmds);
        times.push(start.elapsed().as_secs_f64() * 1e3);
        sim.take_events();
    }
    let mean = times.iter().sum::<f64>() / times.len() as f64;
    times.sort_by(f64::total_cmp);
    let p95 = times[times.len() * 95 / 100];
    let max = times[times.len() - 1];
    let last = sim.hashes().last().map(|c| c.hash).unwrap_or(0);
    println!(
        "妖物 {} 只（目标 {enemies}），{seconds} 秒 {ticks} 步：每步平均 {mean:.3} ms，95% {p95:.3} ms，最大 {max:.3} ms，最终哈希 {last:016x}",
        sim.enemies().count
    );
    Ok(())
}

fn replay(args: &[OsString]) -> Result<(), String> {
    let path = Path::new(args.first().ok_or("replay 后面要跟回放文件的路径")?);
    let text = std::fs::read_to_string(path).map_err(|e| format!("读取 {path:?} 失败：{e}"))?;
    let replay = Replay::parse(&text)?;
    let content = Content::load(&data_dir()).map_err(|e| e.to_string())?;
    if replay.content_hash != content.hash {
        println!("注意：回放录制时的内容数据与当前不同（游戏版本 {}），结果可能不一致", replay.game_version);
    }
    let (ticks, checkpoints, seed) = (replay.ticks, replay.hashes.len(), replay.setup.seed);
    let start = Instant::now();
    let mut sim = SimHarness::from_replay(content, replay);
    while !sim.playback().is_some_and(|p| p.finished) && !sim.is_over() {
        sim.step(InputFrame::default(), &[]);
        sim.take_events();
    }
    let secs = ticks / u64::from(TICK_HZ);
    println!(
        "种子 {seed}，{ticks} 步（{:02}:{:02}），重放用时 {:.2} 秒",
        secs / 60,
        secs % 60,
        start.elapsed().as_secs_f64()
    );
    match sim.playback().and_then(|p| p.diverged_at) {
        None => {
            println!("全部 {checkpoints} 个检查点与录制时一致");
            Ok(())
        }
        Some(t) => Err(format!("从第 {t} 步（{:.1} 秒）起与录制时不一致", t as f64 / f64::from(TICK_HZ))),
    }
}

struct RunStats {
    won: bool,
    secs: f32,
    kills: u32,
    /// 每 30 秒的等级
    levels: Vec<u32>,
    /// 每次进化的时刻（秒）
    evolutions: Vec<f32>,
    damage: Vec<(Source, f64)>,
    build: String,
}

fn play_one(content: &Content, seed: u64, god: bool) -> RunStats {
    let mut setup = RunSetup::new(seed, RunMode::Normal);
    setup.god = god;
    let mut sim = SimHarness::with_setup(content.clone(), setup);
    let mut levels = Vec::new();
    let mut evolutions = Vec::new();
    // 最多 15 分钟游戏时间（夜主没打死时也停）
    while !sim.is_over() && sim.tick() < 15 * 60 * u64::from(TICK_HZ) {
        let tick = sim.tick();
        let (input, cmds) = bot::input(tick);
        bot::step(&mut sim, input, &cmds);
        if sim.tick() != tick && sim.tick().is_multiple_of(30 * u64::from(TICK_HZ)) {
            levels.push(sim.progress().level);
        }
        for ev in sim.take_events() {
            if let SimEvent::Evolve { .. } = ev {
                evolutions.push(sim.tick() as f32 / TICK_HZ as f32);
            }
        }
    }
    let c = content;
    let mut build: Vec<String> = sim
        .arsenal()
        .0
        .iter()
        .map(|w| {
            let def = &c.weapons[w.def];
            match (&def.evolution, w.evolved) {
                (Some(e), true) => e.name.clone(),
                _ => format!("{}{}", def.name, w.level),
            }
        })
        .collect();
    build.extend(sim.build().passives.iter().map(|p| format!("{}{}", c.passives[p.def].name, p.level)));
    let result = sim.flow().result.clone();
    RunStats {
        won: result.as_ref().is_some_and(|r| r.won),
        secs: sim.tick() as f32 / TICK_HZ as f32,
        kills: sim.progress().kills,
        levels,
        evolutions,
        damage: sim.damage_log().0.clone(),
        build: build.join(" "),
    }
}

fn median(mut v: Vec<f32>) -> f32 {
    if v.is_empty() {
        return 0.0;
    }
    v.sort_by(f32::total_cmp);
    v[v.len() / 2]
}

fn source_name(c: &Content, s: Source) -> String {
    match s {
        Source::Weapon(i) => c.weapons[i as usize].name.clone(),
        Source::BonusSword => "追加飞剑".into(),
        Source::Burn => "灼烧".into(),
        Source::Blast => "连锁爆炸".into(),
        Source::Quake => "震地".into(),
        Source::Screen => "太极".into(),
        Source::Ult => "燃灯".into(),
        Source::Reaction(r) => format!("反应·{}", c.elements.reactions[r as usize].name),
        Source::Band => "灯焰带".into(),
        Source::Dash => "轻功".into(),
        Source::Trail => "火痕".into(),
    }
}

/// 机器人打若干局，汇总成长曲线和伤害来源（docs/BALANCE.md 第 11 节）。
fn balance(args: &[OsString]) -> Result<(), String> {
    let runs = flag(args, "--runs", 20)?;
    let seed0 = flag(args, "--seed", 1)?;
    let god = args.iter().any(|a| a == "--god");
    let content = Content::load(&data_dir()).map_err(|e| e.to_string())?;
    let start = Instant::now();
    let all: Vec<RunStats> = (0..runs).map(|k| play_one(&content, seed0 + k, god)).collect();
    println!(
        "{runs} 局（种子 {seed0}–{}，{}），用时 {:.1} 秒",
        seed0 + runs - 1,
        if god { "无敌" } else { "会受伤" },
        start.elapsed().as_secs_f64()
    );
    let wins = all.iter().filter(|r| r.won).count();
    println!(
        "天明 {wins} / {runs}；存活时间中位 {:.0} 秒；击杀中位 {:.0}",
        median(all.iter().map(|r| r.secs).collect()),
        median(all.iter().map(|r| r.kills as f32).collect())
    );
    // 等级曲线：每 30 秒的中位等级（只统计还活着的局）
    let longest = all.iter().map(|r| r.levels.len()).max().unwrap_or(0);
    let curve: Vec<String> = (0..longest)
        .map(|i| {
            let v: Vec<f32> = all.iter().filter_map(|r| r.levels.get(i).map(|&l| l as f32)).collect();
            format!("{:.0}", median(v))
        })
        .collect();
    println!("每 30 秒等级中位：{}", curve.join(","));
    let first_evo: Vec<f32> = all.iter().filter_map(|r| r.evolutions.first().copied()).collect();
    println!(
        "第一次进化：{} 局出现，中位 {:.0} 秒；平均每局进化 {:.1} 件",
        first_evo.len(),
        median(first_evo.clone()),
        all.iter().map(|r| r.evolutions.len()).sum::<usize>() as f32 / runs as f32
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
    let shares: Vec<String> =
        total.iter().map(|&(s, d)| format!("{} {:.1}%", source_name(&content, s), d / sum * 100.0)).collect();
    println!("伤害来源：{}", shares.join("，"));
    println!("各局构筑：");
    for (k, r) in all.iter().enumerate() {
        println!(
            "  种子 {:>4}　{}　{:>4.0} 秒　击杀 {:>5}　{}",
            seed0 + k as u64,
            if r.won { "天明" } else { "夜未尽" },
            r.secs,
            r.kills,
            r.build
        );
    }
    Ok(())
}

/// 机器人打一局并存成回放，用来在游戏里看后期的画面（`lantern --replay <文件> --from <秒>`）。
fn main() -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    let result = match args.first().and_then(|arg| arg.to_str()) {
        Some("bench") => bench(&args[1..]),
        Some("replay") => replay(&args[1..]),
        Some("balance") => balance(&args[1..]),
        Some("kite") => kite::kite_cmd(&args[1..]),
        Some("check-content") => {
            Content::load(&data_dir()).map(|_| println!("内容数据校验通过")).map_err(|e| e.to_string())
        }
        _ => Err(USAGE.into()),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("{msg}");
            ExitCode::FAILURE
        }
    }
}
