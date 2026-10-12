//! 妖物之间互相推开。
//!
//! 网页版按槽位顺序原地修改，每只妖物扫描相邻 9 个 64 单位的格子。5000 只围成一团时，
//! 平均每只要比较约 200 个候选，真正重叠的只有个位数，绝大部分是白算。这里改成：
//! - 普通体型（半径不超过 [`SMALL_R`]）放进专用的细网格，格子边长刚好覆盖两只普通妖物的最小间距，
//!   查相邻 3×3 格就不会漏；
//! - 精英、夜主这类大体型数量很少，单独列成表，每只妖物都和它们直接比较；
//! - 所有推力都按本步开始时的位置快照计算，算完一起写回。结果与遍历顺序无关，
//!   以后可以放心并行；快照按格子连续存放，扫描时对缓存友好。

use bevy_ecs::prelude::*;
use bevy_tasks::{ComputeTaskPool, TaskPool};

use lantern_content::Rank;
use lantern_core::step::DT;

use crate::enemies::{ENEMY_CAP, Enemies};
use crate::run::SimView;
use crate::{GameContent, Player, Pos};

/// 普通体型的最大半径。
pub const SMALL_R: f32 = 19.5;
/// 最小间距系数：两只妖物中心距离小于 (r1 + r2) × SPACING 时互相推开
const SPACING: f32 = 0.85;
/// 格子边长不小于两只普通妖物的最小间距
const CELL: f32 = 34.0;
const _: () = assert!(CELL >= SMALL_R * 2.0 * SPACING);
const MAX_COLS: usize = 128;
const NO_CELL: u32 = u32::MAX;

#[derive(Resource)]
pub struct Crowd {
    cols: usize,
    rows: usize,
    ox: f32,
    oy: f32,
    start: Vec<u32>,
    count: Vec<u32>,
    /// 普通体型妖物的快照，按格子排好
    sx: Vec<f32>,
    sy: Vec<f32>,
    sr: Vec<f32>,
    /// 每个槽位所在的格子；大体型为 NO_CELL
    cell_of: Vec<u32>,
    /// 大体型妖物：(槽位, x, y, r)
    big: Vec<(u32, f32, f32, f32)>,
    /// 本步参与计算的槽位，以及算出的新位置（与 subjects 一一对应）
    subjects: Vec<u32>,
    nx: Vec<f32>,
    ny: Vec<f32>,
}

impl Default for Crowd {
    fn default() -> Self {
        Crowd {
            cols: 1,
            rows: 1,
            ox: 0.0,
            oy: 0.0,
            start: vec![0; MAX_COLS * MAX_COLS + 1],
            count: vec![0; MAX_COLS * MAX_COLS],
            sx: vec![0.0; ENEMY_CAP],
            sy: vec![0.0; ENEMY_CAP],
            sr: vec![0.0; ENEMY_CAP],
            cell_of: vec![NO_CELL; ENEMY_CAP],
            big: Vec::new(),
            subjects: Vec::with_capacity(ENEMY_CAP),
            nx: vec![0.0; ENEMY_CAP],
            ny: vec![0.0; ENEMY_CAP],
        }
    }
}

impl Crowd {
    fn cell_xy(&self, x: f32, y: f32) -> (usize, usize) {
        // 先夹到非负再截断，等同于向下取整，又不用调用 floorf
        let c = (((x - self.ox) / CELL).max(0.0) as usize).min(self.cols - 1);
        let r = (((y - self.oy) / CELL).max(0.0) as usize).min(self.rows - 1);
        (c, r)
    }

    /// 以 (cx, cy) 为中心、半边长 half 建网格并拍快照。
    fn build(&mut self, en: &Enemies, cx: f32, cy: f32, half: f32) {
        self.cols = (((half * 2.0) / CELL).ceil() as usize + 1).min(MAX_COLS);
        self.rows = self.cols;
        self.ox = ((cx - half) / CELL).floor() * CELL;
        self.oy = ((cy - half) / CELL).floor() * CELL;
        let n = self.cols * self.rows;
        self.count[..n].fill(0);
        self.big.clear();
        for i in en.iter_alive() {
            if en.r[i] > SMALL_R {
                self.cell_of[i] = NO_CELL;
                self.big.push((i as u32, en.x[i], en.y[i], en.r[i]));
                continue;
            }
            let (c, r) = self.cell_xy(en.x[i], en.y[i]);
            let cell = r * self.cols + c;
            self.cell_of[i] = cell as u32;
            self.count[cell] += 1;
        }
        let mut acc = 0;
        for c in 0..n {
            self.start[c] = acc;
            acc += self.count[c];
            self.count[c] = 0;
        }
        self.start[n] = acc;
        for i in en.iter_alive() {
            let cell = self.cell_of[i];
            if cell == NO_CELL {
                continue;
            }
            let cell = cell as usize;
            let k = (self.start[cell] + self.count[cell]) as usize;
            self.count[cell] += 1;
            self.sx[k] = en.x[i];
            self.sy[k] = en.y[i];
            self.sr[k] = en.r[i];
        }
    }
}

