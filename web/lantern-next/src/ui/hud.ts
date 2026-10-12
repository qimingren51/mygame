// 战斗 HUD：经验条、头像与生命、法器心法格子、计时、五行共鸣、击杀、连斩、夜主血条、燃灯与闪避按钮、提示条。
// 每帧调用 update(world)；只有数值变化时才改 DOM。

import { xpNeed, RUN_LENGTH } from '../data/balance';
import { EL, ELEMENT_IDS } from '../data/elements';
import { PASSIVES } from '../data/passives';
import { SLOT_MAX, WEAPONS } from '../data/weapons';
import type { World } from '../sim/state';
import { cssColor } from './optionText';

const $ = <T extends HTMLElement>(root: ParentNode, sel: string): T => root.querySelector(sel) as T;

export const fmtTime = (t: number): string => {
  const s = Math.max(0, Math.floor(t));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};

export const fmtNum = (n: number): string => (n >= 10000 ? `${(n / 1000).toFixed(1)}k` : String(n));

export interface HudActions {
  dash(): void;
  ult(): void;
  pause(): void;
}

export class Hud {
  readonly el: HTMLElement;
  private readonly cache = new Map<string, string>();
  private readonly toasts: HTMLElement;

  constructor(actions: HudActions) {
    const el = document.createElement('div');
    el.id = 'game-hud';
    el.className = 'hud';
    el.hidden = true;
    el.innerHTML = `
      <div class="xpbar"><div class="xp-fill" data-id="xp"></div></div>
      <div class="hud-left">
        <div class="hero">
          <div class="portrait" aria-hidden="true"><span class="portrait-glyph">剑</span><span class="level-badge" data-id="level">1</span></div>
          <div class="hp-wrap">
            <div class="hp-row"><span class="hero-name">提灯人</span><span data-id="hptext">100 / 100</span></div>
            <div class="hpbar"><div class="hp-fill" data-id="hp"></div><div class="shield-fill" data-id="shield"></div></div>
          </div>
        </div>
        <div class="slots" data-id="wslots"></div>
        <div class="slots small" data-id="pslots"></div>
      </div>
      <div class="hud-center">
        <div class="timer" data-id="timer">00:00</div>
        <div class="phase" data-id="phase">生存期</div>
        <div class="res-chips" data-id="res"></div>
      </div>
      <div class="hud-right">
        <div class="stat" title="击杀"><span class="stat-glyph">斩</span><span data-id="kills">0</span></div>
        <button class="icon-btn pause-btn" type="button" aria-label="暂停" data-id="pause">❚❚</button>
      </div>
      <div class="combo" data-id="combo" hidden></div>
      <div class="toasts" aria-live="polite"></div>
      <div class="boss-bar" data-id="bossbar" hidden>
        <div class="boss-name">夜主 · 九尾</div>
        <div class="boss-track"><div class="boss-fill" data-id="boss"></div></div>
      </div>
      <button class="dash-btn" type="button" aria-label="闪避" data-id="dash">闪</button>
      <button class="ult-btn" type="button" aria-label="燃灯：清屏大招" data-id="ult"><span class="ult-ring"></span><span class="ult-label">燃灯</span></button>`;
    document.body.appendChild(el);
    this.el = el;
    this.toasts = $(el, '.toasts');
    const press = (id: string, fn: () => void) => {
      $(el, `[data-id="${id}"]`).addEventListener('pointerdown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        fn();
      });
    };
    press('dash', actions.dash);
    press('ult', actions.ult);
    $(el, '[data-id="pause"]').addEventListener('click', actions.pause);
  }

  private node(id: string): HTMLElement {
    return $(this.el, `[data-id="${id}"]`);
  }

  private text(id: string, v: string): void {
    if (this.cache.get(id) === v) return;
    this.cache.set(id, v);
    this.node(id).textContent = v;
  }

  private width(id: string, pct: number): void {
    const v = `${Math.max(0, Math.min(100, pct)).toFixed(1)}%`;
    if (this.cache.get(id) === v) return;
    this.cache.set(id, v);
    this.node(id).style.width = v;
  }

  private html(id: string, key: string, render: () => string): void {
    if (this.cache.get(id) === key) return;
    this.cache.set(id, key);
    this.node(id).innerHTML = render();
  }

  reset(): void {
    this.cache.clear();
    this.toasts.innerHTML = '';
  }

  update(w: World): void {
    const p = w.player;
    const s = w.stats;
    this.width('xp', (w.xp / xpNeed(w.level)) * 100);
    this.text('level', String(w.level));
    this.text('hptext', `${Math.ceil(p.hp)} / ${s.maxHp}`);
    this.width('hp', (p.hp / s.maxHp) * 100);
    this.width('shield', p.shield > 0 ? (p.shield / (p.shieldMax || 1)) * 100 : 0);
    this.text('timer', fmtTime(w.t));
    const boss = w.enemies.resolve(w.boss);
    const phase = boss >= 0 ? '决战' : w.t < 180 ? '生存期' : w.t < 390 ? '构筑期' : w.t < RUN_LENGTH ? '割草期' : '长夜';
    this.text('phase', phase);
    this.text('kills', fmtNum(w.kills));

    const combo = this.node('combo');
    if (w.combo >= 10) {
      combo.hidden = false;
      this.html('combo', String(w.combo), () => `<small>连斩</small>${w.combo}`);
    } else if (!combo.hidden) combo.hidden = true;

    const ult = this.node('ult');
    const charge = w.ult.toFixed(3);
    if (this.cache.get('ultc') !== charge) {
      this.cache.set('ultc', charge);
      ult.style.setProperty('--charge', charge);
      ult.classList.toggle('ready', w.ult >= 1);
    }
    const cooling = p.dashCd > 0 ? '1' : '0';
    if (this.cache.get('dashc') !== cooling) {
      this.cache.set('dashc', cooling);
      this.node('dash').classList.toggle('cooling', p.dashCd > 0);
    }

    const bossBar = this.node('bossbar');
    if (boss >= 0) {
      bossBar.hidden = false;
      this.width('boss', ((w.enemies.hp[boss] as number) / (w.enemies.maxHp[boss] as number)) * 100);
    } else if (!bossBar.hidden) bossBar.hidden = true;

    const resKey = ELEMENT_IDS.map((e) => `${w.res[e]}${w.tier[e]}`).join(',');
    this.html('res', resKey, () => resChips(w, false));
    const slotKey = w.weapons.map((x) => `${x.id}${x.lv}${x.evo ? '*' : ''}`).join(',') + '|' + w.passives.map((x) => `${x.id}${x.lv}`).join(',');
    if (this.cache.get('slots') !== slotKey) {
      this.cache.set('slots', slotKey);
      this.node('wslots').innerHTML = weaponSlots(w);
      this.node('pslots').innerHTML = passiveSlots(w);
    }
  }

  toast(title: string, body: string, color: number, big = false): void {
    const div = document.createElement('div');
    div.className = `toast${big ? ' big' : ''}`;
    div.style.setProperty('--c', cssColor(color));
    const b = document.createElement('b');
    b.textContent = title;
    div.append(b, body);
    this.toasts.appendChild(div);
    while (this.toasts.children.length > 3) this.toasts.firstElementChild?.remove();
    setTimeout(() => div.remove(), 2500);
  }
}

