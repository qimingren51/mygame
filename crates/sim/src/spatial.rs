//! 空间网格（移植自网页版 sim/spatial.ts）：以玩家为中心的均匀网格，每步用计数排序重建，
//! 不分配内存。查询“圆心 (x, y)、半径 r 的圆”接触到的妖物（判定距离为 r + 妖物半径）。

use bevy_ecs::prelude::*;

use crate::enemies::{ENEMY_CAP, Enemies};

pub const CELL: f32 = 64.0;
/// 妖物的最大半径；查询时多扫这么远，保证不漏掉大体型妖物
const MAX_ENEMY_R: f32 = 48.0;
const MAX_COLS: usize = 96;
const MAX_ROWS: usize = 96;

#[derive(Resource)]
pub struct Grid {
    pub cols: usize,
    pub rows: usize,
    /// 网格左上角的世界坐标
    ox: f32,
    oy: f32,
    /// 第 c 个格子里的妖物是 items[start[c] .. start[c+1]]
    pub start: Vec<u32>,
    pub items: Vec<u32>,
    /// 建网格时每只妖物所在的格子
    pub cell_of: Vec<u32>,
    count: Vec<u32>,
}

impl Default for Grid {
    fn default() -> Self {
        Grid {
            cols: 1,
            rows: 1,
            ox: 0.0,
            oy: 0.0,
            start: vec![0; MAX_COLS * MAX_ROWS + 1],
            items: vec![0; ENEMY_CAP],
            cell_of: vec![0; ENEMY_CAP],
            count: vec![0; MAX_COLS * MAX_ROWS],
        }
    }
}

impl Grid {
    /// 以 (cx, cy) 为中心、半宽 hw、半高 hh 建网格；超出范围的妖物归到边缘格子。
    pub fn build(&mut self, en: &Enemies, cx: f32, cy: f32, hw: f32, hh: f32) {
        self.cols = (((hw * 2.0) / CELL).ceil() as usize + 1).min(MAX_COLS);
        self.rows = (((hh * 2.0) / CELL).ceil() as usize + 1).min(MAX_ROWS);
        self.ox = ((cx - hw) / CELL).floor() * CELL;
        self.oy = ((cy - hh) / CELL).floor() * CELL;
        let n = self.cols * self.rows;
        self.count[..n].fill(0);
        for i in en.iter_alive() {
            let c = self.cell_index(en.x[i], en.y[i]);
            self.cell_of[i] = c as u32;
            self.count[c] += 1;
        }
        let mut acc = 0;
        for c in 0..n {
            self.start[c] = acc;
            acc += self.count[c];
            self.count[c] = 0;
        }
        self.start[n] = acc;
        for i in en.iter_alive() {
            let c = self.cell_of[i] as usize;
            self.items[(self.start[c] + self.count[c]) as usize] = i as u32;
            self.count[c] += 1;
        }
    }

    // 先夹到非负再截断，等同于向下取整，又不用调用 floorf
    fn col(&self, x: f32) -> usize {
        (((x - self.ox) / CELL).max(0.0) as usize).min(self.cols - 1)
    }

    fn row(&self, y: f32) -> usize {
        (((y - self.oy) / CELL).max(0.0) as usize).min(self.rows - 1)
    }

    pub fn cell_index(&self, x: f32, y: f32) -> usize {
        self.row(y) * self.cols + self.col(x)
    }

    /// 格子 c 里的妖物槽位。
    pub fn cell(&self, c: usize) -> &[u32] {
        &self.items[self.start[c] as usize..self.start[c + 1] as usize]
    }

    /// 把接触到圆 (x, y, r) 的妖物槽位追加到 out（按格子顺序，确定）。
    pub fn query_circle(&self, en: &Enemies, x: f32, y: f32, r: f32, out: &mut Vec<u32>) {
        let reach = r + MAX_ENEMY_R;
        let (c0, c1) = (self.col(x - reach), self.col(x + reach));
        let (r0, r1) = (self.row(y - reach), self.row(y + reach));
        for row in r0..=r1 {
            for col in c0..=c1 {
                for &i in self.cell(row * self.cols + col) {
                    let i = i as usize;
                    if !en.alive[i] {
                        continue;
                    }
                    let (dx, dy) = (en.x[i] - x, en.y[i] - y);
                    let rr = r + en.r[i];
                    if dx * dx + dy * dy <= rr * rr {
                        out.push(i as u32);
                    }
                }
            }
        }
    }

