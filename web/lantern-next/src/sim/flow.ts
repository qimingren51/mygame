// 局面流程：升级选择、重抽、跳过、宝箱、进化演出、结束（移植自旧版 openLevelUp / afterChoice / openChest）。
// 非 play 阶段时间不推进，只处理界面发来的命令。

import { rollChest, rollChoices, applyOption } from './build';
import { endRun } from './combat';
import type { Command, World } from './state';

export function openLevelUp(w: World): void {
  w.phase = 'levelup';
  w.pendingLevels--;
  const r = rollChoices(w);
  w.choice = { options: r.options, lingguang: r.lingguang, fromLevel: w.level - w.pendingLevels - 1 };
  w.bus.emit({ k: 'levelReady' });
}

function openChest(w: World): void {
  w.chestQueue--;
  const items = rollChest(w);
  w.phase = 'chest';
  w.chest = { n: items.length, items };
  w.bus.emit({ k: 'chest', n: items.length });
}

export function afterChoice(w: World): void {
  w.choice = null;
  w.chest = null;
  w.evo = null;
  const evo = w.pendingEvos.shift();
  if (evo) {
    w.phase = 'evo';
    w.evo = evo;
    w.bus.emit({ k: 'evolve', id: evo });
  } else if (w.pendingLevels > 0) openLevelUp(w);
  else if (w.chestQueue > 0) openChest(w);
  else w.phase = 'play';
}

/** 一步结束时检查：胜利、升级、宝箱（与旧版 update() 末尾的顺序一致） */
export function checkFlow(w: World): void {
  if (w.phase !== 'play') return;
  if (w.benchTarget !== null) {
    // 跑分模式不升级、不开宝箱
    w.pendingLevels = 0;
    w.chestQueue = 0;
    return;
  }
  if (w.wonAt >= 0 && w.t >= w.wonAt) endRun(w, true);
  else if (w.pendingLevels > 0) openLevelUp(w);
  else if (w.chestQueue > 0) openChest(w);
}

/** 处理选择阶段的命令。返回 true 表示命令已被消费。 */
export function handleChoiceCommand(w: World, c: Command): boolean {
  if (w.phase === 'levelup' && w.choice) {
    if (c.k === 'choose') {
      const o = w.choice.options[c.i];
      if (!o) return true;
      applyOption(w, o);
      afterChoice(w);
      return true;
    }
    if (c.k === 'reroll') {
      if (w.rerolls > 0) {
        w.rerolls--;
        const r = rollChoices(w);
        w.choice.options = r.options;
        w.choice.lingguang = r.lingguang;
      }
      return true;
    }
    if (c.k === 'skip') {
      w.oilBonus += 10;
      afterChoice(w);
      return true;
    }
  }
  if ((w.phase === 'chest' || w.phase === 'evo') && c.k === 'ack') {
    afterChoice(w);
    return true;
  }
  return false;
}
