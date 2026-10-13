//! 妖物池：按字段分数组（SoA），不用 ECS 实体（docs/DESIGN.md 第 6.2 节）。
//!
//! - 热路径（移动、互推、碰撞）连续访问同一字段，缓存友好，没有实体创建销毁的开销。
//! - 遍历顺序只由模拟决定（槽位顺序），画面层怎么挂组件都不会影响结果，保证可复现。
//! - 死亡的槽位进空闲列表复用；对外用“槽位 + 代号”的句柄引用，槽位复用后旧句柄自动失效。

use bevy_ecs::prelude::*;

use lantern_core::StateHasher;

/// 同时存在的妖物上限。
pub const ENEMY_CAP: usize = 8192;
const SLOT_BITS: u32 = 13;
const SLOT_MASK: u32 = (1 << SLOT_BITS) - 1;
const _: () = assert!(1 << SLOT_BITS == ENEMY_CAP);

/// [`Enemies::tags`] 的标记位：小头目
pub const TAG_MINIBOSS: u8 = 1;
/// 精英“分”出来的小号（不算精英，不掉宝箱和铜钱，不再分裂）
pub const TAG_CHILD: u8 = 2;
/// “狂”已经发作
pub const TAG_FRENZY: u8 = 4;

/// 指向某只妖物的句柄。妖物死后（或槽位被复用后）解析为 `None`。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EnemyHandle(u32);

#[derive(Resource)]
pub struct Enemies {
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    /// 上一步的位置，画面插值用
    pub px: Vec<f32>,
    pub py: Vec<f32>,
    pub r: Vec<f32>,
    pub hp: Vec<f32>,
    pub max_hp: Vec<f32>,
    pub speed: Vec<f32>,
    pub damage: Vec<f32>,
    /// 击退速度，每步衰减
    pub kx: Vec<f32>,
    pub ky: Vec<f32>,
    /// 受击闪白剩余时间
    pub flash: Vec<f32>,
    /// 每只的随机相位（摇摆、动画错相）
    pub wob: Vec<f32>,
    /// 灯火下一次可以命中它的时刻（秒）
    pub lamp_ready: Vec<f32>,
    pub slow_t: Vec<f32>,
    pub slow_amount: Vec<f32>,
    pub frozen: Vec<f32>,
    pub stun: Vec<f32>,
    /// 灼烧：剩余时间、层数、每层每秒伤害；累计伤害与显示计时（每 0.5 秒冒一个数字）
    pub burn_t: Vec<f32>,
    pub burn_stacks: Vec<f32>,
    pub burn_dps: Vec<f32>,
    pub burn_acc: Vec<f32>,
    pub burn_show: Vec<f32>,
    /// 夜主的出招计时：弹幕、召唤
    pub atk_t: Vec<f32>,
    pub summon_t: Vec<f32>,
    /// 五行印记：0 没有，否则是 [`lantern_content::Element::index`] + 1；剩余时间；反应冷却
    pub mark: Vec<u8>,
    pub mark_t: Vec<f32>,
    pub react_cd: Vec<f32>,
    /// 熔金的易伤与剩余时间
    pub melt: Vec<f32>,
    pub melt_t: Vec<f32>,
    /// 定身（缠住）：不能移动，但仍会还手
    pub root: Vec<f32>,
    /// 晕头：朝 confuse_dir 方向乱走
    pub confuse: Vec<f32>,
    pub confuse_dir: Vec<f32>,
    /// 在淤泥里：受到的击退乘这个倍率（本步有效）
    pub mud: Vec<f32>,
    /// 被命中的次数（水·极境：每第 3 次必定冰冻）
    pub hit_n: Vec<u8>,
    /// 当前的冰冻来自冰爆（这样冻住的再死不触发冰爆）
    pub blast_frozen: Vec<bool>,
    /// 精英词缀（`affixes.ron` 的下标作位）与标记（TAG_*）
    pub affix: Vec<u16>,
    pub tags: Vec<u8>,
    /// 合围：大于 0 时移速乘它，直到离主角足够近
    pub rush: Vec<f32>,
    /// “隐”：在照见圈外，自动瞄准锁定不到
    pub cloaked: Vec<bool>,
    /// 控制递减（只对精英）：6 秒内受到的硬控、软控次数与窗口剩余时间
    pub hard_n: Vec<u8>,
    pub hard_t: Vec<f32>,
    pub soft_n: Vec<u8>,
    pub soft_t: Vec<f32>,
    /// 妖物种类（`enemies.ron` 里的下标）
    pub kind: Vec<u16>,
    pub alive: Vec<bool>,
    generation: Vec<u16>,
    /// 用过的最大槽位 + 1，遍历时到这里为止
    pub hi: usize,
    pub count: usize,
    free: Vec<u32>,
}