/// 重叠时的推力。单独成函数且不内联：否则编译器会把“是否重叠”的分支改成无条件计算，
/// 让绝大多数不重叠的候选也付出开平方和除法的代价（实测慢 4 倍）。
#[inline(never)]
fn overlap_push(dx: f32, dy: f32, d2: f32, min: f32, k: f32) -> (f32, f32) {
    let d = d2.sqrt();
    let p = (min - d) * k / d;
    (dx * p, dy * p)
}

/// 一对妖物的推力：返回施加在 (x, y) 这只身上的位移。
#[inline(always)]
fn push(x: f32, y: f32, r: f32, ox: f32, oy: f32, or: f32, k: f32, acc: &mut (f32, f32)) {
    let (dx, dy) = (x - ox, y - oy);
    let min = (r + or) * SPACING;
    let d2 = dx * dx + dy * dy;
    if d2 < min * min && d2 > 0.01 {
        let (px, py) = overlap_push(dx, dy, d2, min, k);
        acc.0 += px;
        acc.1 += py;
    }
}

/// 按快照计算 subjects 里每只妖物的新位置，写进 out_x / out_y（与 subjects 一一对应）。
fn solve(
    crowd: &Crowd,
    en: &Enemies,
    content: &lantern_content::Content,
    subjects: &[u32],
    out_x: &mut [f32],
    out_y: &mut [f32],
) {
    let k = 0.5 * (DT * 12.0).min(1.0);
    for ((&i, ox_out), oy_out) in subjects.iter().zip(out_x).zip(out_y) {
        let i = i as usize;
        let (x, y, r) = (en.x[i], en.y[i], en.r[i]);
        let mut acc = (0.0, 0.0);
        if content.enemies[en.kind[i] as usize].rank != Rank::Boss {
            // 普通体型邻居：相邻格子；自己是大体型时多扫几圈
            let reach = (((r + SMALL_R) * SPACING) / CELL).ceil().max(1.0) as usize;
            let (cc, cr) = crowd.cell_xy(x, y);
            let c0 = cc.saturating_sub(reach);
            let c1 = (cc + reach).min(crowd.cols - 1);
            for row in cr.saturating_sub(reach)..=(cr + reach).min(crowd.rows - 1) {
                let base = row * crowd.cols;
                let (s, e) = (crowd.start[base + c0] as usize, crowd.start[base + c1 + 1] as usize);
                // 自己也在快照里，但距离为 0，会被 push 里的 d2 > 0.01 排除，不用单独判断
                for ((&ox, &oy), &or) in crowd.sx[s..e].iter().zip(&crowd.sy[s..e]).zip(&crowd.sr[s..e]) {
                    push(x, y, r, ox, oy, or, k, &mut acc);
                }
            }
            for &(o, bx, by, br) in &crowd.big {
                if o as usize != i {
                    push(x, y, r, bx, by, br, k, &mut acc);
                }
            }
        }
        *ox_out = x + acc.0;
        *oy_out = y + acc.1;
    }
}

/// 少于这么多只时不值得分线程
const PARALLEL_MIN: usize = 1024;
const CHUNK: usize = 512;

pub(crate) fn separate(
    content: Res<GameContent>,
    view: Res<SimView>,
    player: Single<&Pos, With<Player>>,
    mut crowd: ResMut<Crowd>,
    mut en: ResMut<Enemies>,
) {
    let crowd = &mut *crowd;
    let en = &mut *en;
    crowd.build(en, player.0.x, player.0.y, view.radius * 1.8);
    let mut subjects = std::mem::take(&mut crowd.subjects);
    subjects.clear();
    subjects.extend(en.iter_alive().map(|i| i as u32));
    let n = subjects.len();
    let (mut nx, mut ny) = (std::mem::take(&mut crowd.nx), std::mem::take(&mut crowd.ny));
    {
        let (crowd, en, content) = (&*crowd, &*en, &*content.0);
        let (out_x, out_y) = (&mut nx[..n], &mut ny[..n]);
        // 每只只读快照、只写自己的输出，怎么分线程结果都逐位相同
        if n >= PARALLEL_MIN {
            let pool = ComputeTaskPool::get_or_init(TaskPool::default);
            pool.scope(|scope| {
                for ((sub, ox), oy) in
                    subjects.chunks(CHUNK).zip(out_x.chunks_mut(CHUNK)).zip(out_y.chunks_mut(CHUNK))
                {
                    scope.spawn(async move { solve(crowd, en, content, sub, ox, oy) });
                }
            });
        } else {
            solve(crowd, en, content, &subjects, out_x, out_y);
        }
    }
    for (k, &i) in subjects.iter().enumerate() {
        en.x[i as usize] = nx[k];
        en.y[i as usize] = ny[k];
    }
    crowd.nx = nx;
    crowd.ny = ny;
    crowd.subjects = subjects;
}