/** 五行共鸣小标签；onlyOwned 时只列出有投入的五行，激活的写出共鸣名 */
export function resChips(w: World, onlyOwned: boolean): string {
  return ELEMENT_IDS.filter((e) => !onlyOwned || w.res[e] > 0)
    .map((e) => {
      const n = w.res[e];
      const on = w.tier[e] >= 1;
      const cls = on ? 'on' : n === 0 ? 'zero' : '';
      const def = EL[e];
      const label = onlyOwned && on ? `${def.name}·${def.res}` : def.name;
      return `<span class="res-chip ${cls}" style="--c:${cssColor(def.color)}"><b>${label}</b>${n}</span>`;
    })
    .join('');
}

function weaponSlots(w: World): string {
  let html = '';
  for (let i = 0; i < SLOT_MAX; i++) {
    const wp = w.weapons[i];
    if (!wp) {
      html += '<div class="slot empty"></div>';
      continue;
    }
    const def = WEAPONS[wp.id];
    html += `<div class="slot ${wp.evo ? 'evo' : ''}" style="--c:${cssColor(EL[def.el].color)}">${def.icon}<span class="lv">${wp.evo ? '' : wp.lv}</span></div>`;
  }
  return html;
}

function passiveSlots(w: World): string {
  let html = '';
  for (let i = 0; i < SLOT_MAX; i++) {
    const p = w.passives[i];
    html += p ? `<div class="slot" style="--c:${cssColor(EL[PASSIVES[p.id].el].color)}">${PASSIVES[p.id].name[0] ?? ''}</div>` : '<div class="slot empty"></div>';
  }
  return html;
}
