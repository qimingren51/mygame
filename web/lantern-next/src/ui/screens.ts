// 局内的全屏界面：升级三选一、宝箱、进化演出、暂停、结算。
// 根据 world.phase 显示对应界面；玩家的选择通过 send() 变成模拟命令。

import { EL } from '../data/elements';
import { PASSIVES } from '../data/passives';
import { WEAPONS } from '../data/weapons';
import type { Command, Option, World } from '../sim/state';
import { fmtNum, fmtTime, resChips } from './hud';
import { RARITY_NAME, cssColor, optionInfo, optionNote } from './optionText';

const esc = (s: string): string => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string);

function section(id: string, cls: string): HTMLElement {
  const el = document.createElement('section');
  el.id = id;
  el.className = `screen ${cls}`;
  el.hidden = true;
  document.body.appendChild(el);
  return el;
}

export interface ScreenActions {
  send(c: Command): void;
  resume(): void;
  quit(): void;
  again(): void;
  sfxSelect(): void;
}

export class Screens {
  private readonly levelup = section('levelup-screen', 'dim');
  private readonly chest = section('chest-screen', 'dim');
  private readonly evo = section('evo-screen', 'evo-screen');
  private readonly pause = section('pause-screen', 'dim');
  private readonly result = section('result-screen', 'dim');
  private shownPhase = '';
  private shownChoice: Option[] | null = null;
  private evoTimer = 0;
  private readonly actions: ScreenActions;
  paused = false;

  constructor(actions: ScreenActions) {
    this.actions = actions;
    addEventListener('keydown', (e) => {
      if (!this.levelup.hidden && /^Digit[1-4]$/.test(e.code)) {
        const i = Number(e.code.slice(5)) - 1;
        (this.levelup.querySelectorAll<HTMLButtonElement>('.card')[i] as HTMLButtonElement | undefined)?.click();
      }
      if (!this.chest.hidden && (e.code === 'Enter' || e.code === 'Space')) this.ackChest();
    });
  }

  /** 每帧调用：阶段变化时切换界面 */
  sync(w: World, dt: number): void {
    const phase = this.paused ? 'paused' : w.phase;
    if (phase === 'levelup' && w.choice && w.choice.options !== this.shownChoice) this.renderLevelUp(w);
    if (phase !== this.shownPhase) {
      this.shownPhase = phase;
      this.levelup.hidden = phase !== 'levelup';
      this.chest.hidden = phase !== 'chest';
      this.evo.hidden = phase !== 'evo';
      this.pause.hidden = phase !== 'paused';
      this.result.hidden = phase !== 'over';
      if (phase === 'chest') this.renderChest(w);
      if (phase === 'evo') this.renderEvo(w);
      if (phase === 'paused') this.renderPause(w);
      if (phase === 'over') this.renderResult(w);
      if (phase !== 'levelup') this.shownChoice = null;
    }
    // 进化演出 2.1 秒后自动继续
    if (phase === 'evo') {
      this.evoTimer -= dt;
      if (this.evoTimer <= 0) {
        this.evoTimer = 99;
        this.actions.send({ k: 'ack' });
      }
    }
  }

  hideAll(): void {
    this.shownPhase = '';
    this.shownChoice = null;
    for (const s of [this.levelup, this.chest, this.evo, this.pause, this.result]) s.hidden = true;
  }

  private renderLevelUp(w: World): void {
    const c = w.choice;
    if (!c) return;
    this.shownChoice = c.options;
    const how = c.lingguang ? '灵光一闪 · 四选一' : c.options.length === 2 ? '二选一' : c.options.length === 1 ? '补给' : '三选一';
    const cards = c.options
      .map((o, i) => {
        const info = optionInfo(w, o);
        const note = optionNote(w, o);
        return `<button type="button" class="card ${info.rarity}" data-i="${i}" style="--rc:var(--r-${info.rarity});--c:${cssColor(info.color)}">
          <div class="card-top"><span class="rarity">${RARITY_NAME[info.rarity]}</span><span class="card-kind">${esc(info.kind)}</span></div>
          <div class="card-head"><div class="card-icon">${esc(info.icon)}</div><div class="card-name">${esc(info.name)}</div></div>
          <div class="card-desc">${esc(info.desc)}</div>
          ${note ? `<div class="card-note" ${note.color !== null ? `style="--nc:${cssColor(note.color)}"` : ''}><b>${esc(note.title)}</b>${esc(note.body)}</div>` : ''}
          <div class="card-el">${info.el ? `${info.el} 属性` : ''}</div>
        </button>`;
      })
      .join('');
    this.levelup.innerHTML = `
      <h2 class="screen-title">心灯渐明</h2>
      <p class="sub">Lv ${c.fromLevel} → ${c.fromLevel + 1} · ${how}</p>
      <div class="cards">${cards}</div>
      <div class="levelup-bar">
        <div class="res-chips">${resChips(w, false)}</div>
        <div class="row">
          <button type="button" class="btn small" data-act="reroll" ${w.rerolls > 0 ? '' : 'disabled'}>重抽 ×${w.rerolls}</button>
          <button type="button" class="btn small ghost" data-act="skip">跳过 +10 灯油</button>
        </div>
      </div>`;
    for (const b of this.levelup.querySelectorAll<HTMLButtonElement>('.card')) {
      b.addEventListener('click', () => {
        this.actions.sfxSelect();
        this.actions.send({ k: 'choose', i: Number(b.dataset.i) });
      });
    }
    this.levelup.querySelector('[data-act="reroll"]')?.addEventListener('click', () => this.actions.send({ k: 'reroll' }));
    this.levelup.querySelector('[data-act="skip"]')?.addEventListener('click', () => this.actions.send({ k: 'skip' }));
  }

