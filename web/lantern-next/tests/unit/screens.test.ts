// 用最小界面替身检查流程实例切换；按钮交互另由浏览器测试覆盖。
import { afterEach, expect, it, vi } from 'vitest';
import { afterChoice, handleChoiceCommand } from '../../src/sim/flow';
import { createRun } from '../../src/sim/step';
import type { World } from '../../src/sim/state';
import { Screens } from '../../src/ui/screens';

function screens(w: World): Screens {
  vi.stubGlobal('document', { createElement: () => ({}), body: { appendChild: () => {} } });
  vi.stubGlobal('addEventListener', () => {});
  return new Screens({
    send: (c) => w.commands.push(c), resume: () => {}, quit: () => {}, again: () => {}, sfxSelect: () => {},
  });
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('连续两个宝箱即使阶段相同也重新渲染', () => {
  const w = createRun({ seed: 7 });
  const ui = screens(w);
  const render = vi.spyOn(ui as unknown as { renderChest(w: World): void }, 'renderChest').mockImplementation(() => {});
  w.chestQueue = 2;
  afterChoice(w);
  const first = w.chest;
  ui.sync(w, 0);
  handleChoiceCommand(w, { k: 'ack' });
  expect(w.chest).not.toBe(first);
  ui.sync(w, 0);
  expect(render).toHaveBeenCalledTimes(2);
  ui.sync(w, 0);
  expect(render).toHaveBeenCalledTimes(2);
});

it('连续相同进化也重新开始演出计时', () => {
  const w = createRun({ seed: 7 });
  const ui = screens(w);
  const id = w.weapons[0]!.id;
  w.pendingEvos.push(id, id);
  afterChoice(w);
  ui.sync(w, 0);
  ui.sync(w, 2.11);
  expect(w.commands).toEqual([{ k: 'ack' }]);
  handleChoiceCommand(w, w.commands.pop()!);
  ui.sync(w, 0.1);
  ui.sync(w, 1.8);
  expect(w.commands).toHaveLength(0);
  ui.sync(w, 0.3);
  expect(w.commands).toEqual([{ k: 'ack' }]);
});
