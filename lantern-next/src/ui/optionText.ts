// 升级卡片上的文字（移植自旧版 optionInfo / optionNote / weaponUpgradeText），纯函数。

import { EL, SHENG, tierOf } from '../data/elements';
import { PASSIVES } from '../data/passives';
import { PASSIVE_MAX, STAT_LABEL, W, WEAPONS, WEAPON_MAX, type WeaponId } from '../data/weapons';
import { elOf } from '../sim/build';
import { getPassive, getWeapon, plv, type Option, type World } from '../sim/state';

export type Rarity = 'tian' | 'xuan' | 'ling' | 'fan';

export const RARITY_NAME: Record<Rarity, string> = { tian: '天品', xuan: '玄品', ling: '灵品', fan: '凡品' };

export interface OptionInfo {
  rarity: Rarity;
  kind: string;
  icon: string;
  /** 五行颜色（0xRRGGBB） */
  color: number;
  name: string;
  desc: string;
  /** 五行名（金木水火土），补给没有 */
  el: string | null;
}

export interface OptionNote {
  /** 高亮颜色；null 表示普通提示 */
  color: number | null;
  title: string;
  body: string;
}

export function weaponUpgradeText(id: WeaponId, lv: number): string {
  const a = W[id](lv) as Record<string, number>;
  const b = W[id](lv + 1) as Record<string, number>;
  const parts: string[] = [];
  for (const k of Object.keys(STAT_LABEL) as (keyof typeof STAT_LABEL)[]) {
    const va = a[k];
    const vb = b[k];
    if (va === undefined || vb === undefined || va === vb) continue;
    if (k === 'cd') parts.push(`冷却 -${(va - vb).toFixed(2)} 秒`);
    else parts.push(`${STAT_LABEL[k]} +${Math.round(vb - va)}`);
  }
  return `${parts.join('，')}。`;
}

export function optionInfo(w: World, o: Option): OptionInfo {
  if (o.type === 'heal') return { rarity: 'fan', kind: '补给', icon: '莲', color: 0x6fd6a0, name: '莲子', desc: '回复 30% 生命。', el: null };
  if (o.type === 'oil') return { rarity: 'fan', kind: '补给', icon: '油', color: 0xffd98a, name: '灯油', desc: '本局结算灯油 +20。', el: null };
  const el = EL[elOf(o) ?? 'fire'];
  if (o.type === 'evo') {
    const def = WEAPONS[o.id];
    return { rarity: 'tian', kind: '进化', icon: def.icon, color: el.color, name: def.evoName, desc: `${def.evoDesc}。`, el: el.name };
  }
  if (o.type === 'wnew' || o.type === 'wup') {
    const def = WEAPONS[o.id];
    const wp = getWeapon(w, o.id);
    if (o.type === 'wnew' || !wp) return { rarity: 'xuan', kind: '法器 · 新', icon: def.icon, color: el.color, name: def.name, desc: def.desc, el: el.name };
    return { rarity: 'ling', kind: `法器 · Lv${wp.lv} → ${wp.lv + 1}`, icon: def.icon, color: el.color, name: def.name, desc: weaponUpgradeText(o.id, wp.lv), el: el.name };
  }
  const def = PASSIVES[o.id];
  const p = getPassive(w, o.id);
  if (o.type === 'pnew' || !p) return { rarity: 'ling', kind: '心法 · 新', icon: def.name[0] ?? '', color: el.color, name: def.name, desc: `${def.desc}。`, el: el.name };
  return { rarity: 'fan', kind: `心法 · Lv${p.lv} → ${p.lv + 1}`, icon: def.name[0] ?? '', color: el.color, name: def.name, desc: `${def.desc}。`, el: el.name };
}

/** 卡片底部提示：共鸣进度、相生、进化线索 */
export function optionNote(w: World, o: Option): OptionNote | null {
  if (o.type === 'heal' || o.type === 'oil') return null;
  if (o.type === 'evo') {
    const def = WEAPONS[o.id];
    return { color: 0xffd98a, title: '选择后立即进化', body: `${def.name} Lv8 + ${PASSIVES[def.evoPassive].name}` };
  }
  const elId = elOf(o) ?? 'fire';
  const from = w.res[elId];
  let gain = 0;
  if (o.type === 'wnew' || o.type === 'pnew') gain = 1;
  else if (o.type === 'wup') gain = (getWeapon(w, o.id)?.lv ?? 0) + 1 >= WEAPON_MAX ? 1 : 0;
  else gain = (getPassive(w, o.id)?.lv ?? 0) + 1 >= PASSIVE_MAX ? 1 : 0;
  const to = from + gain;
  const e = EL[elId];
  if (tierOf(to) > tierOf(from)) {
    const t = tierOf(to);
    let body = e.tiers[t - 1] ?? '';
    if (t === 1) {
      const sh = SHENG.find((s) => (s.a === elId && w.tier[s.b] >= 1) || (s.b === elId && w.tier[s.a] >= 1));
      if (sh) body += `，并点亮「${sh.name}」`;
    }
    return { color: e.color, title: `${e.name} ${from} → ${to} · 共鸣${t === 3 ? '达成' : '激活'}`, body };
  }
  const progress = `${e.name} ${from}${gain ? ` → ${to}` : ''}`;
  // 进化线索
  if (o.type === 'wnew' || o.type === 'wup') {
    const def = WEAPONS[o.id];
    const lvAfter = o.type === 'wnew' ? 1 : (getWeapon(w, o.id)?.lv ?? 0) + 1;
    if (lvAfter >= WEAPON_MAX && plv(w, def.evoPassive) > 0) return { color: 0xffd98a, title: '满级 · 下次升级可进化', body: `→ ${def.evoName}` };
    return { color: null, title: progress, body: `进化需心法「${PASSIVES[def.evoPassive].name}」` };
  }
  const wid = (Object.keys(WEAPONS) as WeaponId[]).find((id) => WEAPONS[id].evoPassive === o.id);
  const wp = wid ? getWeapon(w, wid) : undefined;
  if (wid && wp && !wp.evo) {
    return wp.lv >= WEAPON_MAX
      ? { color: 0xffd98a, title: '可进化', body: `${WEAPONS[wid].name} → ${WEAPONS[wid].evoName}` }
      : { color: null, title: progress, body: `${WEAPONS[wid].name} 满级后可进化` };
  }
  return { color: null, title: progress, body: '' };
}

export const cssColor = (c: number): string => `#${c.toString(16).padStart(6, '0')}`;