    /// 中心离 (x, y) 不超过 range 的妖物里最近的 k 只，按距离从近到远写进 out（距离相同的按扫描顺序）。
    /// 隐身（[`Enemies::cloaked`]）的不算：自动瞄准锁定不到它们。
    pub fn nearest_k(&self, en: &Enemies, x: f32, y: f32, range: f32, k: usize, out: &mut Vec<u32>) {
        out.clear();
        if k == 0 {
            return;
        }
        let mut d2s: [f32; 64] = [0.0; 64];
        let k = k.min(d2s.len());
        let range2 = range * range;
        let (c0, c1) = (self.col(x - range), self.col(x + range));
        let (r0, r1) = (self.row(y - range), self.row(y + range));
        for row in r0..=r1 {
            for col in c0..=c1 {
                for &i in self.cell(row * self.cols + col) {
                    let iu = i as usize;
                    if !en.alive[iu] || en.cloaked[iu] {
                        continue;
                    }
                    let (dx, dy) = (en.x[iu] - x, en.y[iu] - y);
                    let d2 = dx * dx + dy * dy;
                    if d2 > range2 || (out.len() == k && d2 >= d2s[k - 1]) {
                        continue;
                    }
                    // 插入排序（k 很小）
                    let mut j = if out.len() < k {
                        out.push(i);
                        out.len() - 1
                    } else {
                        k - 1
                    };
                    while j > 0 && d2s[j - 1] > d2 {
                        d2s[j] = d2s[j - 1];
                        out[j] = out[j - 1];
                        j -= 1;
                    }
                    d2s[j] = d2;
                    out[j] = i;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn query_matches_brute_force() {
        let mut en = Enemies::default();
        let mut rng = lantern_core::Pcg32::new(9, 0);
        for _ in 0..800 {
            let i = en.alloc().unwrap();
            en.x[i] = rng.range_f32(-900.0, 900.0);
            en.y[i] = rng.range_f32(-900.0, 900.0);
            en.r[i] = rng.range_f32(8.0, 40.0);
        }
        let mut g = Grid::default();
        g.build(&en, 30.0, -20.0, 1000.0, 1000.0);
        for _ in 0..50 {
            let (x, y, r) =
                (rng.range_f32(-800.0, 800.0), rng.range_f32(-800.0, 800.0), rng.range_f32(5.0, 120.0));
            let mut got = Vec::new();
            g.query_circle(&en, x, y, r, &mut got);
            got.sort_unstable();
            let want: Vec<u32> = en
                .iter_alive()
                .filter(|&i| {
                    let (dx, dy) = (en.x[i] - x, en.y[i] - y);
                    let rr = r + en.r[i];
                    dx * dx + dy * dy <= rr * rr
                })
                .map(|i| i as u32)
                .collect();
            assert_eq!(got, want);
        }
    }

    #[test]
    fn nearest_k_matches_brute_force() {
        let mut en = Enemies::default();
        let mut rng = lantern_core::Pcg32::new(4, 0);
        for _ in 0..600 {
            let i = en.alloc().unwrap();
            en.x[i] = rng.range_f32(-700.0, 700.0);
            en.y[i] = rng.range_f32(-700.0, 700.0);
            en.r[i] = 10.0;
        }
        let mut g = Grid::default();
        g.build(&en, 0.0, 0.0, 800.0, 800.0);
        let mut got = Vec::new();
        for _ in 0..50 {
            let (x, y) = (rng.range_f32(-500.0, 500.0), rng.range_f32(-500.0, 500.0));
            let range = rng.range_f32(50.0, 400.0);
            let k = 1 + rng.below(12) as usize;
            g.nearest_k(&en, x, y, range, k, &mut got);
            let d2 = |i: usize| (en.x[i] - x) * (en.x[i] - x) + (en.y[i] - y) * (en.y[i] - y);
            let mut want: Vec<usize> = en.iter_alive().filter(|&i| d2(i) <= range * range).collect();
            want.sort_by(|&a, &b| d2(a).total_cmp(&d2(b)));
            want.truncate(k);
            let got_d: Vec<f32> = got.iter().map(|&i| d2(i as usize)).collect();
            let want_d: Vec<f32> = want.iter().map(|&i| d2(i)).collect();
            assert_eq!(got_d, want_d);
        }
    }
}
