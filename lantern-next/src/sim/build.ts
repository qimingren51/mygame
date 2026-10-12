// 构筑：五行共鸣、属性计算、升级选项、宝箱（移植自旧版 computeRes / computeStats / buildOptions / applyOption / openChest）。

import { ELEMENT_IDS, SHENG, tierOf, type ElementId } from '../data/elements';
import { PASSIVES, PASSIVE_IDS } from '../data/passives';
import { PASSIVE_MAX, SLOT_MAX, WEAPONS, WEAPON_IDS, WEAPON_MAX, type WeaponId } from '../data/weapons';
import type { Rng } from '../core/rng';
import { getPassive, getWeapon, newWeapon, plv, type Option, type World } from './state';

// ---------------------------------------------------------------------------
// 五行共鸣与属性
// ---------------------------------------------------------------------------

/** 满级（或已进化）的法器、满级的心法计 2 点 */
export function computeRes(w: World, announce: boolean): void {
  const res = w.res;
  for (const el of ELEMENT_IDS) res[el] = 0;
  for (const wp of w.weapons) res[WEAPONS[wp.id].el] += wp.lv >= WEAPON_MAX || wp.evo ? 2 : 1;
  for (const p of w.passives) res[PASSIVES[p.id].el] += p.lv >= PASSIVE_MAX ? 2 : 1;
  if (w.mods.favor) res[w.mods.favor] += 2;
  for (const el of ELEMENT_IDS) {
    const tier = tierOf(res[el]);
    if (announce && tier > w.tier[el]) w.bus.emit({ k: 'resonance', el, tier, points: res[el] });
    w.tier[el] = tier;
  }
  for (const s of SHENG) {
    const on = w.tier[s.a] >= 1 && w.tier[s.b] >= 1;
    if (announce && on && !w.sheng[s.name]) w.bus.emit({ k: 'sheng', name: s.name, desc: s.desc, el: s.b });
    w.sheng[s.name] = on;
  }
  const taiji = ELEMENT_IDS.every((el) => w.tier[el] >= 1);
  if (announce && taiji && !w.taiji) w.bus.emit({ k: 'taiji' });
  w.taiji = taiji;
}

export function computeStats(w: World, announce = false): void {
  computeRes(w, announce);
  const t = w.tier;
  const m = w.mods;
  const meta = w.meta;
  const s = w.stats;
  const prevMax = s.maxHp;
  s.area = 1 + 0.1 * plv(w, 'changming');
  s.dmg = (1 + 0.08 * plv(w, 'luxin')) * (1 + 0.04 * meta.dmg) * m.dmg;
  s.critChance = 0.05 + 0.05 * plv(w, 'ruimu') + (t.metal >= 1 ? 0.1 : 0) + m.crit;
  s.critMult = 2 + 0.2 * plv(w, 'jianyi') + (t.metal >= 2 ? 0.5 : 0);
  s.cd = Math.max(0.6, 1 - 0.06 * plv(w, 'jingxin'));
  s.magnet = 65 * (1 + 0.25 * plv(w, 'yinhun')) * (1 + 0.08 * meta.agi);
  s.amount = ([0, 1, 1, 2, 2, 3][plv(w, 'zhezhi')] as number) + (t.wood >= 2 ? 1 : 0);
  s.speed = 118 * (1 + 0.08 * plv(w, 'jixing')) * (1 + 0.03 * meta.agi) * m.speed;
  s.maxHp = Math.round((100 + 20 * plv(w, 'houde') + 12 * meta.hp) * m.maxHp);
  s.armor = plv(w, 'houde');
  s.taken = 1 - 0.05 * plv(w, 'panshi');
  s.regen = m.noHeal ? 0 : (t.wood >= 1 ? 0.005 * s.maxHp : 0) * (w.sheng['水生木'] ? 2 : 1);
  s.burnMult = w.sheng['木生火'] ? 1.3 : 1;
  s.shieldCd = w.sheng['火生土'] ? 6 : 10;
  s.kb = t.earth >= 2 ? 2 : 1;
  // 生命上限提高时同时回复差值
  if (prevMax && s.maxHp > prevMax) w.player.hp += s.maxHp - prevMax;
  w.player.hp = Math.min(w.player.hp, s.maxHp);
}

// ---------------------------------------------------------------------------
// 升级选项
// ---------------------------------------------------------------------------

export function elOf(o: Option): ElementId | null {
  if (o.type === 'evo' || o.type === 'wup' || o.type === 'wnew') return WEAPONS[o.id].el;
  if (o.type === 'pup' || o.type === 'pnew') return PASSIVES[o.id].el;
  return null;
}