impl Default for Enemies {
    fn default() -> Self {
        let f = || vec![0.0f32; ENEMY_CAP];
        Enemies {
            x: f(),
            y: f(),
            px: f(),
            py: f(),
            r: f(),
            hp: f(),
            max_hp: f(),
            speed: f(),
            damage: f(),
            kx: f(),
            ky: f(),
            flash: f(),
            wob: f(),
            lamp_ready: f(),
            slow_t: f(),
            slow_amount: f(),
            frozen: f(),
            stun: f(),
            burn_t: f(),
            burn_stacks: f(),
            burn_dps: f(),
            burn_acc: f(),
            burn_show: f(),
            atk_t: f(),
            summon_t: f(),
            mark: vec![0; ENEMY_CAP],
            mark_t: f(),
            react_cd: f(),
            melt: f(),
            melt_t: f(),
            root: f(),
            confuse: f(),
            confuse_dir: f(),
            mud: f(),
            hit_n: vec![0; ENEMY_CAP],
            blast_frozen: vec![false; ENEMY_CAP],
            affix: vec![0; ENEMY_CAP],
            tags: vec![0; ENEMY_CAP],
            rush: f(),
            cloaked: vec![false; ENEMY_CAP],
            hard_n: vec![0; ENEMY_CAP],
            hard_t: f(),
            soft_n: vec![0; ENEMY_CAP],
            soft_t: f(),
            kind: vec![0; ENEMY_CAP],
            alive: vec![false; ENEMY_CAP],
            generation: vec![0; ENEMY_CAP],
            hi: 0,
            count: 0,
            free: Vec::with_capacity(ENEMY_CAP),
        }
    }
}

impl Enemies {
    /// 分配一个槽位并清空状态；满了返回 `None`。
    pub fn alloc(&mut self) -> Option<usize> {
        let i = if let Some(i) = self.free.pop() {
            i as usize
        } else if self.hi < ENEMY_CAP {
            self.hi += 1;
            self.hi - 1
        } else {
            return None;
        };
        self.alive[i] = true;
        self.count += 1;
        for v in [
            &mut self.kx,
            &mut self.ky,
            &mut self.flash,
            &mut self.lamp_ready,
            &mut self.slow_t,
            &mut self.slow_amount,
            &mut self.frozen,
            &mut self.stun,
            &mut self.burn_t,
            &mut self.burn_stacks,
            &mut self.burn_dps,
            &mut self.burn_acc,
            &mut self.burn_show,
            &mut self.atk_t,
            &mut self.summon_t,
            &mut self.mark_t,
            &mut self.react_cd,
            &mut self.melt,
            &mut self.melt_t,
            &mut self.root,
            &mut self.confuse,
            &mut self.confuse_dir,
            &mut self.mud,
            &mut self.hard_t,
            &mut self.soft_t,
            &mut self.rush,
        ] {
            v[i] = 0.0;
        }
        self.affix[i] = 0;
        self.tags[i] = 0;
        self.cloaked[i] = false;
        self.mark[i] = 0;
        self.hit_n[i] = 0;
        self.blast_frozen[i] = false;
        self.hard_n[i] = 0;
        self.soft_n[i] = 0;
        Some(i)
    }

    pub fn kill(&mut self, i: usize) {
        if !self.alive[i] {
            return;
        }
        self.alive[i] = false;
        self.generation[i] = self.generation[i].wrapping_add(1);
        self.free.push(i as u32);
        self.count -= 1;
    }

    pub fn handle(&self, i: usize) -> EnemyHandle {
        EnemyHandle(i as u32 | (u32::from(self.generation[i]) << SLOT_BITS))
    }

    pub fn resolve(&self, h: EnemyHandle) -> Option<usize> {
        let i = (h.0 & SLOT_MASK) as usize;
        (self.alive[i] && u32::from(self.generation[i]) == h.0 >> SLOT_BITS).then_some(i)
    }

    /// 存活的槽位，按槽位顺序。
    pub fn iter_alive(&self) -> impl Iterator<Item = usize> + '_ {
        (0..self.hi).filter(|&i| self.alive[i])
    }

    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.count as u32);
        for i in self.iter_alive() {
            h.write_u32(i as u32);
            h.write_u32(u32::from(self.kind[i]));
            h.write_u32(u32::from(self.mark[i]));
            for v in
                [self.x[i], self.y[i], self.hp[i], self.kx[i], self.ky[i], self.burn_t[i], self.frozen[i]]
            {
                h.write_f32(v);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn handles_expire_when_slot_is_reused() {
        let mut en = Enemies::default();
        let a = en.alloc().unwrap();
        let ha = en.handle(a);
        assert_eq!(en.resolve(ha), Some(a));
        en.kill(a);
        assert_eq!(en.resolve(ha), None);
        let b = en.alloc().unwrap();
        assert_eq!(a, b, "空闲槽位被复用");
        assert_eq!(en.resolve(ha), None, "旧句柄不能指向新妖物");
        assert_eq!(en.count, 1);
    }
}
