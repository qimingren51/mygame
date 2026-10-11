(() => {
  'use strict';

  // =====================================================================
  // 工具
  // =====================================================================
  const TAU = Math.PI * 2;
  const rand = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const $ = (id) => document.getElementById(id);
  const fmtTime = (sec) => {
    const s = Math.max(0, Math.floor(sec));
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  };
  const fmtNum = (n) => Math.floor(n).toLocaleString('en-US');

  // 音频模块（audio.js）缺失时所有音效调用都变成空操作
  const AUDIO = typeof LanternAudio !== 'undefined' ? LanternAudio : null;
  const SFX = AUDIO ? AUDIO.sfx : new Proxy({}, { get: () => () => {} });

  // localStorage 键名统一加 lantern_ 前缀
  const STORE_OIL = 'lantern_oil';
  const STORE_META = 'lantern_meta';
  const STORE_BEST = 'lantern_best';

  function load(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  }
  function save(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // 隐私模式等情况下存储不可用，忽略
    }
  }

  function hash2(x, y) {
    let h = Math.imul(x, 374761393) + Math.imul(y, 668265263);
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return (h ^ (h >>> 16)) >>> 0;
  }
  function seeded(seed) {
    let a = seed;
    return () => {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // =====================================================================
  // 数据：五行、法器、心法、妖物、心灯
  // =====================================================================
  const EL = {
    metal: { name: '金', res: '锐', color: '#E9D9A6', tiers: ['暴击率 +10%', '暴击伤害 +50%', '暴击时追加飞剑'] },
    wood: { name: '木', res: '生', color: '#6FD6A0', tiers: ['每秒回复 0.5% 生命', '数量 +1', '击杀回复生命'] },
    water: { name: '水', res: '凝', color: '#6FB8FF', tiers: ['命中减速', '命中有概率冰冻', '冰冻目标易伤并碎裂'] },
    fire: { name: '火', res: '焚', color: '#FF8A3D', tiers: ['命中附加灼烧', '灼烧可叠加', '妖物死亡时爆炸'] },
    earth: { name: '土', res: '固', color: '#C9925A', tiers: ['周期获得护盾', '击退加倍', '护盾破碎时震地'] },
  };
  const EL_ORDER = ['metal', 'wood', 'water', 'fire', 'earth'];
  // 相生：木 → 火 → 土 → 金 → 水 → 木
  const SHENG = [
    { a: 'wood', b: 'fire', name: '木生火', desc: '灼烧伤害 +30%' },
    { a: 'fire', b: 'earth', name: '火生土', desc: '护盾恢复加快' },
    { a: 'earth', b: 'metal', name: '土生金', desc: '被击晕的目标必定暴击' },
    { a: 'metal', b: 'water', name: '金生水', desc: '暴击使目标减速' },
    { a: 'water', b: 'wood', name: '水生木', desc: '生命回复翻倍' },
  ];
  const tierOf = (n) => (n >= 6 ? 3 : n >= 4 ? 2 : n >= 2 ? 1 : 0);

  const WEAPON_MAX = 8;
  const PASSIVE_MAX = 5;
  const SLOT_MAX = 6;

  const WEAPONS = {
    lamp: {
      name: '灯火', icon: '灯', el: 'fire', evoPassive: 'changming', evoName: '不夜城',
      desc: '火焰环绕周身，烧灼靠近的妖物。',
      evoDesc: '十盏灯笼环城而行，范围更大、伤害翻倍',
    },
    sword: {
      name: '符剑', icon: '剑', el: 'metal', evoPassive: 'jianyi', evoName: '万剑归宗',
      desc: '自动射出追踪符剑，可穿透。',
      evoDesc: '飞剑连发，无限穿透',
    },
    bell: {
      name: '霜铃', icon: '铃', el: 'water', evoPassive: 'jingxin', evoName: '寒山钟',
      desc: '周期震出寒波，伤害并减速周围妖物。',
      evoDesc: '每 6 秒钟鸣全屏，冻结所有妖物',
    },
    crane: {
      name: '纸鹤', icon: '鹤', el: 'wood', evoPassive: 'zhezhi', evoName: '千鹤引',
      desc: '纸鹤自动扑向妖物，撞击后折返。',
      evoDesc: '十只纸鹤随身，扑击更快更狠',
    },
    seal: {
      name: '山印', icon: '印', el: 'earth', evoPassive: 'houde', evoName: '镇岳',
      desc: '石印从天而降，范围伤害并击晕。',
      evoDesc: '巨岩砸出地裂，裂缝持续伤害并减速',
    },
  };

  // 各法器每级数值
  const W = {
    lamp: (lv) => ({ count: [3, 3, 4, 4, 5, 5, 6, 6][lv - 1], radius: 50 + lv * 4, dmg: 12 + lv * 3 }),
    sword: (lv) => ({ cd: 1.15 - lv * 0.06, count: 1 + Math.floor(lv / 3), dmg: 12 + lv * 4, pierce: 1 + Math.floor(lv / 3) }),
    bell: (lv) => ({ cd: 3 - lv * 0.15, radius: 70 + lv * 9, dmg: 6 + lv * 3 }),
    crane: (lv) => ({ count: [1, 1, 2, 2, 3, 3, 4, 4][lv - 1], dmg: 9 + lv * 3 }),
    seal: (lv) => ({ cd: 4.2 - lv * 0.22, count: 1 + Math.floor(lv / 3), radius: 38 + lv * 4, dmg: 22 + lv * 8 }),
  };
  const STAT_LABEL = { count: '数量', dmg: '伤害', radius: '范围', pierce: '穿透', cd: '冷却' };

  const PASSIVES = {
    changming: { name: '长明', el: 'fire', desc: '攻击范围 +10%' },
    luxin: { name: '炉心', el: 'fire', desc: '伤害 +8%' },
    jianyi: { name: '剑意', el: 'metal', desc: '暴击伤害 +20%' },
    ruimu: { name: '锐目', el: 'metal', desc: '暴击率 +5%' },
    jingxin: { name: '静心', el: 'water', desc: '冷却 -6%' },
    yinhun: { name: '引魂', el: 'water', desc: '拾取范围 +25%' },
    zhezhi: { name: '折纸', el: 'wood', desc: '1 / 3 / 5 级时数量 +1' },
    jixing: { name: '疾行', el: 'wood', desc: '移动速度 +8%' },
    houde: { name: '厚德', el: 'earth', desc: '生命上限 +20，护甲 +1' },
    panshi: { name: '磐石', el: 'earth', desc: '受到伤害 -5%' },
  };

  const ENEMY = {
    shade: { name: '影妖', r: 13, hp: 10, speed: 46, dmg: 5, xp: 1, body: '#1C1630', rim: '#4A3873', eye: '#FF8A5B' },
    wisp: { name: '疾影', r: 10, hp: 6, speed: 84, dmg: 4, xp: 1, body: '#141E2C', rim: '#3B5F80', eye: '#9FE3FF' },
    golem: { name: '石妖', r: 19, hp: 45, speed: 30, dmg: 10, xp: 3, body: '#211B17', rim: '#6A5238', eye: '#FFB46B' },
    fox: { name: '赤面狐', r: 24, hp: 320, speed: 58, dmg: 14, xp: 20, elite: true, body: '#2A1426', rim: '#FF6B5A', eye: '#FF6B5A', mask: '#F4EBDD' },
    ghoul: { name: '青面鬼', r: 30, hp: 900, speed: 50, dmg: 18, xp: 40, elite: true, body: '#13231F', rim: '#5FD4A0', eye: '#C8FF6B', mask: '#CFE8DC' },
    boss: { name: '夜主 · 九尾', r: 44, hp: 36000, speed: 52, dmg: 22, xp: 0, boss: true, body: '#2A1426', rim: '#FFB46B', eye: '#FFD98A', mask: '#F4EBDD' },
    stonelord: { name: '石将', r: 28, hp: 1100, speed: 34, dmg: 16, xp: 30, elite: true, body: '#2A2119', rim: '#C9925A', eye: '#FFB46B' },
    toad: { name: '金蟾', r: 14, hp: 70, speed: 80, dmg: 0, xp: 0, toad: true, body: '#5A4210', rim: '#FFD98A', eye: '#FFF1C2' },
  };
  const ELITE_INFO = {
    fox: { label: '精英 · 赤面狐', color: '#FF6B5A' },
    ghoul: { label: '小头目 · 青面鬼', color: '#5FD4A0' },
    stonelord: { label: '精英 · 石将', color: '#C9925A' },
  };

  // 夜签：开局三选一的本局规则，有好处也有代价
  const OMENS = [
    { id: 'bloodmoon', name: '血月', good: '魂火 +35%', bad: '妖物数量 +35%', apply: (m) => { m.xp *= 1.35; m.spawn *= 1.35; } },
    { id: 'fog', name: '浓雾', good: '暴击率 +15%', bad: '灯光范围 -30%', apply: (m) => { m.crit += 0.15; m.light *= 0.7; } },
    { id: 'glass', name: '琉璃灯', good: '伤害 +40%', bad: '生命上限 -35%', apply: (m) => { m.dmg *= 1.4; m.maxHp *= 0.65; } },
    { id: 'foxes', name: '狐火夜', good: '宝箱至少三连', bad: '精英数量翻倍', apply: (m) => { m.chestMin = 3; m.elites = 2; } },
    { id: 'gale', name: '疾风', good: '移动速度 +25%', bad: '妖物移速 +25%', apply: (m) => { m.speed *= 1.25; m.enemySpeed *= 1.25; } },
    { id: 'chestrain', name: '天降宝箱', good: '每 100 秒天降宝箱', bad: '妖物血量 +25%', apply: (m) => { m.chestRain = true; m.enemyHp *= 1.25; } },
    { id: 'element', name: '五行偏重', good: '', bad: '其他四系选项更少出现', apply: (m, o) => { m.favor = o.el; } },
    { id: 'greed', name: '贪婪', good: '灯油收益 +50%', bad: '无法回复生命', apply: (m) => { m.oil *= 1.5; m.noHeal = true; } },
    { id: 'quiet', name: '静夜', good: '妖物数量 -25%', bad: '升级只有两个选项', apply: (m) => { m.spawn *= 0.75; m.choices = 2; } },
    { id: 'wonders', name: '奇遇夜', good: '奇遇出现频率翻倍', bad: '妖物血量 +15%', apply: (m) => { m.events = 2; m.enemyHp *= 1.15; } },
  ];
  const baseMods = () => ({
    xp: 1, spawn: 1, crit: 0, light: 1, dmg: 1, maxHp: 1, chestMin: 1, elites: 1, speed: 1, enemySpeed: 1,
    chestRain: false, enemyHp: 1, favor: null, oil: 1, noHeal: false, choices: 3, events: 1,
  });

  // 奇遇：地图上随机出现的事件
  const EVENTS = {
    toad: { name: '金蟾', icon: '蟾', color: '#FFD98A', weight: 3, hint: '追上它，打死就散财' },
    spring: { name: '灵泉', icon: '泉', color: '#5FD4C4', weight: 2, hint: '站在泉中回复生命' },
    shrine: { name: '古灯', icon: '灯', color: '#FF8A3D', weight: 2, hint: '触碰获得 30 秒随机增益' },
    altar: { name: '血祭坛', icon: '祭', color: '#FF6B5A', weight: 1.5, hint: '以 25% 生命换一次强化' },
    rift: { name: '妖潮裂隙', icon: '隙', color: '#B07CF0', weight: 1.5, hint: '击败守卫获得宝箱' },
  };
  const BUFFS = [
    { id: 'fury', name: '灯焰', desc: '伤害 +50%', color: '#FF8A3D' },
    { id: 'swift', name: '御风', desc: '移速 +40%', color: '#6FD6A0' },
    { id: 'soul', name: '聚魂', desc: '拾取范围 ×3', color: '#5FD4C4' },
    { id: 'iron', name: '金身', desc: '受到伤害 -60%', color: '#E9D9A6' },
  ];

  const META = [
    { id: 'dmg', name: '锋芒', icon: '锋', per: '每级伤害 +4%' },
    { id: 'hp', name: '体魄', icon: '体', per: '每级生命上限 +12' },
    { id: 'agi', name: '灵巧', icon: '灵', per: '每级移速 +3%，拾取范围 +8%' },
    { id: 'luck', name: '气运', icon: '运', per: '每级重抽 +1，宝箱更易多开' },
  ];
  const META_MAX = 5;
  const metaCost = (lv) => Math.round((120 * Math.pow(lv + 1, 1.6)) / 10) * 10;

  const RUN_LENGTH = 600; // 10 分钟
  const BOSS_TIME = 570; // 9:30 夜主降临
  const xpNeed = (lv) => 4 + 5 * lv + 0.6 * lv * lv;

  // 绘制用路径
  const FLAME = new Path2D('M0 -9 C5 -4 6 2 3 6 C1 8 -1 8 -3 6 C-6 2 -5 -4 0 -9 Z');
  const FLAME_CORE = new Path2D('M0 -3.5 C2 -1 2 2 1 4 C0 5 -1 5 -1 4 C-2 2 -2 -1 0 -3.5 Z');
  const BLOB = new Path2D('M-13 7 C-15 -5 -7 -15 0 -15 C7 -15 15 -5 13 7 C11 13 7 10 5 15 C3 11 -1 11 -3 15 C-5 11 -9 13 -13 7 Z');
  const MASK = new Path2D('M-12 -9 L0 -3 L12 -9 L8 5 L0 10 L-8 5 Z');
  const EARS = new Path2D('M-15 -12 L-9 -26 L-4 -14 Z M15 -12 L9 -26 L4 -14 Z');
  const HORNS = new Path2D('M-9 -13 L-12 -24 L-4 -15 Z M9 -13 L12 -24 L4 -15 Z');
  const SWORD = new Path2D('M14 0 L4 -2 L-6 -1.4 L-6 1.4 L4 2 Z');
  const CRANE = new Path2D('M-8 0 L-1 -1 L-3 -9 L3 -1 L10 -3 L4 1 L1 8 L-1 1 Z');
  const GEM = new Path2D('M0 -1 L0.7 0 L0 1 L-0.7 0 Z');

  // =====================================================================
  // 画布与视口
  // =====================================================================
  const canvas = $('game');
  const ctx = canvas.getContext('2d');
  if (!ctx.roundRect) {
    // 旧浏览器没有 roundRect 时退化为直角矩形
    CanvasRenderingContext2D.prototype.roundRect = function (x, y, w, h) {
      this.rect(x, y, w, h);
    };
  }
  const view = { cssW: 0, cssH: 0, dpr: 1, scale: 1, w: 0, h: 0 };
  const coarse = window.matchMedia('(pointer: coarse)').matches;

  function resize() {
    view.dpr = Math.min(window.devicePixelRatio || 1, 2);
    view.cssW = window.innerWidth;
    view.cssH = window.innerHeight;
    canvas.width = Math.round(view.cssW * view.dpr);
    canvas.height = Math.round(view.cssH * view.dpr);
    // 视野高度约 420 个世界单位，手机横屏与电脑看到的范围接近
    view.scale = clamp(view.cssH / 420, 0.75, 1.8);
    view.w = view.cssW / view.scale;
    view.h = view.cssH / view.scale;
    if (coarse && view.cssH > view.cssW && state === 'play') pauseGame();
  }
  const viewRadius = () => Math.hypot(view.w, view.h) / 2;

  // =====================================================================
  // 存档
  // =====================================================================
  let oil = load(STORE_OIL, 0);
  const meta = Object.assign({ dmg: 0, hp: 0, agi: 0, luck: 0 }, load(STORE_META, {}));
  let best = load(STORE_BEST, { time: 0, kills: 0, won: false });

  // =====================================================================
  // 状态
  // =====================================================================
  // state: title | play | levelup | chest | evo | paused | over | meta
  let state = 'title';
  let metaReturn = 'title';
  let G = null;
  let evoTimer = 0;
  const demo = { x: 0, y: 0, t: 0 };
  const mapSeed = { x: 0, y: 0 };

  function newRun(omen) {
    const mods = baseMods();
    omen.apply(mods, omen);
    G = {
      omen,
      mods,
      seed: Math.floor(Math.random() * 1e9),
      mapX: Math.floor(Math.random() * 20000) - 10000,
      mapY: Math.floor(Math.random() * 20000) - 10000,
      // 本局妖群组成：疾影、石妖的比例每局不同
      mix: { wisp: rand(0.08, 0.3), golem: rand(0.05, 0.2) },
      plan: makePlan(),
      nextEvent: rand(28, 45),
      events: [],
      buff: null,
      chestRainT: 100,
      intensity: -1,
      t: 0,
      kills: 0,
      level: 1,
      xp: 0,
      pendingLevels: 0,
      chestQueue: [],
      pendingEvos: [],
      player: { x: 0, y: 0, r: 11, hp: 100, faceX: 1, faceY: 0, iframe: 0, dashT: 0, dashCd: 0, dashVX: 0, dashVY: 0, shield: 0, shieldT: 0, moving: false },
      weapons: [],
      passives: [],
      enemies: [],
      gems: [],
      shots: [],
      foes: [],
      effects: [],
      zones: [],
      particles: [],
      numbers: [],
      pickups: [],
      blasts: [],
      res: { metal: 0, wood: 0, water: 0, fire: 0, earth: 0 },
      tier: { metal: 0, wood: 0, water: 0, fire: 0, earth: 0 },
      sheng: {},
      taiji: false,
      taijiT: 0,
      stats: {},
      rerolls: 2 + meta.luck,
      ult: 0,
      combo: 0,
      comboT: 0,
      bestCombo: 0,
      evolutions: 0,
      spawnAcc: 0,
      ev: {},
      boss: null,
      shake: 0,
      flash: null,
      edge: null,
      slowT: 0,
      oilBonus: 0,
    };
    addWeapon('lamp');
    computeStats();
    G.player.hp = G.stats.maxHp;
    hudCache = {};
    renderSlots();
  }

  // 精英与妖潮的出场时间、种类每局随机
  function makePlan() {
    return [
      { at: rand(150, 200), kind: 'elite', pool: ['fox', 'stonelord'] },
      { at: rand(270, 320), kind: 'elite', pool: ['ghoul', 'stonelord', 'fox'] },
      { at: rand(370, 420), kind: 'elite', pool: ['fox', 'ghoul', 'stonelord'] },
      { at: rand(450, 500), kind: 'surge' },
      { at: BOSS_TIME, kind: 'boss' },
    ];
  }

  function drawOmens() {
    const pool = OMENS.slice();
    const out = [];
    while (out.length < 3) {
      const o = pool.splice(Math.floor(Math.random() * pool.length), 1)[0];
      if (o.id === 'element') {
        const el = EL_ORDER[Math.floor(Math.random() * EL_ORDER.length)];
        out.push({ ...o, el, good: `${EL[el].name}系开局即得 2 点共鸣` });
      } else {
        out.push(o);
      }
    }
    return out;
  }

  const getWeapon = (id) => G.weapons.find((w) => w.id === id);
  const getPassive = (id) => G.passives.find((p) => p.id === id);
  const plv = (id) => {
    const p = getPassive(id);
    return p ? p.lv : 0;
  };

  function addWeapon(id) {
    G.weapons.push({ id, lv: 1, evo: false, t: 0.6, angle: 0, big: 6, pos: [], cranes: [] });
  }

  // =====================================================================
  // 五行共鸣与属性
  // =====================================================================
  function computeRes(announce) {
    const res = { metal: 0, wood: 0, water: 0, fire: 0, earth: 0 };
    // 满级（或已进化）的法器、满级的心法计 2 点
    for (const w of G.weapons) res[WEAPONS[w.id].el] += w.lv >= WEAPON_MAX || w.evo ? 2 : 1;
    for (const p of G.passives) res[PASSIVES[p.id].el] += p.lv >= PASSIVE_MAX ? 2 : 1;
    if (G.mods.favor) res[G.mods.favor] += 2;
    G.res = res;
    for (const el of EL_ORDER) {
      const tier = tierOf(res[el]);
      if (announce && tier > G.tier[el]) {
        const e = EL[el];
        toast(`${e.name} · ${e.res} ${res[el]}`, `共鸣激活：${e.tiers[tier - 1]}`, e.color, tier === 3);
        G.edge = { color: e.color, t: 0.9 };
        sfxFlash(e.color, 0.12);
        SFX.resonance();
      }
      G.tier[el] = tier;
    }
    for (const s of SHENG) {
      const on = G.tier[s.a] >= 1 && G.tier[s.b] >= 1;
      if (announce && on && !G.sheng[s.name]) toast(`相生 · ${s.name}`, s.desc, EL[s.b].color);
      G.sheng[s.name] = on;
    }
    const taiji = EL_ORDER.every((el) => G.tier[el] >= 1);
    if (announce && taiji && !G.taiji) toast('五行圆满 · 太极', '每 30 秒全屏轮转五行之力', '#FFD98A', true);
    G.taiji = taiji;
  }

  function computeStats(announce) {
    computeRes(announce);
    const t = G.tier;
    const s = {};
    s.area = 1 + 0.1 * plv('changming');
    const m = G.mods;
    s.dmg = (1 + 0.08 * plv('luxin')) * (1 + 0.04 * meta.dmg) * m.dmg;
    s.critChance = 0.05 + 0.05 * plv('ruimu') + (t.metal >= 1 ? 0.1 : 0) + m.crit;
    s.critMult = 2 + 0.2 * plv('jianyi') + (t.metal >= 2 ? 0.5 : 0);
    s.cd = Math.max(0.6, 1 - 0.06 * plv('jingxin'));
    s.magnet = 65 * (1 + 0.25 * plv('yinhun')) * (1 + 0.08 * meta.agi);
    s.amount = [0, 1, 1, 2, 2, 3][plv('zhezhi')] + (t.wood >= 2 ? 1 : 0);
    s.speed = 118 * (1 + 0.08 * plv('jixing')) * (1 + 0.03 * meta.agi) * m.speed;
    s.maxHp = Math.round((100 + 20 * plv('houde') + 12 * meta.hp) * m.maxHp);
    s.armor = plv('houde');
    s.taken = 1 - 0.05 * plv('panshi');
    s.regen = m.noHeal ? 0 : (t.wood >= 1 ? 0.005 * s.maxHp : 0) * (G.sheng['水生木'] ? 2 : 1);
    s.burnMult = G.sheng['木生火'] ? 1.3 : 1;
    s.shieldCd = G.sheng['火生土'] ? 6 : 10;
    s.kb = t.earth >= 2 ? 2 : 1;
    if (G.stats.maxHp && s.maxHp > G.stats.maxHp) G.player.hp += s.maxHp - G.stats.maxHp;
    G.stats = s;
    G.player.hp = Math.min(G.player.hp, s.maxHp);
  }

  // =====================================================================
  // 空间网格（加速碰撞查询）
  // =====================================================================
  const CELL = 64;
  const grid = new Map();
  const cellKey = (cx, cy) => cx * 65536 + cy;

  function buildGrid() {
    grid.clear();
    for (const e of G.enemies) {
      if (e.dead) continue;
      const k = cellKey(Math.floor(e.x / CELL), Math.floor(e.y / CELL));
      let arr = grid.get(k);
      if (!arr) {
        arr = [];
        grid.set(k, arr);
      }
      arr.push(e);
    }
  }

  // 对圆心 (x, y)、半径 r 内（含妖物自身半径）的妖物调用 fn
  function queryEnemies(x, y, r, fn) {
    const reach = r + 48;
    const x0 = Math.floor((x - reach) / CELL);
    const x1 = Math.floor((x + reach) / CELL);
    const y0 = Math.floor((y - reach) / CELL);
    const y1 = Math.floor((y + reach) / CELL);
    for (let cx = x0; cx <= x1; cx++) {
      for (let cy = y0; cy <= y1; cy++) {
        const arr = grid.get(cellKey(cx, cy));
        if (!arr) continue;
        for (const e of arr) {
          if (e.dead) continue;
          const dx = e.x - x;
          const dy = e.y - y;
          const rr = r + e.r;
          if (dx * dx + dy * dy <= rr * rr) fn(e);
        }
      }
    }
  }

  function nearestEnemies(x, y, range, k) {
    const out = [];
    const r2 = range * range;
    for (const e of G.enemies) {
      if (e.dead) continue;
      const d2 = (e.x - x) ** 2 + (e.y - y) ** 2;
      if (d2 > r2) continue;
      if (out.length < k) {
        out.push({ e, d2 });
        out.sort((a, b) => a.d2 - b.d2);
      } else if (d2 < out[k - 1].d2) {
        out[k - 1] = { e, d2 };
        out.sort((a, b) => a.d2 - b.d2);
      }
    }
    return out.map((o) => o.e);
  }

  const onScreen = (e, margin = 30) =>
    Math.abs(e.x - G.player.x) < view.w / 2 + margin && Math.abs(e.y - G.player.y) < view.h / 2 + margin;

  // =====================================================================
  // 伤害与击杀
  // =====================================================================
  function hitEnemy(e, base, opt = {}) {
    if (e.dead) return;
    const s = G.stats;
    let dmg = base * s.dmg * (G.buff && G.buff.id === 'fury' ? 1.5 : 1);
    SFX.hit();
    const crit = opt.noCrit ? false : Math.random() < s.critChance || (e.stun > 0 && G.sheng['土生金']);
    if (crit) dmg *= s.critMult;
    if (e.frozen > 0 && G.tier.water >= 3) dmg *= 1.5;
    if (e.d.boss && opt.bossCap) dmg = Math.min(dmg, opt.bossCap);
    e.hp -= dmg;
    e.flash = 0.08;
    addNumber(e.x + rand(-6, 6), e.y - e.r - 4, dmg, crit ? '#FFD98A' : opt.color || '#EDE6D6', crit ? 19 : 13);

    if (!opt.dot) {
      if (G.tier.fire >= 1) {
        e.burnT = 3;
        e.burnStacks = G.tier.fire >= 2 ? Math.min(5, e.burnStacks + 1) : 1;
        e.burnDps = Math.max(e.burnDps * 0.9, dmg * 0.2 * s.burnMult);
      }
      if (G.tier.water >= 1) {
        e.slow = Math.max(e.slow, 1);
        e.slowAmt = Math.max(e.slowAmt, 0.2);
      }
      if (crit && G.sheng['金生水']) {
        e.slow = Math.max(e.slow, 1.5);
        e.slowAmt = Math.max(e.slowAmt, 0.35);
      }
      if (G.tier.water >= 2 && Math.random() < 0.12 && !e.d.boss) e.frozen = 1;
      if (crit && G.tier.metal >= 3 && !opt.bonus && Math.random() < 0.5) {
        const ang = Math.atan2(e.y - G.player.y, e.x - G.player.x);
        fireSword(G.player.x, G.player.y, ang, 10 + G.level, 2, e, false, true);
      }
      if (opt.kb && opt.from && !e.d.boss) {
        const dx = e.x - opt.from.x;
        const dy = e.y - opt.from.y;
        const d = Math.hypot(dx, dy) || 1;
        const k = (opt.kb * s.kb) / (e.d.elite ? 3 : 1);
        e.kx += (dx / d) * k;
        e.ky += (dy / d) * k;
      }
    }
    if (e.hp <= 0) killEnemy(e);
  }

  function killEnemy(e) {
    if (e.dead) return;
    e.dead = true;
    SFX.kill();
    if (e.d.toad) {
      killToad(e);
      return;
    }
    G.kills++;
    G.comboT > 0 ? G.combo++ : (G.combo = 1);
    G.comboT = 2.2;
    if (G.combo > G.bestCombo) G.bestCombo = G.combo;
    if ([100, 300, 500, 1000].includes(G.combo)) {
      toast(`连斩 ${G.combo}`, '', '#FFD98A', G.combo >= 500);
      sfxFlash('#FFD98A', 0.08);
      SFX.combo();
    }
    G.ult = Math.min(1, G.ult + (e.d.elite ? 0.15 : 1 / 140));

    const m = G.t / 60;
    if (e.d.xp > 0) {
      const value = e.d.xp * (1 + 0.25 * m) * G.mods.xp;
      if (e.d.elite) {
        for (let i = 0; i < 8; i++) dropGem(e.x + rand(-20, 20), e.y + rand(-20, 20), value / 8);
      } else {
        dropGem(e.x, e.y, value);
      }
    }
    if (e.d.elite) {
      G.pickups.push({ kind: 'chest', x: e.x, y: e.y, t: 0 });
      G.pickups.push({ kind: 'bell', x: e.x + 24, y: e.y, t: 0 });
    } else if (Math.random() < 1 / 220) G.pickups.push({ kind: 'bell', x: e.x, y: e.y, t: 0 });
    else if (!G.mods.noHeal && Math.random() < 1 / 260) G.pickups.push({ kind: 'lotus', x: e.x, y: e.y, t: 0 });

    burst(e.x, e.y, e.d.rim, e.d.elite ? 22 : 6, e.d.elite ? 160 : 90);
    if (G.tier.wood >= 3 && !G.mods.noHeal) G.player.hp = Math.min(G.stats.maxHp, G.player.hp + 0.4);
    if (G.tier.fire >= 3) G.blasts.push({ x: e.x, y: e.y, r: 46, dmg: 8 + 4 * m, color: '#FF8A3D' });
    if (G.tier.water >= 3 && e.frozen > 0) G.blasts.push({ x: e.x, y: e.y, r: 52, dmg: 10 + 5 * m, color: '#6FB8FF' });

    if (e.d.boss) {
      G.boss = null;
      burst(e.x, e.y, '#FFD98A', 60, 260);
      G.slowT = 1.2;
      sfxFlash('#FFF1C2', 0.6);
      G.wonAt = G.t + 0.6; // 慢镜头之后进入结算
    }
  }

  // 金蟾：被打死时散落大量魂火与灯油
  function killToad(e) {
    const total = xpNeed(G.level) * 1.3;
    for (let i = 0; i < 24; i++) {
      const a = rand(0, TAU);
      const r = rand(10, 60);
      dropGem(e.x + Math.cos(a) * r, e.y + Math.sin(a) * r, total / 24);
    }
    G.oilBonus += 30;
    burst(e.x, e.y, '#FFD98A', 40, 220);
    sfxFlash('#FFD98A', 0.2);
    toast('金蟾 · 散财', '魂火满地，灯油 +30', '#FFD98A', true);
    SFX.coins();
  }

  function dropGem(x, y, value) {
    if (G.gems.length > 380) {
      // 魂火太多时并入最近的一颗，避免卡顿
      let near = G.gems[0];
      let nd = Infinity;
      for (const g of G.gems) {
        const d = (g.x - x) ** 2 + (g.y - y) ** 2;
        if (d < nd) {
          nd = d;
          near = g;
        }
      }
      near.v += value;
      return;
    }
    G.gems.push({ x, y, v: value, pulled: false, vx: 0, vy: 0, age: 0 });
  }

  function damagePlayer(amount) {
    const p = G.player;
    if (p.iframe > 0 || p.dashT > 0 || state !== 'play') return;
    const s = G.stats;
    let dmg = Math.max(1, amount * s.taken * (G.buff && G.buff.id === 'iron' ? 0.4 : 1) - s.armor);
    if (p.shield > 0) {
      const absorbed = Math.min(p.shield, dmg);
      p.shield -= absorbed;
      dmg -= absorbed;
      if (p.shield <= 0) {
        p.shieldT = s.shieldCd;
        if (G.tier.earth >= 3) quake();
      }
    }
    p.iframe = 0.5;
    if (dmg <= 0) return;
    p.hp -= dmg;
    SFX.hurt();
    G.shake = Math.max(G.shake, 5);
    G.flash = { color: '#FF3B30', a: 0.18 };
    addNumber(p.x, p.y - 18, dmg, '#FF6B5A', 15);
    if (p.hp <= 0) {
      p.hp = 0;
      endRun(false);
    }
  }

  function quake() {
    const p = G.player;
    G.effects.push({ kind: 'ring', x: p.x, y: p.y, r0: 20, r1: 150, t: 0, life: 0.5, color: '#C9925A', width: 6 });
    G.shake = Math.max(G.shake, 8);
    queryEnemies(p.x, p.y, 150, (e) => {
      hitEnemy(e, 30 + 6 * (G.t / 60), { kb: 120, from: p });
      e.stun = Math.max(e.stun, 0.8);
    });
  }

  // =====================================================================
  // 法器逻辑
  // =====================================================================
  function fireSword(x, y, ang, dmg, pierce, target, big, bonus) {
    const speed = 380;
    G.shots.push({ kind: 'sword', x, y, vx: Math.cos(ang) * speed, vy: Math.sin(ang) * speed, dmg, pierce, target, life: 1.5, hit: new Set(), big, bonus });
  }

  const WEAPON_UPDATE = {
    lamp(w) {
      const s = G.stats;
      const p = G.player;
      const base = W.lamp(w.lv);
      const count = (w.evo ? 10 : base.count) + s.amount;
      const radius = (w.evo ? 92 : base.radius) * s.area;
      const dmg = base.dmg * (w.evo ? 2.2 : 1);
      const size = (w.evo ? 12 : 10) * Math.sqrt(s.area);
      w.count = count;
      w.radius = radius;
      w.size = size;
      for (let i = 0; i < count; i++) {
        const a = w.angle + (i * TAU) / count;
        const x = p.x + Math.cos(a) * radius;
        const y = p.y + Math.sin(a) * radius;
        w.pos[i] = w.pos[i] || { x: 0, y: 0 };
        w.pos[i].x = x;
        w.pos[i].y = y;
        queryEnemies(x, y, size, (e) => {
          if (e.cdLamp > G.t) return;
          e.cdLamp = G.t + 0.45;
          hitEnemy(e, dmg, { kb: 50, from: p });
        });
      }
      w.pos.length = count;
    },

    sword(w, dt) {
      w.t -= dt;
      if (w.t > 0) return;
      const s = G.stats;
      const p = G.player;
      const base = W.sword(w.lv);
      const count = (w.evo ? 3 : base.count) + s.amount;
      const targets = nearestEnemies(p.x, p.y, 460, count);
      if (!targets.length) {
        w.t = 0.2;
        return;
      }
      w.t = (w.evo ? 0.42 : base.cd) * s.cd;
      for (let i = 0; i < count; i++) {
        const tgt = targets[i % targets.length];
        const ang = Math.atan2(tgt.y - p.y, tgt.x - p.x) + (i - (count - 1) / 2) * 0.14;
        fireSword(p.x, p.y, ang, base.dmg * (w.evo ? 1.6 : 1), w.evo ? 999 : base.pierce, tgt, w.evo, false);
      }
      SFX.sword();
    },

    bell(w, dt) {
      const s = G.stats;
      const p = G.player;
      const base = W.bell(w.lv);
      w.t -= dt;
      if (w.t <= 0) {
        w.t = base.cd * s.cd;
        const r = base.radius * s.area * (w.evo ? 1.3 : 1);
        G.effects.push({ kind: 'ring', x: p.x, y: p.y, r0: 12, r1: r, t: 0, life: 0.45, color: '#6FB8FF', width: 3 });
        SFX.bellPulse();
        queryEnemies(p.x, p.y, r, (e) => {
          hitEnemy(e, base.dmg * (w.evo ? 1.5 : 1), { kb: 40, from: p });
          e.slow = Math.max(e.slow, 1.5);
          e.slowAmt = Math.max(e.slowAmt, 0.35);
        });
      }
      if (w.evo) {
        w.big -= dt;
        if (w.big <= 0) {
          w.big = 6 * s.cd;
          G.effects.push({ kind: 'ring', x: p.x, y: p.y, r0: 20, r1: viewRadius(), t: 0, life: 0.7, color: '#A8D4FF', width: 8 });
          sfxFlash('#6FB8FF', 0.18);
          SFX.bigBell();
          for (const e of G.enemies) {
            if (e.dead || !onScreen(e)) continue;
            if (!e.d.boss) e.frozen = 1.5;
            hitEnemy(e, base.dmg * 3, { bossCap: 400 });
          }
        }
      }
    },

    crane(w, dt) {
      const s = G.stats;
      const p = G.player;
      const base = W.crane(w.lv);
      const n = (w.evo ? 10 : base.count) + s.amount;
      while (w.cranes.length < n) w.cranes.push({ x: p.x, y: p.y, vx: 0, vy: 0, state: 'rest', t: 0.2, target: null, ang: 0 });
      const speed = w.evo ? 330 : 250 + w.lv * 6;
      const dmg = base.dmg * (w.evo ? 1.5 : 1);
      w.cranes.forEach((c, i) => {
        c.t -= dt;
        let tx;
        let ty;
        if (c.state === 'rest') {
          const a = G.t * 2 + (i * TAU) / w.cranes.length;
          tx = p.x + Math.cos(a) * 34;
          ty = p.y + Math.sin(a) * 34;
          if (c.t <= 0) c.state = 'seek';
        } else {
          if (!c.target || c.target.dead || (c.target.x - p.x) ** 2 + (c.target.y - p.y) ** 2 > 340 * 340) {
            const near = nearestEnemies(c.x, c.y, 340, 3);
            c.target = near.length ? near[Math.floor(Math.random() * near.length)] : null;
          }
          if (!c.target) {
            c.state = 'rest';
            c.t = 0.3;
            return;
          }
          tx = c.target.x;
          ty = c.target.y;
          const d = Math.hypot(tx - c.x, ty - c.y);
          if (d < c.target.r + 6) {
            hitEnemy(c.target, dmg, { kb: 50, from: c });
            c.state = 'rest';
            c.t = w.evo ? 0.2 : 0.35;
          }
        }
        const dx = tx - c.x;
        const dy = ty - c.y;
        const d = Math.hypot(dx, dy) || 1;
        const k = Math.min(1, dt * 7);
        c.vx += ((dx / d) * speed - c.vx) * k;
        c.vy += ((dy / d) * speed - c.vy) * k;
        c.x += c.vx * dt;
        c.y += c.vy * dt;
        c.ang = Math.atan2(c.vy, c.vx);
      });
    },

    seal(w, dt) {
      w.t -= dt;
      if (w.t > 0) return;
      const s = G.stats;
      const p = G.player;
      const base = W.seal(w.lv);
      w.t = (w.evo ? 2.6 : base.cd) * s.cd;
      const count = base.count + (w.evo ? 1 : 0) + Math.floor(s.amount / 2);
      const radius = base.radius * s.area * (w.evo ? 2 : 1);
      const cands = nearestEnemies(p.x, p.y, 300, 12);
      for (let i = 0; i < count; i++) {
        let x;
        let y;
        if (cands.length) {
          const e = cands.splice(Math.floor(Math.random() * cands.length), 1)[0];
          x = e.x;
          y = e.y;
        } else {
          x = p.x + rand(-150, 150);
          y = p.y + rand(-100, 100);
        }
        G.effects.push({ kind: 'sealWarn', x, y, r: radius, t: -i * 0.12, life: 0.45, dmg: base.dmg * (w.evo ? 1.5 : 1), evo: w.evo });
      }
    },
  };

  // =====================================================================
  // 刷怪与事件
  // =====================================================================
  const hpScale = () => {
    const m = G.t / 60;
    return (1 + 0.3 * m + 0.07 * m * m) * G.mods.enemyHp;
  };

  function spawnEnemy(type, x, y) {
    const d = ENEMY[type];
    const sc = d.boss ? 1 : hpScale();
    const e = {
      type, d, x, y, r: d.r, hp: d.hp * sc, maxHp: d.hp * sc,
      speed: d.speed * rand(0.9, 1.1) * (d.toad ? 1 : G.mods.enemySpeed), dmg: d.dmg * (1 + 0.1 * (G.t / 60)),
      flash: 0, slow: 0, slowAmt: 0, frozen: 0, stun: 0, kx: 0, ky: 0,
      burnT: 0, burnStacks: 0, burnDps: 0, burnShow: 0, burnAcc: 0, cdLamp: 0,
      dead: false, wob: Math.random() * TAU, atk: 2, summon: 7,
    };
    G.enemies.push(e);
    return e;
  }

  function ringPos(extra = 40) {
    const p = G.player;
    const a = rand(0, TAU);
    const R = viewRadius() + extra;
    return { x: p.x + Math.cos(a) * R, y: p.y + Math.sin(a) * R };
  }

  function spawnElite(pool) {
    const type = pool[Math.floor(Math.random() * pool.length)];
    const info = ELITE_INFO[type];
    for (let i = 0; i < G.mods.elites; i++) {
      const pos = ringPos();
      spawnEnemy(type, pos.x, pos.y);
    }
    toast(G.mods.elites > 1 ? `${info.label} ×${G.mods.elites}` : info.label, '击败它获得宝箱', info.color);
    SFX.warn(false);
  }

  function updateSpawns(dt) {
    const m = G.t / 60;
    let rate = (1.6 + 1.1 * m + 0.1 * m * m) * G.mods.spawn;
    if (G.surgeT > 0) {
      G.surgeT -= dt;
      rate *= 2.5;
    }
    if (G.boss) rate *= 0.4;
    if (G.enemies.length > 360) rate = 0;
    G.spawnAcc += rate * dt;
    while (G.spawnAcc >= 1) {
      G.spawnAcc -= 1;
      const r = Math.random();
      let type = 'shade';
      if (m >= 1 && r < G.mix.wisp * (m >= 5 ? 1.5 : 1)) type = 'wisp';
      else if (m >= 2.5 && r > 1 - G.mix.golem * (m >= 5 ? 1.6 : 1)) type = 'golem';
      const pos = ringPos();
      spawnEnemy(type, pos.x, pos.y);
    }

    // 每 25 秒左右从随机方向涌来一群，制造“妖潮”的方向感
    if (G.t > 40 && G.t >= (G.nextPack || 40) && G.enemies.length < 300) {
      G.nextPack = G.t + rand(18, 32);
      const base = ringPos(60);
      const n = Math.round((8 + m * 3) * G.mods.spawn);
      for (let i = 0; i < n; i++) spawnEnemy(m > 4 && Math.random() < G.mix.wisp * 2 ? 'wisp' : 'shade', base.x + rand(-40, 40), base.y + rand(-40, 40));
    }

    // 按本局随机计划出场
    for (const step of G.plan) {
      if (step.done || G.t < step.at) continue;
      step.done = true;
      if (step.kind === 'elite') {
        spawnElite(step.pool);
      } else if (step.kind === 'surge') {
        G.surgeT = 30;
        spawnElite(['fox', 'ghoul', 'stonelord']);
        toast('妖潮来袭', '撑过这 30 秒', '#FF6B5A', true);
        G.shake = Math.max(G.shake, 6);
      } else if (step.kind === 'boss') {
        const pos = ringPos();
        G.boss = spawnEnemy('boss', pos.x, pos.y);
        toast('夜主 · 九尾 降临', '击败它，迎来天明', '#FFB46B', true);
        G.shake = Math.max(G.shake, 10);
        sfxFlash('#FF6B5A', 0.2);
        SFX.warn(true);
        if (AUDIO) AUDIO.setMusic('boss');
      }
    }

    // 夜签「天降宝箱」
    if (G.mods.chestRain) {
      G.chestRainT -= dt;
      if (G.chestRainT <= 0) {
        G.chestRainT = 100;
        const a = rand(0, TAU);
        G.pickups.push({ kind: 'chest', x: G.player.x + Math.cos(a) * 120, y: G.player.y + Math.sin(a) * 90, t: 0 });
        toast('天降宝箱', '就在附近', '#FFD98A');
        SFX.event();
      }
    }

    updateEvents(dt);
  }

  // =====================================================================
  // 奇遇
  // =====================================================================
  function pickEvent() {
    const kinds = Object.keys(EVENTS).filter((k) => !(k === 'spring' && G.mods.noHeal));
    const total = kinds.reduce((sum, k) => sum + EVENTS[k].weight, 0);
    let r = Math.random() * total;
    for (const k of kinds) {
      r -= EVENTS[k].weight;
      if (r <= 0) return k;
    }
    return kinds[0];
  }

  function spawnEvent(kind) {
    const p = G.player;
    const a = rand(0, TAU);
    const info = EVENTS[kind];
    const ev = { kind, t: 0, life: 30, used: false, x: 0, y: 0 };
    if (kind === 'toad') {
      const R = viewRadius() * 0.55;
      ev.ref = spawnEnemy('toad', p.x + Math.cos(a) * R, p.y + Math.sin(a) * R);
      ev.life = 20;
    } else if (kind === 'rift') {
      ev.x = p.x + Math.cos(a) * 280;
      ev.y = p.y + Math.sin(a) * 280;
      ev.life = 12;
      const m = G.t / 60;
      const n = 12 + Math.floor(m * 3);
      for (let i = 0; i < n; i++) {
        const b = rand(0, TAU);
        const r = rand(10, 70);
        spawnEnemy(Math.random() < 0.3 ? 'wisp' : 'shade', ev.x + Math.cos(b) * r, ev.y + Math.sin(b) * r);
      }
      const guard = ['fox', 'stonelord', 'ghoul'][Math.floor(Math.random() * (m > 4 ? 3 : 2))];
      ev.ref = spawnEnemy(guard, ev.x, ev.y);
    } else {
      ev.x = p.x + Math.cos(a) * 240;
      ev.y = p.y + Math.sin(a) * 240;
      ev.life = kind === 'spring' ? 25 : 35;
    }
    G.events.push(ev);
    toast(`奇遇 · ${info.name}`, info.hint, info.color);
    SFX.event();
  }

  function updateEvents(dt) {
    if (!G.boss && G.t >= G.nextEvent) {
      G.nextEvent = G.t + rand(40, 65) / G.mods.events;
      spawnEvent(pickEvent());
    }
    if (G.buff) {
      G.buff.t -= dt;
      if (G.buff.t <= 0) G.buff = null;
    }
    const p = G.player;
    const out = [];
    for (const ev of G.events) {
      ev.t += dt;
      if (ev.kind === 'toad') {
        if (ev.ref.dead) continue;
        if (ev.t >= ev.life) {
          ev.ref.dead = true;
          burst(ev.ref.x, ev.ref.y, '#FFD98A', 12, 80);
          toast('金蟾遁走了', '下次快一点', '#A9AEC2');
          continue;
        }
      } else if (ev.kind === 'rift') {
        if (ev.t >= ev.life) continue;
      } else {
        if (ev.used || ev.t >= ev.life) continue;
        const d2 = (ev.x - p.x) ** 2 + (ev.y - p.y) ** 2;
        if (ev.kind === 'spring') {
          if (d2 < 46 * 46 && p.hp < G.stats.maxHp) {
            const heal = G.stats.maxHp * 0.06 * dt;
            p.hp = Math.min(G.stats.maxHp, p.hp + heal);
            if (Math.random() < dt * 6) G.particles.push({ x: p.x + rand(-10, 10), y: p.y + 6, vx: 0, vy: -40, life: 0.5, max: 0.5, color: '#8FF0E0', size: 2 });
            SFX.heal();
          }
        } else if (d2 < 30 * 30) {
          ev.used = true;
          if (ev.kind === 'shrine') {
            const b = BUFFS[Math.floor(Math.random() * BUFFS.length)];
            G.buff = { ...b, t: 30 };
            toast(`古灯 · ${b.name}`, `${b.desc}，持续 30 秒`, b.color, true);
            sfxFlash(b.color, 0.2);
            SFX.resonance();
          } else if (ev.kind === 'altar') {
            const cost = Math.round(G.stats.maxHp * 0.25);
            p.hp = Math.max(1, p.hp - cost);
            addNumber(p.x, p.y - 20, cost, '#FF6B5A', 16);
            G.chestQueue.push({ n: 1, title: '血祭 · 以血换力' });
            sfxFlash('#FF3B30', 0.25);
            SFX.hurt();
          }
          continue;
        }
      }
      out.push(ev);
    }
    G.events = out;
  }

  // =====================================================================
  // 主更新
  // =====================================================================
  const input = { keys: new Set(), joy: null };

  function moveVector() {
    let x = 0;
    let y = 0;
    const k = input.keys;
    if (k.has('KeyA') || k.has('ArrowLeft')) x -= 1;
    if (k.has('KeyD') || k.has('ArrowRight')) x += 1;
    if (k.has('KeyW') || k.has('ArrowUp')) y -= 1;
    if (k.has('KeyS') || k.has('ArrowDown')) y += 1;
    if (input.joy) {
      const dx = input.joy.x - input.joy.ox;
      const dy = input.joy.y - input.joy.oy;
      const d = Math.hypot(dx, dy);
      if (d > 6) {
        const mag = Math.min(1, d / 44);
        x += (dx / d) * mag;
        y += (dy / d) * mag;
      }
    }
    const len = Math.hypot(x, y);
    if (len > 1) {
      x /= len;
      y /= len;
    }
    return { x, y };
  }

  function update(dt) {
    const p = G.player;
    const s = G.stats;
    G.t += dt;

    // 玩家移动
    const mv = moveVector();
    p.moving = mv.x !== 0 || mv.y !== 0;
    if (p.moving) {
      const len = Math.hypot(mv.x, mv.y);
      p.faceX = mv.x / len;
      p.faceY = mv.y / len;
    }
    if (p.dashT > 0) {
      p.dashT -= dt;
      p.x += p.dashVX * dt;
      p.y += p.dashVY * dt;
      if (Math.random() < 0.8) G.particles.push({ x: p.x, y: p.y, vx: 0, vy: 0, life: 0.25, max: 0.25, color: '#CFE3F5', size: 9, ghost: true });
    } else {
      const sp = s.speed * (G.buff && G.buff.id === 'swift' ? 1.4 : 1);
      p.x += mv.x * sp * dt;
      p.y += mv.y * sp * dt;
    }
    p.iframe = Math.max(0, p.iframe - dt);
    p.dashCd = Math.max(0, p.dashCd - dt);
    p.hp = Math.min(s.maxHp, p.hp + s.regen * dt);

    // 土·固：护盾
    if (G.tier.earth >= 1 && p.shield <= 0) {
      p.shieldT -= dt;
      if (p.shieldT <= 0) {
        p.shield = 20 + 5 * (G.t / 60);
        p.shieldMax = p.shield;
      }
    }

    // 太极
    if (G.taiji) {
      G.taijiT += dt;
      if (G.taijiT >= 30) {
        G.taijiT = 0;
        G.effects.push({ kind: 'taiji', x: p.x, y: p.y, t: 0, life: 1 });
        for (const e of G.enemies) if (!e.dead && onScreen(e)) hitEnemy(e, 40 * (1 + 0.4 * (G.t / 60)), { bossCap: 600 });
      }
    }

    const intensity = G.t < 180 ? 0 : G.t < 390 ? 1 : 2;
    if (intensity !== G.intensity) {
      G.intensity = intensity;
      if (AUDIO) AUDIO.setIntensity(intensity);
    }

    G.comboT -= dt;
    if (G.comboT <= 0) G.combo = 0;

    updateSpawns(dt);

    // 妖物
    buildGrid();
    for (const e of G.enemies) {
      if (e.dead) continue;
      e.flash = Math.max(0, e.flash - dt);
      e.wob += dt * 5;

      if (e.burnT > 0) {
        e.burnT -= dt;
        const dmg = e.burnDps * e.burnStacks * dt;
        e.hp -= dmg;
        e.burnAcc += dmg;
        e.burnShow -= dt;
        if (e.burnShow <= 0 && e.burnAcc >= 1) {
          addNumber(e.x + rand(-6, 6), e.y - e.r, e.burnAcc, '#FF9A55', 11);
          e.burnAcc = 0;
          e.burnShow = 0.5;
        }
        if (Math.random() < dt * 4) G.particles.push({ x: e.x + rand(-6, 6), y: e.y + rand(-6, 6), vx: 0, vy: -30, life: 0.4, max: 0.4, color: '#FF8A3D', size: 2.5 });
        if (e.hp <= 0) {
          killEnemy(e);
          continue;
        }
      } else {
        e.burnStacks = 0;
        e.burnDps = 0;
      }

      const dx = p.x - e.x;
      const dy = p.y - e.y;
      const d = Math.hypot(dx, dy) || 1;

      e.x += e.kx * dt;
      e.y += e.ky * dt;
      const decay = Math.exp(-8 * dt);
      e.kx *= decay;
      e.ky *= decay;

      if (e.frozen > 0) {
        e.frozen -= dt;
      } else if (e.stun > 0) {
        e.stun -= dt;
      } else {
        let sp = e.speed;
        if (e.slow > 0) {
          e.slow -= dt;
          sp *= 1 - e.slowAmt;
          if (e.slow <= 0) e.slowAmt = 0;
        }
        if (e.d.toad) {
          // 金蟾背着玩家逃，略慢于玩家，追得上
          const wob = Math.sin(G.t * 3 + e.wob) * 0.6;
          const ax = -dx / d;
          const ay = -dy / d;
          e.x += (ax * Math.cos(wob) - ay * Math.sin(wob)) * sp * dt;
          e.y += (ax * Math.sin(wob) + ay * Math.cos(wob)) * sp * dt;
        } else {
          e.x += (dx / d) * sp * dt;
          e.y += (dy / d) * sp * dt;
        }
      }

      if (e.d.boss) updateBoss(e, dt, dx / d, dy / d);

      // 离得太远的普通妖物绕到玩家前方
      if (!e.d.elite && !e.d.boss && !e.d.toad && d > viewRadius() * 1.7) {
        const a = Math.atan2(p.faceY, p.faceX) + rand(-0.8, 0.8);
        const R = viewRadius() + 40;
        e.x = p.x + Math.cos(a) * R;
        e.y = p.y + Math.sin(a) * R;
      }

      if (d < e.r + p.r && e.dmg > 0) damagePlayer(e.dmg);
    }

    // 妖物之间互相推开
    for (const e of G.enemies) {
      if (e.dead || e.d.boss) continue;
      const cx = Math.floor(e.x / CELL);
      const cy = Math.floor(e.y / CELL);
      for (let ix = cx - 1; ix <= cx + 1; ix++) {
        for (let iy = cy - 1; iy <= cy + 1; iy++) {
          const arr = grid.get(cellKey(ix, iy));
          if (!arr) continue;
          for (const o of arr) {
            if (o === e || o.dead) continue;
            const ox = e.x - o.x;
            const oy = e.y - o.y;
            const min = (e.r + o.r) * 0.85;
            const d2 = ox * ox + oy * oy;
            if (d2 < min * min && d2 > 0.01) {
              const dd = Math.sqrt(d2);
              const push = (min - dd) * 0.5 * Math.min(1, dt * 12);
              e.x += (ox / dd) * push;
              e.y += (oy / dd) * push;
            }
          }
        }
      }
    }

    // 法器
    for (const w of G.weapons) {
      if (w.id === 'lamp') {
        w.angle += (w.evo ? 2.4 : 3.2 + w.lv * 0.12) * dt;
      }
      WEAPON_UPDATE[w.id](w, dt);
    }

    updateShots(dt);
    updateFoes(dt);
    updateEffects(dt);
    updateZones(dt);

    // 连锁爆炸（本帧之前排队的）
    const blasts = G.blasts;
    G.blasts = [];
    if (blasts.length) SFX.blast();
    for (const b of blasts) {
      G.effects.push({ kind: 'blast', x: b.x, y: b.y, r: b.r, t: 0, life: 0.3, color: b.color });
      queryEnemies(b.x, b.y, b.r, (e) => hitEnemy(e, b.dmg, { noCrit: true, dot: true }));
    }

    updateGems(dt);
    updatePickups(dt);
    updateParticles(dt);

    G.enemies = G.enemies.filter((e) => !e.dead);
    G.shake = Math.max(0, G.shake - dt * 30);
    if (G.flash) {
      G.flash.a -= dt * 0.8;
      if (G.flash.a <= 0) G.flash = null;
    }
    if (G.edge) {
      G.edge.t -= dt;
      if (G.edge.t <= 0) G.edge = null;
    }

    if (G.wonAt && G.t >= G.wonAt && state === 'play') endRun(true);
    else if (G.pendingLevels > 0 && state === 'play') openLevelUp();
    else if (G.chestQueue.length && state === 'play') openChest();
  }

  function updateBoss(e, dt, ux, uy) {
    e.atk -= dt;
    if (e.atk <= 0) {
      e.atk = 2.6;
      const n = 14;
      const off = Math.random() * TAU;
      for (let i = 0; i < n; i++) {
        const a = off + (i * TAU) / n;
        G.foes.push({ x: e.x, y: e.y, vx: Math.cos(a) * 115, vy: Math.sin(a) * 115, r: 6, dmg: 14, life: 6 });
      }
    }
    e.summon -= dt;
    if (e.summon <= 0) {
      e.summon = 7;
      for (let i = 0; i < 6; i++) {
        const a = (i * TAU) / 6;
        spawnEnemy('shade', e.x + Math.cos(a) * 70, e.y + Math.sin(a) * 70);
      }
    }
    e.faceX = ux;
    e.faceY = uy;
  }

  function updateShots(dt) {
    const out = [];
    for (const sh of G.shots) {
      sh.life -= dt;
      if (sh.life <= 0) continue;
      if (sh.target && !sh.target.dead) {
        const want = Math.atan2(sh.target.y - sh.y, sh.target.x - sh.x);
        const cur = Math.atan2(sh.vy, sh.vx);
        let diff = want - cur;
        while (diff > Math.PI) diff -= TAU;
        while (diff < -Math.PI) diff += TAU;
        const turn = clamp(diff, -8 * dt, 8 * dt);
        const sp = Math.hypot(sh.vx, sh.vy);
        sh.vx = Math.cos(cur + turn) * sp;
        sh.vy = Math.sin(cur + turn) * sp;
      }
      sh.x += sh.vx * dt;
      sh.y += sh.vy * dt;
      let alive = true;
      queryEnemies(sh.x, sh.y, sh.big ? 9 : 6, (e) => {
        if (!alive || sh.hit.has(e)) return;
        sh.hit.add(e);
        hitEnemy(e, sh.dmg, { kb: 30, from: sh, bonus: sh.bonus, color: sh.bonus ? '#CFE3F5' : undefined });
        sh.pierce--;
        if (sh.pierce <= 0) alive = false;
        if (sh.target === e) sh.target = null;
      });
      if (alive) out.push(sh);
    }
    G.shots = out;
  }

  function updateFoes(dt) {
    const p = G.player;
    const out = [];
    for (const f of G.foes) {
      f.life -= dt;
      f.x += f.vx * dt;
      f.y += f.vy * dt;
      if ((f.x - p.x) ** 2 + (f.y - p.y) ** 2 < (f.r + p.r) ** 2) {
        damagePlayer(f.dmg);
        continue;
      }
      if (f.life > 0) out.push(f);
    }
    G.foes = out;
  }

  function updateEffects(dt) {
    const out = [];
    for (const fx of G.effects) {
      fx.t += dt;
      if (fx.kind === 'sealWarn' && fx.t >= fx.life) {
        sealImpact(fx);
        continue;
      }
      if (fx.t < fx.life) out.push(fx);
    }
    G.effects = out;
  }

  function sealImpact(fx) {
    G.effects.push({ kind: 'sealHit', x: fx.x, y: fx.y, r: fx.r, t: 0, life: 0.4, evo: fx.evo });
    G.shake = Math.max(G.shake, fx.evo ? 7 : 3);
    SFX.seal();
    burst(fx.x, fx.y, '#C9925A', fx.evo ? 18 : 8, 120);
    queryEnemies(fx.x, fx.y, fx.r, (e) => {
      hitEnemy(e, fx.dmg, { kb: 90, from: fx });
      e.stun = Math.max(e.stun, 0.5);
    });
    if (fx.evo) G.zones.push({ x: fx.x, y: fx.y, r: fx.r * 0.85, life: 2.5, max: 2.5, tick: 0, dmg: fx.dmg * 0.25 });
  }

  function updateZones(dt) {
    const out = [];
    for (const z of G.zones) {
      z.life -= dt;
      z.tick -= dt;
      if (z.tick <= 0) {
        z.tick = 0.5;
        queryEnemies(z.x, z.y, z.r, (e) => {
          hitEnemy(e, z.dmg, { dot: true, noCrit: true, color: '#E2B588' });
          e.slow = Math.max(e.slow, 0.6);
          e.slowAmt = Math.max(e.slowAmt, 0.4);
        });
      }
      if (z.life > 0) out.push(z);
    }
    G.zones = out;
  }

  function updateGems(dt) {
    const p = G.player;
    const mag = G.stats.magnet * (G.buff && G.buff.id === 'soul' ? 3 : 1);
    const mag2 = mag * mag;
    const out = [];
    for (const g of G.gems) {
      const dx = p.x - g.x;
      const dy = p.y - g.y;
      const d2 = dx * dx + dy * dy;
      g.age += dt;
      // 魂火归灯：落地 8 秒没被捡的魂火会自己飞向灯笼
      if (!g.pulled && (d2 < mag2 || g.age > 8)) g.pulled = true;
      if (g.pulled) {
        const d = Math.sqrt(d2) || 1;
        const sp = Math.min(520, Math.hypot(g.vx, g.vy) + 900 * dt);
        g.vx = (dx / d) * sp;
        g.vy = (dy / d) * sp;
        g.x += g.vx * dt;
        g.y += g.vy * dt;
        if (d < p.r + 8) {
          addXp(g.v);
          SFX.gem();
          continue;
        }
      }
      out.push(g);
    }
    G.gems = out;
  }

  function addXp(v) {
    G.xp += v;
    while (G.xp >= xpNeed(G.level)) {
      G.xp -= xpNeed(G.level);
      G.level++;
      G.pendingLevels++;
    }
  }

  function updatePickups(dt) {
    const p = G.player;
    const out = [];
    for (const k of G.pickups) {
      k.t += dt;
      const d2 = (k.x - p.x) ** 2 + (k.y - p.y) ** 2;
      if (d2 < (p.r + 16) ** 2) {
        if (k.kind === 'chest') {
          G.chestQueue.push({});
        } else if (k.kind === 'bell') {
          for (const g of G.gems) g.pulled = true;
          toast('引魂铃', '魂火尽归', '#5FD4C4');
          sfxFlash('#5FD4C4', 0.15);
          SFX.soulBell();
        } else if (k.kind === 'lotus') {
          const heal = G.stats.maxHp * 0.3;
          p.hp = Math.min(G.stats.maxHp, p.hp + heal);
          addNumber(p.x, p.y - 20, heal, '#6FD6A0', 15, '+');
          SFX.heal();
        }
        continue;
      }
      out.push(k);
    }
    G.pickups = out;
  }

  function updateParticles(dt) {
    const out = [];
    for (const pt of G.particles) {
      pt.life -= dt;
      if (pt.life <= 0) continue;
      pt.x += pt.vx * dt;
      pt.y += pt.vy * dt;
      pt.vx *= 0.92;
      pt.vy *= 0.92;
      out.push(pt);
    }
    G.particles = out;
    const nums = [];
    for (const n of G.numbers) {
      n.t += dt;
      if (n.t < n.life) nums.push(n);
    }
    G.numbers = nums;
  }

  function burst(x, y, color, n, speed) {
    if (G.particles.length > 420) return;
    for (let i = 0; i < n; i++) {
      const a = rand(0, TAU);
      const sp = rand(speed * 0.3, speed);
      G.particles.push({ x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: rand(0.25, 0.5), max: 0.5, color, size: rand(1.5, 3) });
    }
  }

  function addNumber(x, y, value, color, size, prefix = '') {
    if (G.numbers.length > 90 && size < 15) return;
    G.numbers.push({ x, y, text: prefix + Math.max(1, Math.round(value)), color, size, t: 0, life: 0.7 });
  }

  function sfxFlash(color, a) {
    G.flash = { color, a };
  }

  // =====================================================================
  // 主动技能：闪避与燃灯
  // =====================================================================
  function dash() {
    if (state !== 'play') return;
    const p = G.player;
    if (p.dashCd > 0) return;
    p.dashT = 0.16;
    p.dashVX = p.faceX * 720;
    p.dashVY = p.faceY * 720;
    p.iframe = Math.max(p.iframe, 0.3);
    p.dashCd = 2.4;
    SFX.dash();
  }

  function ultimate() {
    if (state !== 'play' || G.ult < 1) return;
    G.ult = 0;
    const p = G.player;
    G.effects.push({ kind: 'ring', x: p.x, y: p.y, r0: 20, r1: viewRadius() * 1.1, t: 0, life: 0.6, color: '#FFD98A', width: 10 });
    sfxFlash('#FFD98A', 0.55);
    SFX.ult();
    G.shake = 12;
    G.slowT = 0.35;
    const dmg = 120 * (1 + 0.4 * (G.t / 60));
    for (const e of G.enemies) {
      if (e.dead || !onScreen(e, 60)) continue;
      if (e.d.boss) hitEnemy(e, e.maxHp * 0.05, { noCrit: true });
      else hitEnemy(e, dmg, { kb: 160, from: p });
    }
    for (const f of G.foes) f.life = 0;
  }

  // =====================================================================
  // 升级三选一
  // =====================================================================
  function elOf(o) {
    if (o.type === 'evo' || o.type === 'wup' || o.type === 'wnew') return WEAPONS[o.id].el;
    if (o.type === 'pup' || o.type === 'pnew') return PASSIVES[o.id].el;
    return null;
  }

  function buildOptions() {
    const opts = [];
    for (const w of G.weapons) {
      if (!w.evo && w.lv >= WEAPON_MAX && plv(WEAPONS[w.id].evoPassive) > 0) opts.push({ type: 'evo', id: w.id, weight: 1000 });
    }
    for (const w of G.weapons) if (!w.evo && w.lv < WEAPON_MAX) opts.push({ type: 'wup', id: w.id, weight: 10 });
    if (G.weapons.length < SLOT_MAX) {
      for (const id of Object.keys(WEAPONS)) if (!getWeapon(id)) opts.push({ type: 'wnew', id, weight: G.t < 180 ? 9 : 5 });
    }
    for (const p of G.passives) if (p.lv < PASSIVE_MAX) opts.push({ type: 'pup', id: p.id, weight: 7 });
    if (G.passives.length < SLOT_MAX) {
      for (const id of Object.keys(PASSIVES)) if (!getPassive(id)) opts.push({ type: 'pnew', id, weight: 5 });
    }
    // 已投入的五行更容易出现，帮助玩家凑共鸣
    for (const o of opts) {
      if (o.type === 'evo') continue;
      const el = elOf(o);
      if (G.res[el] >= 2) o.weight *= 1.5;
      if (G.mods.favor) o.weight *= el === G.mods.favor ? 1.3 : 0.6;
    }
    return opts;
  }

  function pickWeighted(opts, n) {
    const pool = opts.slice();
    const out = [];
    while (out.length < n && pool.length) {
      const total = pool.reduce((s, o) => s + o.weight, 0);
      let r = Math.random() * total;
      let i = 0;
      for (; i < pool.length - 1; i++) {
        r -= pool[i].weight;
        if (r <= 0) break;
      }
      out.push(pool.splice(i, 1)[0]);
    }
    return out;
  }

  function rollChoices() {
    const opts = buildOptions();
    G.lingguang = false;
    if (!opts.length) return G.mods.noHeal ? [{ type: 'oil' }] : [{ type: 'heal' }, { type: 'oil' }];
    let n = G.mods.choices;
    // 灵光一闪：小概率四选一
    if (n === 3 && Math.random() < 0.1) {
      n = 4;
      G.lingguang = true;
    }
    return pickWeighted(opts, n);
  }

  function applyOption(o) {
    if (o.type === 'evo') {
      const w = getWeapon(o.id);
      w.evo = true;
      G.evolutions++;
      G.pendingEvos.push(o.id);
    } else if (o.type === 'wup') {
      getWeapon(o.id).lv++;
    } else if (o.type === 'wnew') {
      addWeapon(o.id);
    } else if (o.type === 'pup') {
      getPassive(o.id).lv++;
    } else if (o.type === 'pnew') {
      G.passives.push({ id: o.id, lv: 1 });
    } else if (o.type === 'heal') {
      G.player.hp = Math.min(G.stats.maxHp, G.player.hp + G.stats.maxHp * 0.3);
    } else if (o.type === 'oil') {
      G.oilBonus += 20;
    }
    computeStats(true);
    renderSlots();
  }

  function weaponUpgradeText(id, lv) {
    const a = W[id](lv);
    const b = W[id](lv + 1);
    const parts = [];
    for (const k of Object.keys(STAT_LABEL)) {
      if (!(k in a) || a[k] === b[k]) continue;
      if (k === 'cd') parts.push(`冷却 -${(a.cd - b.cd).toFixed(2)} 秒`);
      else parts.push(`${STAT_LABEL[k]} +${Math.round(b[k] - a[k])}`);
    }
    return `${parts.join('，')}。`;
  }

  function optionInfo(o) {
    if (o.type === 'heal') return { rarity: 'fan', rname: '凡品', kind: '补给', icon: '莲', color: '#6FD6A0', name: '莲子', desc: '回复 30% 生命。' };
    if (o.type === 'oil') return { rarity: 'fan', rname: '凡品', kind: '补给', icon: '油', color: '#FFD98A', name: '灯油', desc: '本局结算灯油 +20。' };
    const el = elOf(o);
    const color = EL[el].color;
    if (o.type === 'evo') {
      const def = WEAPONS[o.id];
      return { rarity: 'tian', rname: '天品', kind: '进化', icon: def.icon, color, name: def.evoName, desc: `${def.evoDesc}。` };
    }
    if (o.type === 'wnew' || o.type === 'wup') {
      const def = WEAPONS[o.id];
      const w = getWeapon(o.id);
      return o.type === 'wnew'
        ? { rarity: 'xuan', rname: '玄品', kind: '法器 · 新', icon: def.icon, color, name: def.name, desc: def.desc }
        : { rarity: 'ling', rname: '灵品', kind: `法器 · Lv${w.lv} → ${w.lv + 1}`, icon: def.icon, color, name: def.name, desc: weaponUpgradeText(o.id, w.lv) };
    }
    const def = PASSIVES[o.id];
    const p = getPassive(o.id);
    return o.type === 'pnew'
      ? { rarity: 'ling', rname: '灵品', kind: '心法 · 新', icon: def.name[0], color, name: def.name, desc: `${def.desc}。` }
      : { rarity: 'fan', rname: '凡品', kind: `心法 · Lv${p.lv} → ${p.lv + 1}`, icon: def.name[0], color, name: def.name, desc: `${def.desc}。` };
  }

  // 卡片底部提示：共鸣进度、相生、进化线索
  function optionNote(o) {
    if (o.type === 'heal' || o.type === 'oil') return null;
    if (o.type === 'evo') {
      const def = WEAPONS[o.id];
      return { color: '#FFD98A', title: '选择后立即进化', body: `${def.name} Lv8 + ${PASSIVES[def.evoPassive].name}` };
    }
    const el = elOf(o);
    const from = G.res[el];
    let gain = 0;
    if (o.type === 'wnew' || o.type === 'pnew') gain = 1;
    else if (o.type === 'wup') gain = getWeapon(o.id).lv + 1 >= WEAPON_MAX ? 1 : 0;
    else if (o.type === 'pup') gain = getPassive(o.id).lv + 1 >= PASSIVE_MAX ? 1 : 0;
    const to = from + gain;
    const e = EL[el];
    if (tierOf(to) > tierOf(from)) {
      const t = tierOf(to);
      let body = e.tiers[t - 1];
      if (t === 1) {
        const sh = SHENG.find((s) => (s.a === el && G.tier[s.b] >= 1) || (s.b === el && G.tier[s.a] >= 1));
        if (sh) body += `，并点亮「${sh.name}」`;
      }
      return { color: e.color, title: `${e.name} ${from} → ${to} · 共鸣${t === 3 ? '达成' : '激活'}`, body };
    }
    // 进化线索
    if (o.type === 'wnew' || o.type === 'wup') {
      const def = WEAPONS[o.id];
      const lvAfter = o.type === 'wnew' ? 1 : getWeapon(o.id).lv + 1;
      if (lvAfter >= WEAPON_MAX && plv(def.evoPassive) > 0) return { color: '#FFD98A', title: '满级 · 下次升级可进化', body: `→ ${def.evoName}` };
      return { color: null, title: `${e.name} ${from}${gain ? ` → ${to}` : ''}`, body: `进化需心法「${PASSIVES[def.evoPassive].name}」` };
    }
    const wid = Object.keys(WEAPONS).find((id) => WEAPONS[id].evoPassive === o.id);
    if (wid && getWeapon(wid)) {
      const w = getWeapon(wid);
      if (!w.evo) {
        return w.lv >= WEAPON_MAX
          ? { color: '#FFD98A', title: '可进化', body: `${WEAPONS[wid].name} → ${WEAPONS[wid].evoName}` }
          : { color: null, title: `${e.name} ${from}${gain ? ` → ${to}` : ''}`, body: `${WEAPONS[wid].name} 满级后可进化` };
      }
    }
    return { color: null, title: `${e.name} ${from}${gain ? ` → ${to}` : ''}`, body: '' };
  }

  let currentChoices = [];

  function openLevelUp() {
    setState('levelup');
    G.pendingLevels--;
    currentChoices = rollChoices();
    const how = G.lingguang ? '灵光一闪 · 四选一' : currentChoices.length === 2 ? '二选一' : '三选一';
    $('levelup-sub').textContent = `Lv ${G.level - G.pendingLevels - 1} → ${G.level - G.pendingLevels} · ${how}`;
    renderCards();
    SFX.levelUp();
  }

  function renderCards() {
    const wrap = $('cards');
    wrap.innerHTML = '';
    currentChoices.forEach((o, i) => {
      const info = optionInfo(o);
      const note = optionNote(o);
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `card ${info.rarity}`;
      btn.style.setProperty('--rc', `var(--r-${info.rarity})`);
      btn.style.setProperty('--c', info.color);
      btn.innerHTML = `
        <div class="card-top"><span class="rarity">${info.rname}</span><span class="card-kind">${info.kind}</span></div>
        <div class="card-head"><div class="card-icon">${info.icon}</div><div class="card-name">${info.name}</div></div>
        <div class="card-desc">${info.desc}</div>
        ${note ? `<div class="card-note" ${note.color ? `style="--nc:${note.color}"` : ''}><b>${note.title}</b>${note.body}</div>` : ''}
        <div class="card-el">${o.type === 'heal' || o.type === 'oil' ? '' : `${EL[elOf(o)].name} 属性`}</div>`;
      btn.addEventListener('click', () => chooseOption(i));
      wrap.appendChild(btn);
    });
    renderResChips($('levelup-res'));
    const rr = $('reroll-btn');
    rr.textContent = `重抽 ×${G.rerolls}`;
    rr.disabled = G.rerolls <= 0;
    $('skip-btn').textContent = '跳过 +10 灯油';
    const first = wrap.querySelector('button');
    if (first && !coarse) first.focus({ preventScroll: true });
  }

  function chooseOption(i) {
    if (state !== 'levelup') return;
    SFX.select();
    applyOption(currentChoices[i]);
    afterChoice();
  }

  function afterChoice() {
    if (G.pendingEvos.length) showEvolution(G.pendingEvos.shift());
    else if (G.pendingLevels > 0) openLevelUp();
    else if (G.chestQueue.length) openChest();
    else setState('play');
  }

  // =====================================================================
  // 宝箱
  // =====================================================================
  function openChest() {
    const q = G.chestQueue.shift();
    setState('chest');
    const r = Math.random() + meta.luck * 0.03;
    const n = q.n || Math.max(G.mods.chestMin, r > 0.93 ? 5 : r > 0.68 ? 3 : 1);
    $('chest-title').textContent = q.title || (n === 5 ? '五连 · 天降鸿运' : n === 3 ? '三连宝箱' : '宝箱');
    SFX.chest(n);
    const wrap = $('chest-items');
    wrap.innerHTML = '';
    for (let i = 0; i < n; i++) {
      const opts = buildOptions().filter((o) => o.type !== 'wnew' && o.type !== 'pnew');
      const pool = opts.length ? opts : buildOptions();
      const o = pool.length ? pickWeighted(pool, 1)[0] : { type: 'oil' };
      const info = optionInfo(o);
      applyOption(o);
      const div = document.createElement('div');
      div.className = 'chest-item';
      div.style.setProperty('--rc', `var(--r-${info.rarity})`);
      div.style.setProperty('--c', info.color);
      div.style.animationDelay = `${0.15 + i * 0.28}s`;
      div.innerHTML = `<div class="card-icon">${info.icon}</div><div class="name">${info.name}</div><div class="what">${info.kind}</div>`;
      wrap.appendChild(div);
    }
    const ok = $('chest-ok');
    ok.disabled = true;
    setTimeout(() => {
      ok.disabled = false;
      if (!coarse) ok.focus({ preventScroll: true });
    }, 250 + n * 280);
  }

  // =====================================================================
  // 进化演出
  // =====================================================================
  function showEvolution(id) {
    const def = WEAPONS[id];
    setState('evo');
    $('evo-name').textContent = def.evoName;
    $('evo-recipe').textContent = `${def.name} Lv8 ＋ ${PASSIVES[def.evoPassive].name} → ${EL[def.el].name} · 天品法器`;
    $('evo-desc').textContent = def.evoDesc;
    evoTimer = 2.1;
    SFX.evolution();
    G.edge = { color: '#FFD98A', t: 1.5 };
  }

  // =====================================================================
  // 结算与局外
  // =====================================================================
  function endRun(won) {
    if (state === 'over') return;
    const survived = Math.min(G.t, RUN_LENGTH + 120);
    const parts = {
      time: Math.floor(survived),
      kills: Math.floor(G.kills * 0.1),
      boss: won ? 300 : 0,
      bonus: G.oilBonus,
    };
    const total = Math.round((parts.time + parts.kills + parts.boss + parts.bonus) * G.mods.oil);
    if (AUDIO) AUDIO.setMusic('none');
    won ? SFX.victory() : SFX.defeat();
    oil += total;
    save(STORE_OIL, oil);

    const newRecord = won && !best.won ? '首次天明' : G.kills > best.kills ? '新纪录 · 单局击杀' : survived > best.time && !won ? '新纪录 · 存活时间' : '';
    best = { time: Math.max(best.time, survived), kills: Math.max(best.kills, G.kills), won: best.won || won };
    save(STORE_BEST, best);

    const title = $('result-title');
    title.textContent = won ? '天明' : '灯灭';
    title.classList.toggle('lost', !won);
    $('result-sub').innerHTML = `${won
      ? `存活 ${fmtTime(survived)} · 击败夜主「九尾」`
      : `倒在第 ${fmtTime(survived)}<br>离天明还有 ${fmtTime(Math.max(0, RUN_LENGTH - survived))}`}<br>夜签「${G.omen.name}」`;
    const rec = $('result-record');
    rec.hidden = !newRecord;
    rec.textContent = newRecord;

    $('result-stats').innerHTML = [
      ['击杀', fmtNum(G.kills)],
      ['等级', G.level],
      ['最高连斩', fmtNum(G.bestCombo)],
      ['进化', G.evolutions],
    ].map(([k, v]) => `<div class="stat-box"><span>${k}</span><b>${v}</b></div>`).join('');

    const tiles = G.weapons.map((w) => {
      const def = WEAPONS[w.id];
      return w.evo
        ? `<div class="build-tile evo" style="--c:${EL[def.el].color}"><i>${def.icon}</i>${def.evoName}<small>进化</small></div>`
        : `<div class="build-tile" style="--c:${EL[def.el].color}"><i>${def.icon}</i>${def.name}<small>Lv${w.lv}</small></div>`;
    });
    $('result-build').innerHTML = tiles.join('');
    renderResChips($('result-res'), true);

    $('result-oil').textContent = `+${fmtNum(total)} 灯油`;
    $('result-oil-detail').textContent = `存活 ${parts.time} · 击杀 ${parts.kills}${parts.boss ? ` · 夜主 ${parts.boss}` : ''}${parts.bonus ? ` · 额外 ${parts.bonus}` : ''}`;
    renderNextUnlock();

    setState('over');
  }

  // 结算时展示离下一盏心灯最近的进度，制造“只差一点”
  function renderNextUnlock() {
    const items = META.filter((m) => meta[m.id] < META_MAX)
      .map((m) => ({ m, cost: metaCost(meta[m.id]) }))
      .sort((a, b) => a.cost - b.cost);
    const wrap = $('result-next');
    if (!items.length) {
      wrap.innerHTML = '<div class="muted">心灯已全部点亮</div>';
      return;
    }
    const ready = items.filter((i) => i.cost <= oil).length;
    const next = items[0];
    const pct = clamp(oil / next.cost, 0, 1) * 100;
    wrap.innerHTML = `
      <div class="row"><span>点亮「${next.m.name}」Lv${meta[next.m.id] + 1}</span>${next.cost <= oil ? '<b>可点亮</b>' : `<b>只差 ${fmtNum(next.cost - oil)}</b>`}</div>
      <div class="bar"><div style="width:${pct}%"></div></div>
      <div class="muted">当前灯油 ${fmtNum(oil)}${ready > 1 ? ` · 可点亮 ${ready} 项` : ''}</div>`;
  }

  function renderMeta() {
    $('meta-oil').textContent = `灯油 ${fmtNum(oil)}`;
    const wrap = $('meta-list');
    wrap.innerHTML = '';
    for (const m of META) {
      const lv = meta[m.id];
      const maxed = lv >= META_MAX;
      const cost = metaCost(lv);
      const card = document.createElement('div');
      card.className = 'meta-card';
      card.innerHTML = `
        <div class="head"><div class="node ${lv ? '' : 'off'}">${m.icon}</div><div><div class="name">${m.name}</div><div class="muted small-text">Lv ${lv} / ${META_MAX}</div></div></div>
        <div class="pips">${Array.from({ length: META_MAX }, (_, i) => `<span class="${i < lv ? 'on' : ''}"></span>`).join('')}</div>
        <div class="desc">${m.per}</div>`;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn primary';
      btn.textContent = maxed ? '已满' : `点亮 · ${fmtNum(cost)}`;
      btn.disabled = maxed || oil < cost;
      btn.addEventListener('click', () => {
        if (oil < cost || maxed) return;
        oil -= cost;
        meta[m.id]++;
        save(STORE_OIL, oil);
        save(STORE_META, meta);
        renderMeta();
      });
      card.appendChild(btn);
      wrap.appendChild(card);
    }
  }

  function renderTitleInfo() {
    const parts = [`灯油 ${fmtNum(oil)}`];
    if (best.time > 0) parts.push(best.won ? '已见天明' : `最久存活 ${fmtTime(best.time)}`);
    if (best.kills > 0) parts.push(`最多击杀 ${fmtNum(best.kills)}`);
    $('title-info').textContent = parts.join(' · ');
  }

  // =====================================================================
  // 界面状态切换
  // =====================================================================
  const SCREENS = {
    title: 'title-screen',
    omen: 'omen-screen',
    levelup: 'levelup-screen',
    chest: 'chest-screen',
    evo: 'evo-screen',
    paused: 'pause-screen',
    over: 'result-screen',
    meta: 'meta-screen',
  };

  function setState(next) {
    state = next;
    for (const [k, id] of Object.entries(SCREENS)) $(id).hidden = k !== next;
    $('hud').hidden = !G || next === 'title' || next === 'over' || next === 'meta' || next === 'omen';
    $('hud').classList.toggle('inactive', next !== 'play');
    if (next !== 'play') {
      input.joy = null;
      $('joystick').hidden = true;
    }
    if (AUDIO) {
      AUDIO.muffle(next !== 'play' && next !== 'title' && next !== 'omen' && next !== 'over');
      if (next === 'title' || next === 'omen') AUDIO.setMusic('title');
    }
    if (next === 'title') renderTitleInfo();
    if (next === 'meta') renderMeta();
    if (next === 'title' || next === 'paused') syncAudioButtons();
  }

  // 出发：先抽夜签
  function startRun() {
    if (AUDIO) AUDIO.init();
    tryFullscreen();
    const omens = drawOmens();
    const wrap = $('omen-cards');
    wrap.innerHTML = '';
    omens.forEach((o) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'card omen';
      btn.innerHTML = `
        <div class="omen-name brush">${o.name}</div>
        <div class="omen-line good">＋ ${o.good}</div>
        <div class="omen-line bad">－ ${o.bad}</div>`;
      btn.addEventListener('click', () => beginRun(o));
      wrap.appendChild(btn);
    });
    setState('omen');
    SFX.event();
  }

  function beginRun(omen) {
    if (state !== 'omen') return;
    SFX.select();
    newRun(omen);
    if (AUDIO) {
      AUDIO.setMusic('play', G.seed);
      AUDIO.setIntensity(0);
    }
    setState('play');
    toast(`夜签 · ${omen.name}`, `${omen.good}；${omen.bad}`, '#FFD98A');
  }

  function pauseGame() {
    if (state !== 'play') return;
    renderPauseBuild();
    setState('paused');
  }

  function renderPauseBuild() {
    const wrap = $('pause-build');
    const ws = G.weapons.map((w) => (w.evo ? WEAPONS[w.id].evoName : `${WEAPONS[w.id].name} Lv${w.lv}`)).join(' · ');
    const ps = G.passives.map((p) => `${PASSIVES[p.id].name} Lv${p.lv}`).join(' · ') || '暂无心法';
    wrap.innerHTML = `<div class="muted small-text">${ws}</div><div class="muted small-text">${ps}</div><div class="res-chips"></div>`;
    renderResChips(wrap.querySelector('.res-chips'));
  }

  function tryFullscreen() {
    if (!coarse) return;
    const el = document.documentElement;
    if (document.fullscreenElement || !el.requestFullscreen) return;
    el.requestFullscreen({ navigationUI: 'hide' })
      .then(() => screen.orientation && screen.orientation.lock && screen.orientation.lock('landscape'))
      .catch(() => {});
  }

  // =====================================================================
  // HUD
  // =====================================================================
  let hudCache = {};
  function setText(id, value) {
    if (hudCache[id] === value) return;
    hudCache[id] = value;
    $(id).textContent = value;
  }
  function setWidth(id, pct) {
    const v = `${pct.toFixed(1)}%`;
    if (hudCache[id] === v) return;
    hudCache[id] = v;
    $(id).style.width = v;
  }

  function updateHud() {
    const p = G.player;
    const s = G.stats;
    setWidth('xp-fill', (G.xp / xpNeed(G.level)) * 100);
    setText('level', String(G.level));
    setText('hp-text', `${Math.ceil(p.hp)} / ${s.maxHp}`);
    setWidth('hp-fill', (p.hp / s.maxHp) * 100);
    setWidth('shield-fill', p.shield > 0 ? (p.shield / (p.shieldMax || 1)) * 100 : 0);
    setText('timer', fmtTime(G.t));
    const phase = G.boss ? '决战' : G.t < 180 ? '生存期' : G.t < 390 ? '构筑期' : G.t < RUN_LENGTH ? '割草期' : '长夜';
    setText('phase', `${phase} · ${G.omen.name}`);
    const buff = $('buff-chip');
    if (G.buff) {
      buff.hidden = false;
      buff.style.setProperty('--c', G.buff.color);
      setText('buff-chip', `${G.buff.name} ${Math.ceil(G.buff.t)}s · ${G.buff.desc}`);
    } else if (!buff.hidden) {
      buff.hidden = true;
    }
    setText('kills', fmtNum(G.kills));

    const combo = $('combo');
    if (G.combo >= 10) {
      const v = String(G.combo);
      if (hudCache.combo !== v) {
        hudCache.combo = v;
        combo.hidden = false;
        combo.innerHTML = `<small>连斩</small>${v}`;
        if (G.combo % 50 === 0) {
          combo.classList.remove('pop');
          void combo.offsetWidth;
          combo.classList.add('pop');
        }
      }
    } else if (hudCache.combo !== '') {
      hudCache.combo = '';
      combo.hidden = true;
    }

    const ult = $('ult-btn');
    const charge = G.ult.toFixed(3);
    if (hudCache.ult !== charge) {
      hudCache.ult = charge;
      ult.style.setProperty('--charge', charge);
      ult.classList.toggle('ready', G.ult >= 1);
    }
    const cooling = p.dashCd > 0;
    if (hudCache.dash !== cooling) {
      hudCache.dash = cooling;
      $('dash-btn').classList.toggle('cooling', cooling);
    }

    const bossBar = $('boss-bar');
    if (G.boss && !G.boss.dead) {
      bossBar.hidden = false;
      setWidth('boss-fill', (G.boss.hp / G.boss.maxHp) * 100);
    } else {
      bossBar.hidden = true;
    }

    const resKey = EL_ORDER.map((el) => G.res[el]).join(',');
    if (hudCache.res !== resKey) {
      hudCache.res = resKey;
      renderResChips($('res-chips'));
    }
  }

  // onlyOwned：结算页只列出有投入的五行，激活的共鸣写出名字
  function renderResChips(wrap, onlyOwned) {
    wrap.innerHTML = EL_ORDER.filter((el) => !onlyOwned || G.res[el] > 0)
      .map((el) => {
        const n = G.res[el];
        const on = G.tier[el] >= 1;
        const cls = on ? 'on' : n === 0 ? 'zero' : '';
        const label = onlyOwned && on ? `${EL[el].name}·${EL[el].res}` : EL[el].name;
        return `<span class="res-chip ${cls}" style="--c:${EL[el].color}"><b>${label}</b>${n}</span>`;
      })
      .join('');
  }

  function renderSlots() {
    const ws = $('weapon-slots');
    const ps = $('passive-slots');
    let html = '';
    for (let i = 0; i < SLOT_MAX; i++) {
      const w = G.weapons[i];
      if (!w) {
        html += '<div class="slot empty"></div>';
        continue;
      }
      const def = WEAPONS[w.id];
      html += `<div class="slot ${w.evo ? 'evo' : ''}" style="--c:${EL[def.el].color}">${def.icon}<span class="lv">${w.evo ? '' : w.lv}</span></div>`;
    }
    ws.innerHTML = html;
    html = '';
    for (let i = 0; i < SLOT_MAX; i++) {
      const p = G.passives[i];
      html += p
        ? `<div class="slot" style="--c:${EL[PASSIVES[p.id].el].color}">${PASSIVES[p.id].name[0]}</div>`
        : '<div class="slot empty"></div>';
    }
    ps.innerHTML = html;
  }

  function toast(title, body, color, big) {
    const wrap = $('toasts');
    const div = document.createElement('div');
    div.className = `toast${big ? ' big' : ''}`;
    div.style.setProperty('--c', color);
    div.innerHTML = `<b>${title}</b>${body}`;
    wrap.appendChild(div);
    while (wrap.children.length > 3) wrap.firstChild.remove();
    setTimeout(() => div.remove(), 2500);
  }

  // =====================================================================
  // 绘制
  // =====================================================================
  function drawGround(left, top, right, bottom) {
    ctx.fillStyle = '#0B0F1C';
    ctx.fillRect(left, top, right - left, bottom - top);
    const C = 160;
    const cx0 = Math.floor(left / C) - 1;
    const cx1 = Math.floor(right / C) + 1;
    const cy0 = Math.floor(top / C) - 1;
    const cy1 = Math.floor(bottom / C) + 1;
    for (let cx = cx0; cx <= cx1; cx++) {
      for (let cy = cy0; cy <= cy1; cy++) {
        const r = seeded(hash2(cx + mapSeed.x, cy + mapSeed.y));
        const bx = cx * C;
        const by = cy * C;
        if (r() < 0.55) {
          ctx.fillStyle = r() < 0.5 ? '#0F1626' : '#101727';
          ctx.beginPath();
          ctx.ellipse(bx + r() * C, by + r() * C, 30 + r() * 40, 18 + r() * 26, r() * Math.PI, 0, TAU);
          ctx.fill();
        }
        if (r() < 0.35) {
          ctx.fillStyle = '#19213A';
          ctx.strokeStyle = '#26304C';
          ctx.lineWidth = 1;
          let x = bx + r() * C;
          let y = by + r() * C;
          const ang = r() * Math.PI;
          const n = 2 + Math.floor(r() * 3);
          for (let i = 0; i < n; i++) {
            ctx.save();
            ctx.translate(x, y);
            ctx.rotate(ang + (r() - 0.5) * 0.4);
            ctx.beginPath();
            ctx.roundRect(-13, -8, 26, 16, 5);
            ctx.fill();
            ctx.stroke();
            ctx.restore();
            x += Math.cos(ang) * 34;
            y += Math.sin(ang) * 34;
          }
        }
        const tufts = Math.floor(r() * 3);
        ctx.strokeStyle = '#2B3A4A';
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        for (let i = 0; i < tufts; i++) {
          const x = bx + r() * C;
          const y = by + r() * C;
          ctx.moveTo(x, y);
          ctx.lineTo(x + 1, y - 7);
          ctx.moveTo(x + 3, y);
          ctx.lineTo(x + 6, y - 6);
          ctx.moveTo(x - 3, y);
          ctx.lineTo(x - 5, y - 6);
        }
        ctx.stroke();
        if (r() < 0.3) {
          ctx.fillStyle = '#1A2236';
          ctx.beginPath();
          ctx.arc(bx + r() * C, by + r() * C, 2 + r() * 3, 0, TAU);
          ctx.fill();
        }
        if (r() < 0.05) {
          const x = bx + C / 2;
          const y = by + C / 2;
          ctx.fillStyle = '#1E2538';
          ctx.strokeStyle = '#2F3954';
          ctx.beginPath();
          ctx.roundRect(x - 11, y - 11, 22, 22, 3);
          ctx.fill();
          ctx.stroke();
          ctx.save();
          ctx.translate(x, y);
          ctx.rotate(Math.PI / 4);
          ctx.fillStyle = '#262F47';
          ctx.fillRect(-8, -8, 16, 16);
          ctx.restore();
          ctx.fillStyle = 'rgba(255, 217, 138, 0.5)';
          ctx.beginPath();
          ctx.arc(x, y, 3, 0, TAU);
          ctx.fill();
        }
      }
    }
  }

  // 奇遇：地面部分（在黑夜遮罩之下）
  function drawEventsGround() {
    for (const ev of G.events) {
      if (ev.kind === 'toad') continue;
      const fade = clamp((ev.life - ev.t) / 3, 0, 1);
      ctx.globalAlpha = fade;
      if (ev.kind === 'spring') {
        ctx.fillStyle = 'rgba(95, 212, 196, 0.22)';
        ctx.strokeStyle = 'rgba(143, 240, 224, 0.6)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.ellipse(ev.x, ev.y, 46, 32, 0, 0, TAU);
        ctx.fill();
        ctx.stroke();
        const rip = (demo.t * 0.8) % 1;
        ctx.globalAlpha = fade * (1 - rip);
        ctx.beginPath();
        ctx.ellipse(ev.x, ev.y, 46 * rip, 32 * rip, 0, 0, TAU);
        ctx.stroke();
      } else if (ev.kind === 'shrine') {
        ctx.fillStyle = '#262F47';
        ctx.strokeStyle = '#3A4466';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(ev.x - 16, ev.y - 16, 32, 32, 4);
        ctx.fill();
        ctx.stroke();
        ctx.save();
        ctx.translate(ev.x, ev.y);
        ctx.rotate(Math.PI / 4);
        ctx.fillStyle = '#313B58';
        ctx.fillRect(-12, -12, 24, 24);
        ctx.restore();
      } else if (ev.kind === 'altar') {
        ctx.fillStyle = '#2A1620';
        ctx.strokeStyle = '#5A2A30';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(ev.x - 20, ev.y - 14, 40, 28, 4);
        ctx.fill();
        ctx.stroke();
      } else if (ev.kind === 'rift') {
        ctx.strokeStyle = '#3A2460';
        ctx.lineWidth = 5;
        ctx.beginPath();
        ctx.moveTo(ev.x - 50, ev.y - 10);
        ctx.lineTo(ev.x - 18, ev.y + 6);
        ctx.lineTo(ev.x + 6, ev.y - 8);
        ctx.lineTo(ev.x + 30, ev.y + 10);
        ctx.lineTo(ev.x + 52, ev.y - 4);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
  }

  // 奇遇：发光部分（在黑夜遮罩之上，远处也看得见）
  function drawEventsGlow() {
    for (const ev of G.events) {
      if (ev.kind === 'toad') continue;
      const fade = clamp((ev.life - ev.t) / 3, 0, 1);
      const pulse = 0.75 + Math.sin(demo.t * 4) * 0.25;
      const color = EVENTS[ev.kind].color;
      ctx.globalAlpha = fade * 0.22 * pulse;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(ev.x, ev.y, 34, 0, TAU);
      ctx.fill();
      ctx.globalAlpha = fade;
      if (ev.kind === 'shrine') {
        drawFlame(ev.x, ev.y - 2, 8, fade);
      } else if (ev.kind === 'altar') {
        ctx.strokeStyle = '#FF6B5A';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(ev.x, ev.y, 9 + pulse * 2, 0, TAU);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(ev.x, ev.y - 7);
        ctx.lineTo(ev.x, ev.y + 7);
        ctx.moveTo(ev.x - 6, ev.y);
        ctx.lineTo(ev.x + 6, ev.y);
        ctx.stroke();
      } else if (ev.kind === 'rift') {
        ctx.strokeStyle = '#C9A0FF';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(ev.x - 50, ev.y - 10);
        ctx.lineTo(ev.x - 18, ev.y + 6);
        ctx.lineTo(ev.x + 6, ev.y - 8);
        ctx.lineTo(ev.x + 30, ev.y + 10);
        ctx.lineTo(ev.x + 52, ev.y - 4);
        ctx.stroke();
      } else if (ev.kind === 'spring') {
        ctx.fillStyle = '#8FF0E0';
        for (let i = 0; i < 3; i++) {
          const a = demo.t * 1.5 + (i * TAU) / 3;
          ctx.beginPath();
          ctx.arc(ev.x + Math.cos(a) * 24, ev.y + Math.sin(a) * 16, 1.6, 0, TAU);
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
    }
  }

  // 屏幕外的奇遇：在屏幕边缘画指引
  function drawEventArrows(camX, camY, k) {
    const W2 = canvas.width / 2;
    const H2 = canvas.height / 2;
    const inset = 30 * view.dpr;
    for (const ev of G.events) {
      const tx = ev.kind === 'toad' ? ev.ref.x : ev.x;
      const ty = ev.kind === 'toad' ? ev.ref.y : ev.y;
      const dx = (tx - camX) * k;
      const dy = (ty - camY) * k;
      if (Math.abs(dx) < W2 - inset && Math.abs(dy) < H2 - inset) continue;
      const t = Math.min((W2 - inset) / Math.abs(dx || 1e-6), (H2 - inset - 20 * view.dpr) / Math.abs(dy || 1e-6));
      const x = W2 + dx * t;
      const y = H2 + dy * t;
      const a = Math.atan2(dy, dx);
      const info = EVENTS[ev.kind];
      const r = 13 * view.dpr;
      ctx.fillStyle = info.color;
      ctx.beginPath();
      ctx.moveTo(x + Math.cos(a) * (r + 8 * view.dpr), y + Math.sin(a) * (r + 8 * view.dpr));
      ctx.lineTo(x + Math.cos(a + 0.5) * r, y + Math.sin(a + 0.5) * r);
      ctx.lineTo(x + Math.cos(a - 0.5) * r, y + Math.sin(a - 0.5) * r);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = 'rgba(14, 18, 32, 0.9)';
      ctx.strokeStyle = info.color;
      ctx.lineWidth = 1.5 * view.dpr;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, TAU);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = info.color;
      ctx.font = `900 ${Math.round(12 * view.dpr)}px "Noto Serif SC", serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(info.icon, x, y + 0.5);
    }
  }

  function drawPlayerBody(x, y, alpha) {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
    ctx.beginPath();
    ctx.ellipse(x, y + 10, 15, 6, 0, 0, TAU);
    ctx.fill();
    ctx.fillStyle = '#262B44';
    ctx.strokeStyle = '#3B4266';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y + 2, 15, 0, TAU);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = '#6B5332';
    ctx.strokeStyle = '#8E7044';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.arc(x, y, 13, 0, TAU);
    ctx.fill();
    ctx.stroke();
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, 8.5, 0, TAU);
    ctx.stroke();
    ctx.fillStyle = '#8E7044';
    ctx.beginPath();
    ctx.arc(x, y, 3.5, 0, TAU);
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  function lanternPos(x, y, fx, fy) {
    // 灯笼提在身体右前方
    const lx = x + fx * 14 - fy * 9;
    const ly = y + fy * 14 + fx * 9 - 6;
    return { lx, ly };
  }

  function drawLantern(x, y, fx, fy, t) {
    const { lx, ly } = lanternPos(x, y, fx, fy);
    ctx.strokeStyle = '#5A4630';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x + fx * 6 - fy * 6, y + fy * 6 + fx * 6);
    ctx.lineTo(lx, ly);
    ctx.stroke();
    const flicker = 1 + Math.sin(t * 13) * 0.05 + Math.sin(t * 7.3) * 0.04;
    const g = ctx.createRadialGradient(lx, ly, 0, lx, ly, 22 * flicker);
    g.addColorStop(0, 'rgba(255, 241, 194, 0.9)');
    g.addColorStop(0.4, 'rgba(255, 200, 97, 0.35)');
    g.addColorStop(1, 'rgba(255, 200, 97, 0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(lx, ly, 22 * flicker, 0, TAU);
    ctx.fill();
    ctx.fillStyle = '#FFD98A';
    ctx.strokeStyle = '#FFF1C2';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(lx, ly, 5, 0, TAU);
    ctx.fill();
    ctx.stroke();
  }

  function drawEnemyBody(e) {
    const d = e.d;
    const k = e.r / 15;
    const bob = Math.sin(e.wob) * 0.6;
    ctx.save();
    ctx.translate(e.x, e.y + bob);
    if (d.boss) {
      const back = Math.atan2(-(e.faceY || 0), -(e.faceX || 1));
      ctx.lineCap = 'round';
      for (let i = 0; i < 9; i++) {
        const a = back + (i - 4) * 0.22 + Math.sin(demo.t * 2 + i) * 0.1;
        const len = 70;
        const mx = Math.cos(a) * len * 0.6 + Math.cos(a + 0.6) * 14;
        const my = Math.sin(a) * len * 0.6 + Math.sin(a + 0.6) * 14;
        ctx.strokeStyle = d.rim;
        ctx.lineWidth = 12;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.quadraticCurveTo(mx, my, Math.cos(a) * len, Math.sin(a) * len);
        ctx.stroke();
        ctx.strokeStyle = d.body;
        ctx.lineWidth = 8;
        ctx.stroke();
        ctx.fillStyle = '#F4EBDD';
        ctx.beginPath();
        ctx.arc(Math.cos(a) * len, Math.sin(a) * len, 4, 0, TAU);
        ctx.fill();
      }
    }
    ctx.scale(k, k);
    if (d.mask === undefined) {
      // 普通妖物
    } else if (d.boss || e.type === 'fox') {
      ctx.fillStyle = d.body;
      ctx.strokeStyle = d.rim;
      ctx.lineWidth = 1.2 / k + 0.6;
      ctx.fill(EARS);
      ctx.stroke(EARS);
    } else {
      ctx.fillStyle = d.rim;
      ctx.fill(HORNS);
    }
    ctx.fillStyle = e.flash > 0 ? '#F4EBDD' : d.body;
    ctx.strokeStyle = d.rim;
    ctx.lineWidth = (d.elite || d.boss ? 2 : 1.2) / Math.max(1, k * 0.8);
    ctx.fill(BLOB);
    ctx.stroke(BLOB);
    if (d.mask) {
      ctx.fillStyle = d.mask;
      ctx.fill(MASK);
      ctx.strokeStyle = d.boss || e.type === 'fox' ? '#D9443A' : '#2E8F66';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(-8, -5);
      ctx.lineTo(-3, -3);
      ctx.moveTo(8, -5);
      ctx.lineTo(3, -3);
      ctx.stroke();
    }
    if (d.toad) {
      // 背上的铜钱
      ctx.fillStyle = '#FFD98A';
      ctx.beginPath();
      ctx.arc(0, 2, 5, 0, TAU);
      ctx.fill();
      ctx.fillStyle = '#5A4210';
      ctx.fillRect(-1.6, 0.4, 3.2, 3.2);
    }
    if (e.type === 'golem' || e.type === 'stonelord') {
      ctx.strokeStyle = e.type === 'stonelord' ? '#6A5238' : '#3A2E24';
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(-6, 4);
      ctx.lineTo(-1, 8);
      ctx.lineTo(3, 5);
      ctx.moveTo(5, -8);
      ctx.lineTo(8, -3);
      ctx.stroke();
    }
    if (e.frozen > 0) {
      ctx.fillStyle = 'rgba(127, 200, 255, 0.45)';
      ctx.fill(BLOB);
    }
    ctx.restore();
    if (e.burnT > 0 && e.burnStacks > 0) {
      ctx.fillStyle = `rgba(255, 138, 61, ${0.15 + 0.05 * e.burnStacks})`;
      ctx.beginPath();
      ctx.arc(e.x, e.y, e.r + 3, 0, TAU);
      ctx.fill();
    }
  }

  function drawEnemyEyes(e) {
    const p = G.player;
    const dx = p.x - e.x;
    const dy = p.y - e.y;
    const d = Math.hypot(dx, dy) || 1;
    const k = e.r / 15;
    const ox = (dx / d) * 1.5 * k;
    const oy = (dy / d) * 1.5 * k - 3 * k + Math.sin(e.wob) * 0.6;
    if (e.d.toad) {
      ctx.fillStyle = 'rgba(255, 217, 138, 0.22)';
      ctx.beginPath();
      ctx.arc(e.x, e.y, e.r * 2, 0, TAU);
      ctx.fill();
    }
    ctx.fillStyle = e.frozen > 0 ? '#CFE3F5' : e.d.eye;
    const ex = e.d.mask ? 6.5 : 4.5;
    ctx.beginPath();
    ctx.ellipse(e.x - ex * k + ox, e.y + oy, 2.3 * k, 1.6 * k, 0, 0, TAU);
    ctx.ellipse(e.x + ex * k + ox, e.y + oy, 2.3 * k, 1.6 * k, 0, 0, TAU);
    ctx.fill();
    if (e.d.elite && !e.d.boss) {
      const w = e.r * 2.2;
      ctx.fillStyle = '#2A1620';
      ctx.fillRect(e.x - w / 2, e.y - e.r - 14, w, 4);
      ctx.fillStyle = '#FF6B5A';
      ctx.fillRect(e.x - w / 2, e.y - e.r - 14, w * clamp(e.hp / e.maxHp, 0, 1), 4);
    }
    if (e.stun > 0) {
      ctx.strokeStyle = '#FFD98A';
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.arc(e.x, e.y - e.r - 4, 5, demo.t * 6, demo.t * 6 + 4);
      ctx.stroke();
    }
  }

  function drawFlame(x, y, size, alpha = 1) {
    const k = size / 9;
    ctx.save();
    ctx.translate(x, y);
    ctx.globalAlpha = alpha * 0.25;
    ctx.fillStyle = '#FF8A3D';
    ctx.beginPath();
    ctx.arc(0, 0, 13 * k, 0, TAU);
    ctx.fill();
    ctx.globalAlpha = alpha;
    ctx.scale(k, k * (1 + Math.sin(demo.t * 15 + x) * 0.06));
    ctx.fillStyle = '#FF8A3D';
    ctx.fill(FLAME);
    ctx.fillStyle = '#FFE08A';
    ctx.fill(FLAME_CORE);
    ctx.restore();
    ctx.globalAlpha = 1;
  }

  function drawWeapons() {
    const p = G.player;
    for (const w of G.weapons) {
      if (w.id === 'lamp') {
        ctx.strokeStyle = 'rgba(255, 138, 61, 0.14)';
        ctx.setLineDash([3, 6]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(p.x, p.y, w.radius || 50, 0, TAU);
        ctx.stroke();
        ctx.setLineDash([]);
        for (let i = 0; i < w.pos.length; i++) {
          const pos = w.pos[i];
          if (w.evo) {
            // 灯笼
            ctx.fillStyle = 'rgba(255, 138, 61, 0.22)';
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, 18, 0, TAU);
            ctx.fill();
            ctx.fillStyle = '#D9443A';
            ctx.strokeStyle = '#FFD98A';
            ctx.lineWidth = 1.2;
            ctx.beginPath();
            ctx.ellipse(pos.x, pos.y, 7, 9, 0, 0, TAU);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = '#FFE08A';
            ctx.beginPath();
            ctx.ellipse(pos.x, pos.y, 3, 5, 0, 0, TAU);
            ctx.fill();
          } else {
            drawFlame(pos.x, pos.y, w.size || 9);
          }
        }
      } else if (w.id === 'crane') {
        for (const c of w.cranes) {
          ctx.save();
          ctx.translate(c.x, c.y);
          ctx.rotate(c.ang);
          const k = w.evo ? 1.25 : 1;
          ctx.scale(k, k);
          ctx.fillStyle = '#E8F5EC';
          ctx.strokeStyle = '#6FD6A0';
          ctx.lineWidth = 1.2;
          ctx.fill(CRANE);
          ctx.stroke(CRANE);
          ctx.restore();
        }
      }
    }
    for (const sh of G.shots) {
      const a = Math.atan2(sh.vy, sh.vx);
      ctx.strokeStyle = sh.bonus ? 'rgba(207, 227, 245, 0.25)' : 'rgba(159, 227, 255, 0.35)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(sh.x - Math.cos(a) * 24, sh.y - Math.sin(a) * 24);
      ctx.lineTo(sh.x - Math.cos(a) * 6, sh.y - Math.sin(a) * 6);
      ctx.stroke();
      ctx.save();
      ctx.translate(sh.x, sh.y);
      ctx.rotate(a);
      const k = sh.big ? 1.4 : sh.bonus ? 0.8 : 1;
      ctx.scale(k, k);
      ctx.fillStyle = '#F4FAFF';
      ctx.fill(SWORD);
      ctx.fillStyle = '#F2B544';
      ctx.fillRect(-7.5, -4.5, 2.5, 9);
      ctx.fillStyle = '#B88A3A';
      ctx.fillRect(-11, -1, 3.5, 2);
      ctx.restore();
    }
  }

  function drawEffects() {
    for (const fx of G.effects) {
      const k = clamp(fx.t / fx.life, 0, 1);
      if (fx.kind === 'ring') {
        ctx.globalAlpha = 1 - k;
        ctx.strokeStyle = fx.color;
        ctx.lineWidth = fx.width * (1 - k * 0.5);
        ctx.beginPath();
        ctx.arc(fx.x, fx.y, fx.r0 + (fx.r1 - fx.r0) * (1 - (1 - k) * (1 - k)), 0, TAU);
        ctx.stroke();
        ctx.globalAlpha = 1;
      } else if (fx.kind === 'sealWarn') {
        if (fx.t < 0) continue;
        ctx.fillStyle = 'rgba(201, 146, 90, 0.12)';
        ctx.strokeStyle = 'rgba(226, 181, 136, 0.7)';
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(fx.x, fx.y, fx.r * (0.6 + 0.4 * k), 0, TAU);
        ctx.fill();
        ctx.stroke();
        ctx.setLineDash([]);
        const size = fx.r * 0.55 * (1.6 - 0.6 * k);
        const y = fx.y - (1 - k) * 110;
        drawSeal(fx.x, y, size, 0.4 + 0.6 * k);
      } else if (fx.kind === 'sealHit') {
        drawSeal(fx.x, fx.y, fx.r * 0.55, 1 - k);
        ctx.globalAlpha = 1 - k;
        ctx.strokeStyle = '#E2B588';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(fx.x, fx.y, fx.r * (0.8 + 0.3 * k), 0, TAU);
        ctx.stroke();
        ctx.globalAlpha = 1;
      } else if (fx.kind === 'blast') {
        ctx.globalAlpha = (1 - k) * 0.6;
        ctx.fillStyle = fx.color;
        ctx.beginPath();
        ctx.arc(fx.x, fx.y, fx.r * (0.4 + 0.6 * k), 0, TAU);
        ctx.fill();
        ctx.globalAlpha = 1;
      } else if (fx.kind === 'taiji') {
        ctx.globalAlpha = 1 - k;
        EL_ORDER.forEach((el, i) => {
          ctx.strokeStyle = EL[el].color;
          ctx.lineWidth = 8;
          const a0 = (i * TAU) / 5 + k * 3;
          ctx.beginPath();
          ctx.arc(fx.x, fx.y, 40 + k * viewRadius(), a0, a0 + TAU / 5 - 0.1);
          ctx.stroke();
        });
        ctx.globalAlpha = 1;
      }
    }
  }

  function drawSeal(x, y, size, alpha) {
    ctx.globalAlpha = clamp(alpha, 0, 1);
    ctx.fillStyle = '#5A4630';
    ctx.strokeStyle = '#E2B588';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(x - size / 2, y - size / 2, size, size, size * 0.12);
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = '#C9925A';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x - size * 0.3, y - size * 0.3, size * 0.6, size * 0.6);
    ctx.globalAlpha = 1;
  }

  function drawGemsAndPickups() {
    for (const g of G.gems) {
      const big = g.v >= 8;
      const mid = g.v >= 2.5;
      const size = big ? 7 : mid ? 5.5 : 4.2;
      const color = big ? '#FFD98A' : mid ? '#8CC8FF' : '#8FF0E0';
      ctx.fillStyle = big ? 'rgba(242, 181, 68, 0.2)' : 'rgba(95, 212, 196, 0.18)';
      ctx.beginPath();
      ctx.arc(g.x, g.y, size * 1.7, 0, TAU);
      ctx.fill();
      ctx.save();
      ctx.translate(g.x, g.y);
      ctx.scale(size, size);
      ctx.fillStyle = color;
      ctx.fill(GEM);
      ctx.restore();
    }
    for (const k of G.pickups) {
      const bob = Math.sin(k.t * 4) * 2;
      if (k.kind === 'chest') {
        ctx.fillStyle = `rgba(242, 181, 68, ${0.2 + 0.1 * Math.sin(k.t * 5)})`;
        ctx.beginPath();
        ctx.arc(k.x, k.y + bob, 24, 0, TAU);
        ctx.fill();
        ctx.fillStyle = '#6B4A1A';
        ctx.strokeStyle = '#FFD98A';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(k.x - 11, k.y - 8 + bob, 22, 16, 3);
        ctx.fill();
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(k.x - 11, k.y - 2 + bob);
        ctx.lineTo(k.x + 11, k.y - 2 + bob);
        ctx.stroke();
        ctx.fillStyle = '#FFD98A';
        ctx.fillRect(k.x - 2, k.y - 4 + bob, 4, 5);
      } else if (k.kind === 'bell') {
        ctx.fillStyle = 'rgba(95, 212, 196, 0.25)';
        ctx.beginPath();
        ctx.arc(k.x, k.y + bob, 16, 0, TAU);
        ctx.fill();
        ctx.fillStyle = '#5FD4C4';
        ctx.beginPath();
        ctx.moveTo(k.x - 7, k.y + 5 + bob);
        ctx.quadraticCurveTo(k.x - 7, k.y - 9 + bob, k.x, k.y - 9 + bob);
        ctx.quadraticCurveTo(k.x + 7, k.y - 9 + bob, k.x + 7, k.y + 5 + bob);
        ctx.closePath();
        ctx.fill();
      } else if (k.kind === 'lotus') {
        ctx.fillStyle = 'rgba(255, 154, 176, 0.22)';
        ctx.beginPath();
        ctx.arc(k.x, k.y + bob, 14, 0, TAU);
        ctx.fill();
        ctx.fillStyle = '#FF9AB0';
        for (let i = 0; i < 5; i++) {
          const a = (i * TAU) / 5 - Math.PI / 2;
          ctx.beginPath();
          ctx.ellipse(k.x + Math.cos(a) * 4, k.y + bob + Math.sin(a) * 4, 4, 2.4, a, 0, TAU);
          ctx.fill();
        }
        ctx.fillStyle = '#FFE08A';
        ctx.beginPath();
        ctx.arc(k.x, k.y + bob, 2.5, 0, TAU);
        ctx.fill();
      }
    }
  }

  function drawFoes() {
    for (const f of G.foes) {
      ctx.fillStyle = 'rgba(255, 180, 107, 0.25)';
      ctx.beginPath();
      ctx.arc(f.x, f.y, f.r * 2, 0, TAU);
      ctx.fill();
      ctx.fillStyle = '#FFB46B';
      ctx.beginPath();
      ctx.arc(f.x, f.y, f.r, 0, TAU);
      ctx.fill();
      ctx.fillStyle = '#FFF1C2';
      ctx.beginPath();
      ctx.arc(f.x, f.y, f.r * 0.45, 0, TAU);
      ctx.fill();
    }
  }

  function drawParticles() {
    for (const pt of G.particles) {
      const a = pt.life / pt.max;
      ctx.globalAlpha = pt.ghost ? a * 0.3 : a;
      ctx.fillStyle = pt.color;
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, pt.size, 0, TAU);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function drawNumbers() {
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const n of G.numbers) {
      const k = n.t / n.life;
      const rise = n.size >= 17 ? 22 : 16;
      const scale = n.size >= 17 && k < 0.15 ? 1.4 - k * 2.6 : 1;
      ctx.globalAlpha = k > 0.6 ? 1 - (k - 0.6) / 0.4 : 1;
      ctx.font = `900 ${Math.round(n.size * scale)}px "Noto Serif SC", serif`;
      ctx.lineWidth = 3;
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.75)';
      ctx.strokeText(n.text, n.x, n.y - k * rise);
      ctx.fillStyle = n.color;
      ctx.fillText(n.text, n.x, n.y - k * rise);
    }
    ctx.globalAlpha = 1;
  }

  // 黑夜：以灯笼为中心的光圈，光圈外只剩妖物的眼睛
  function drawDarkness(sx, sy, radius) {
    const W2 = canvas.width;
    const H2 = canvas.height;
    const g = ctx.createRadialGradient(sx, sy, radius * 0.3, sx, sy, radius * 1.3);
    g.addColorStop(0, 'rgba(5, 7, 13, 0)');
    g.addColorStop(0.55, 'rgba(5, 7, 13, 0.35)');
    g.addColorStop(1, 'rgba(5, 7, 13, 0.86)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W2, H2);
    const warm = ctx.createRadialGradient(sx, sy, 0, sx, sy, radius);
    warm.addColorStop(0, 'rgba(255, 217, 138, 0.10)');
    warm.addColorStop(1, 'rgba(255, 217, 138, 0)');
    ctx.fillStyle = warm;
    ctx.fillRect(0, 0, W2, H2);
  }

  function render(dt) {
    demo.t += dt;
    const k = view.dpr * view.scale;
    let camX;
    let camY;
    let sx = 0;
    let sy = 0;
    const playing = G && state !== 'title' && state !== 'omen';
    mapSeed.x = playing ? G.mapX : 0;
    mapSeed.y = playing ? G.mapY : 0;
    if (playing) {
      camX = G.player.x;
      camY = G.player.y;
      if (G.shake > 0) {
        sx = rand(-G.shake, G.shake) * view.dpr;
        sy = rand(-G.shake, G.shake) * view.dpr;
      }
    } else {
      demo.x += dt * 14;
      demo.y += dt * 6;
      camX = demo.x;
      camY = demo.y;
    }
    const ox = canvas.width / 2 - camX * k + sx;
    const oy = canvas.height / 2 - camY * k + sy;
    ctx.setTransform(k, 0, 0, k, ox, oy);

    const left = camX - view.w / 2 - 20;
    const right = camX + view.w / 2 + 20;
    const top = camY - view.h / 2 - 20;
    const bottom = camY + view.h / 2 + 20;
    drawGround(left, top, right, bottom);

    if (playing) {
      drawEventsGround();
      for (const z of G.zones) {
        ctx.globalAlpha = 0.5 * (z.life / z.max);
        ctx.strokeStyle = '#3A2E24';
        ctx.lineWidth = 4;
        ctx.beginPath();
        for (let i = 0; i < 6; i++) {
          const a = (i * TAU) / 6 + z.x;
          ctx.moveTo(z.x, z.y);
          ctx.lineTo(z.x + Math.cos(a) * z.r, z.y + Math.sin(a) * z.r);
        }
        ctx.stroke();
        ctx.fillStyle = 'rgba(201, 146, 90, 0.12)';
        ctx.beginPath();
        ctx.arc(z.x, z.y, z.r, 0, TAU);
        ctx.fill();
        ctx.globalAlpha = 1;
      }
      for (const e of G.enemies) if (!e.dead && Math.abs(e.x - camX) < view.w / 2 + 80 && Math.abs(e.y - camY) < view.h / 2 + 80) drawEnemyBody(e);
      const p = G.player;
      const blink = p.iframe > 0 && Math.floor(demo.t * 20) % 2 === 0;
      drawPlayerBody(p.x, p.y, blink ? 0.5 : 1);
      if (p.shield > 0) {
        ctx.strokeStyle = 'rgba(226, 181, 136, 0.6)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 20, 0, TAU);
        ctx.stroke();
      }
    } else {
      drawPlayerBody(camX, camY, 1);
    }

    // 黑夜遮罩（屏幕坐标）
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const lightR = (playing ? 200 * Math.sqrt(G.stats.area) * G.mods.light : 210) * k;
    drawDarkness(canvas.width / 2 + sx, canvas.height / 2 + sy, lightR);
    ctx.setTransform(k, 0, 0, k, ox, oy);

    if (playing) {
      const p = G.player;
      drawEventsGlow();
      drawGemsAndPickups();
      for (const e of G.enemies) if (!e.dead && Math.abs(e.x - camX) < view.w / 2 + 40 && Math.abs(e.y - camY) < view.h / 2 + 40) drawEnemyEyes(e);
      drawEffects();
      drawWeapons();
      drawLantern(p.x, p.y, p.faceX, p.faceY, demo.t);
      drawFoes();
      drawParticles();
      drawNumbers();
    } else {
      drawLantern(camX, camY, 1, 0.3, demo.t);
    }

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (playing) drawEventArrows(camX, camY, k);
    if (playing && G.edge) {
      ctx.globalAlpha = clamp(G.edge.t, 0, 1) * 0.5;
      ctx.strokeStyle = G.edge.color;
      ctx.lineWidth = 26 * view.dpr;
      ctx.strokeRect(0, 0, canvas.width, canvas.height);
      ctx.globalAlpha = 1;
    }
    if (playing && G.flash) {
      ctx.globalAlpha = clamp(G.flash.a, 0, 1);
      ctx.fillStyle = G.flash.color;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.globalAlpha = 1;
    }
  }

  // =====================================================================
  // 主循环
  // =====================================================================
  let last = performance.now();
  let debugSteps = 1; // 仅调试模式下用来加速模拟
  function frame(now) {
    const realDt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (state === 'play') {
      for (let i = 0; i < debugSteps && state === 'play'; i++) {
        let dt = realDt;
        if (G.slowT > 0) {
          G.slowT -= realDt;
          dt *= 0.3;
        }
        update(dt);
      }
    } else if (state === 'evo') {
      evoTimer -= realDt;
      if (evoTimer <= 0) afterChoice();
    }
    if (G && state !== 'title' && state !== 'over' && state !== 'meta' && state !== 'omen') updateHud();
    render(realDt);
    requestAnimationFrame(frame);
  }

  // =====================================================================
  // 输入
  // =====================================================================
  const GAME_KEYS = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']);

  document.addEventListener('keydown', (e) => {
    if (GAME_KEYS.has(e.code)) {
      input.keys.add(e.code);
      if (state === 'play') e.preventDefault();
      return;
    }
    if (e.repeat) return;
    if (state === 'play') {
      if (e.code === 'Space' || e.code === 'ShiftLeft' || e.code === 'KeyJ') {
        e.preventDefault();
        dash();
      } else if (e.code === 'KeyE' || e.code === 'KeyK') {
        ultimate();
      } else if (e.code === 'Escape' || e.code === 'KeyP') {
        pauseGame();
      }
    } else if (state === 'paused' && (e.code === 'Escape' || e.code === 'KeyP')) {
      setState('play');
    } else if (state === 'levelup' && ['Digit1', 'Digit2', 'Digit3', 'Digit4'].includes(e.code)) {
      const i = Number(e.code.slice(-1)) - 1;
      if (currentChoices[i]) chooseOption(i);
    } else if (state === 'omen' && ['Digit1', 'Digit2', 'Digit3'].includes(e.code)) {
      const card = $('omen-cards').children[Number(e.code.slice(-1)) - 1];
      if (card) card.click();
    } else if (state === 'title' && (e.code === 'Enter' || e.code === 'Space')) {
      e.preventDefault();
      startRun();
    }
  });
  document.addEventListener('keyup', (e) => input.keys.delete(e.code));
  window.addEventListener('blur', () => {
    input.keys.clear();
    pauseGame();
  });

  canvas.addEventListener('pointerdown', (e) => {
    if (state !== 'play' || input.joy) return;
    input.joy = { id: e.pointerId, ox: e.clientX, oy: e.clientY, x: e.clientX, y: e.clientY };
    canvas.setPointerCapture(e.pointerId);
    const j = $('joystick');
    j.hidden = false;
    j.style.left = `${e.clientX}px`;
    j.style.top = `${e.clientY}px`;
    $('knob').style.transform = '';
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!input.joy || e.pointerId !== input.joy.id) return;
    input.joy.x = e.clientX;
    input.joy.y = e.clientY;
    const dx = e.clientX - input.joy.ox;
    const dy = e.clientY - input.joy.oy;
    const d = Math.hypot(dx, dy);
    const m = Math.min(d, 44) / (d || 1);
    $('knob').style.transform = `translate(${dx * m}px, ${dy * m}px)`;
  });
  const endJoy = (e) => {
    if (!input.joy || e.pointerId !== input.joy.id) return;
    input.joy = null;
    $('joystick').hidden = true;
  };
  canvas.addEventListener('pointerup', endJoy);
  canvas.addEventListener('pointercancel', endJoy);

  const tap = (id, fn) => {
    $(id).addEventListener('pointerdown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      fn();
    });
  };
  tap('dash-btn', dash);
  tap('ult-btn', ultimate);
  $('pause-btn').addEventListener('click', pauseGame);

  $('start-btn').addEventListener('click', startRun);
  $('omen-back').addEventListener('click', () => setState('title'));

  // 音频：第一次触摸或按键时解锁（浏览器要求用户手势）
  const unlockAudio = () => {
    if (!AUDIO) return;
    AUDIO.init();
    if (state === 'title' || state === 'omen') AUDIO.setMusic('title');
  };
  document.addEventListener('pointerdown', unlockAudio);
  document.addEventListener('keydown', unlockAudio);
  document.addEventListener('click', (e) => {
    if (e.target.closest('.btn, .card')) SFX.click();
  });

  function syncAudioButtons() {
    const st = AUDIO ? AUDIO.settings : { music: false, sfx: false };
    document.querySelectorAll('[data-audio]').forEach((btn) => {
      const kind = btn.dataset.audio;
      const on = st[kind];
      btn.setAttribute('aria-pressed', String(on));
      btn.textContent = `${kind === 'music' ? '音乐' : '音效'} ${on ? '开' : '关'}`;
    });
  }
  document.querySelectorAll('[data-audio]').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (!AUDIO) return;
      AUDIO.init();
      const kind = btn.dataset.audio;
      AUDIO.setEnabled(kind, !AUDIO.settings[kind]);
      syncAudioButtons();
    });
  });
  syncAudioButtons();
  $('again-btn').addEventListener('click', startRun);
  $('meta-btn').addEventListener('click', () => {
    metaReturn = 'title';
    setState('meta');
  });
  $('result-meta-btn').addEventListener('click', () => {
    metaReturn = 'over';
    setState('meta');
  });
  $('meta-back').addEventListener('click', () => {
    if (metaReturn === 'over') renderNextUnlock();
    setState(metaReturn);
  });
  $('home-btn').addEventListener('click', () => setState('title'));
  $('resume-btn').addEventListener('click', () => setState('play'));
  $('quit-btn').addEventListener('click', () => {
    setState('play');
    endRun(false);
  });
  $('reroll-btn').addEventListener('click', () => {
    if (G.rerolls <= 0) return;
    G.rerolls--;
    currentChoices = rollChoices();
    renderCards();
  });
  $('skip-btn').addEventListener('click', () => {
    G.oilBonus += 10;
    afterChoice();
  });
  $('chest-ok').addEventListener('click', afterChoice);

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) pauseGame();
  });
  window.addEventListener('resize', resize);

  // 调试：地址加 ?debug 时暴露内部状态，便于测试
  if (location.search.includes('debug')) {
    window.__lantern = {
      get G() {
        return G;
      },
      get state() {
        return state;
      },
      addXp: (v) => addXp(v),
      setTime: (t) => {
        G.t = t;
      },
      setSpeed: (n) => {
        debugSteps = n;
      },
      spawnEvent: (k) => spawnEvent(k),
      audio: () => AUDIO,
    };
  }

  resize();
  setState('title');
  requestAnimationFrame((t) => {
    last = t;
    frame(t);
  });
})();