export function buildOptions(w: World): Option[] {
  const opts: Option[] = [];
  // 法器满级并持有对应心法：必出进化
  for (const wp of w.weapons) {
    if (!wp.evo && wp.lv >= WEAPON_MAX && plv(w, WEAPONS[wp.id].evoPassive) > 0) opts.push({ type: 'evo', id: wp.id, weight: 1000 });
  }
  for (const wp of w.weapons) if (!wp.evo && wp.lv < WEAPON_MAX) opts.push({ type: 'wup', id: wp.id, weight: 10 });
  if (w.weapons.length < SLOT_MAX) {
    for (const id of WEAPON_IDS) if (!getWeapon(w, id)) opts.push({ type: 'wnew', id, weight: w.t < 180 ? 9 : 5 });
  }
  for (const p of w.passives) if (p.lv < PASSIVE_MAX) opts.push({ type: 'pup', id: p.id, weight: 7 });
  if (w.passives.length < SLOT_MAX) {
    for (const id of PASSIVE_IDS) if (!getPassive(w, id)) opts.push({ type: 'pnew', id, weight: 5 });
  }
  // 已投入的五行更容易出现，帮助玩家凑共鸣
  for (const o of opts) {
    if (o.type === 'evo') continue;
    const el = elOf(o) as ElementId;
    if (w.res[el] >= 2) o.weight *= 1.5;
    if (w.mods.favor) o.weight *= el === w.mods.favor ? 1.3 : 0.6;
  }
  return opts;
}

export function pickWeighted(rng: Rng, opts: Option[], n: number): Option[] {
  const pool = opts.slice();
  const out: Option[] = [];
  while (out.length < n && pool.length) {
    let total = 0;
    for (const o of pool) total += o.weight;
    let r = rng.next() * total;
    let i = 0;
    for (; i < pool.length - 1; i++) {
      r -= (pool[i] as Option).weight;
      if (r <= 0) break;
    }
    out.push(pool.splice(i, 1)[0] as Option);
  }
  return out;
}

/** 升级时抽选项。返回选项和是否“灵光一闪”（小概率四选一）。 */
export function rollChoices(w: World): { options: Option[]; lingguang: boolean } {
  const opts = buildOptions(w);
  if (!opts.length) {
    return { options: w.mods.noHeal ? [{ type: 'oil', weight: 1 }] : [{ type: 'heal', weight: 1 }, { type: 'oil', weight: 1 }], lingguang: false };
  }
  let n = w.mods.choices;
  let lingguang = false;
  if (n === 3 && w.rng.choices.chance(0.1)) {
    n = 4;
    lingguang = true;
  }
  return { options: pickWeighted(w.rng.choices, opts, n), lingguang };
}

export function addWeapon(w: World, id: WeaponId): void {
  w.weapons.push(newWeapon(id));
}

export function applyOption(w: World, o: Option): void {
  if (o.type === 'evo') {
    const wp = getWeapon(w, o.id);
    if (wp) {
      wp.evo = true;
      w.evolutions++;
      w.pendingEvos.push(o.id);
    }
  } else if (o.type === 'wup') {
    const wp = getWeapon(w, o.id);
    if (wp) wp.lv++;
  } else if (o.type === 'wnew') {
    addWeapon(w, o.id);
  } else if (o.type === 'pup') {
    const p = getPassive(w, o.id);
    if (p) p.lv++;
  } else if (o.type === 'pnew') {
    w.passives.push({ id: o.id, lv: 1 });
  } else if (o.type === 'heal') {
    w.player.hp = Math.min(w.stats.maxHp, w.player.hp + w.stats.maxHp * 0.3);
  } else if (o.type === 'oil') {
    w.oilBonus += 20;
  }
  computeStats(w, true);
}

/** 打开一个宝箱：按概率 1 / 3 / 5 连，直接应用，返回揭晓的内容。 */
export function rollChest(w: World): Option[] {
  const r = w.rng.chest.next() + w.meta.luck * 0.03;
  const n = Math.max(w.mods.chestMin, r > 0.93 ? 5 : r > 0.68 ? 3 : 1);
  const items: Option[] = [];
  for (let i = 0; i < n; i++) {
    // 宝箱只给升级和进化，不给新法器 / 新心法；都满了才放宽
    const all = buildOptions(w);
    const ups = all.filter((o) => o.type !== 'wnew' && o.type !== 'pnew');
    const pool = ups.length ? ups : all;
    const o: Option = pool.length ? (pickWeighted(w.rng.chest, pool, 1)[0] as Option) : { type: 'oil', weight: 1 };
    applyOption(w, o);
    items.push(o);
  }
  return items;
}