  private ackChest(): void {
    const ok = this.chest.querySelector<HTMLButtonElement>('[data-act="ok"]');
    if (ok && !ok.disabled) ok.click();
  }

  private renderChest(w: World): void {
    const ch = w.chest;
    if (!ch) return;
    const title = ch.n === 5 ? '五连 · 天降鸿运' : ch.n === 3 ? '三连宝箱' : '宝箱';
    const items = ch.items
      .map((o, i) => {
        const info = optionInfo(w, o);
        return `<div class="chest-item" style="--rc:var(--r-${info.rarity});--c:${cssColor(info.color)};animation-delay:${0.15 + i * 0.28}s">
          <div class="card-icon">${esc(info.icon)}</div><div class="name">${esc(info.name)}</div><div class="what">${o.type === 'evo' ? '进化' : esc(chestKind(o))}</div></div>`;
      })
      .join('');
    this.chest.innerHTML = `<h2 class="screen-title">${title}</h2><div class="chest-items">${items}</div>
      <button type="button" class="btn primary" data-act="ok" disabled>收下</button>`;
    const ok = this.chest.querySelector<HTMLButtonElement>('[data-act="ok"]') as HTMLButtonElement;
    ok.addEventListener('click', () => {
      ok.disabled = true;
      this.actions.send({ k: 'ack' });
    });
    setTimeout(() => (ok.disabled = false), 250 + ch.n * 280);
  }

  private renderEvo(w: World): void {
    const id = w.evo;
    if (!id) return;
    const def = WEAPONS[id];
    this.evoTimer = 2.1;
    this.evo.innerHTML = `<div class="evo-tag">进化</div><div class="evo-name">${esc(def.evoName)}</div>
      <div class="evo-recipe">${esc(def.name)} Lv8 ＋ ${esc(PASSIVES[def.evoPassive].name)} → ${EL[def.el].name} · 天品法器</div>
      <div class="evo-desc">${esc(def.evoDesc)}</div>`;
    this.evo.onclick = () => {
      if (this.evoTimer < 1.6) {
        this.evoTimer = 99;
        this.actions.send({ k: 'ack' });
      }
    };
  }

  private renderPause(w: World): void {
    const ws = w.weapons.map((x) => (x.evo ? WEAPONS[x.id].evoName : `${WEAPONS[x.id].name} Lv${x.lv}`)).join(' · ');
    const ps = w.passives.map((p) => `${PASSIVES[p.id].name} Lv${p.lv}`).join(' · ') || '暂无心法';
    this.pause.innerHTML = `<h2 class="screen-title">暂停</h2>
      <div class="pause-build"><div class="small-text">${esc(ws)}</div><div class="small-text muted">${esc(ps)}</div><div class="res-chips">${resChips(w, false)}</div></div>
      <div class="row"><button type="button" class="btn primary" data-act="resume">继续</button><button type="button" class="btn ghost" data-act="quit">放弃本局</button></div>`;
    this.pause.querySelector('[data-act="resume"]')?.addEventListener('click', () => this.actions.resume());
    this.pause.querySelector('[data-act="quit"]')?.addEventListener('click', () => this.actions.quit());
  }

  private renderResult(w: World): void {
    const won = w.over?.won ?? false;
    const stats: [string, string][] = [
      ['坚持', fmtTime(w.t)],
      ['等级', String(w.level)],
      ['击杀', fmtNum(w.kills)],
      ['最高连斩', String(w.bestCombo)],
      ['进化', String(w.evolutions)],
      ['灯油', `+${Math.round(w.oilBonus)}`],
    ];
    const build = [
      ...w.weapons.map((x) => {
        const def = WEAPONS[x.id];
        return `<div class="build-tile ${x.evo ? 'evo' : ''}" style="--c:${cssColor(EL[def.el].color)}"><i>${def.icon}</i>${esc(x.evo ? def.evoName : def.name)}<small>${x.evo ? '进化' : `Lv${x.lv}`}</small></div>`;
      }),
      ...w.passives.map((p) => {
        const def = PASSIVES[p.id];
        return `<div class="build-tile" style="--c:${cssColor(EL[def.el].color)}"><i>${def.name[0] ?? ''}</i>${esc(def.name)}<small>Lv${p.lv}</small></div>`;
      }),
    ].join('');
    this.result.innerHTML = `
      <div class="result-grid">
        <div class="result-col">
          <div class="result-title ${won ? '' : 'lost'}">${won ? '天明' : '灯灭'}</div>
          <div class="result-sub">${won ? '夜主伏诛，东方既白。' : `撑到了 ${fmtTime(w.t)}，灯火熄于长夜。`}</div>
          <div class="stat-grid">${stats.map(([k, v]) => `<div class="stat-box"><span>${k}</span><b>${v}</b></div>`).join('')}</div>
        </div>
        <div class="result-col">
          <div class="col-label">本局构筑</div>
          <div class="build-grid">${build}</div>
          <div class="res-chips wrap">${resChips(w, true)}</div>
        </div>
      </div>
      <div class="row result-actions">
        <button type="button" class="btn ghost" data-act="home">返回</button>
        <button type="button" class="btn primary big" data-act="again">再来一局</button>
      </div>`;
    this.result.querySelector('[data-act="home"]')?.addEventListener('click', () => this.actions.quit());
    this.result.querySelector('[data-act="again"]')?.addEventListener('click', () => this.actions.again());
  }
}

function chestKind(o: Option): string {
  if (o.type === 'wup') return '法器升级';
  if (o.type === 'pup') return '心法升级';
  if (o.type === 'wnew') return '新法器';
  if (o.type === 'pnew') return '新心法';
  return '补给';
}
