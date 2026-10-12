// 把模拟事件翻译成 HUD 提示条。

import type { SimEvent } from '../core/bus';
import { EL } from '../data/elements';
import { ELITE_INFO } from '../data/enemies';
import type { Hud } from './hud';

export function toastFor(hud: Hud, e: SimEvent): void {
  switch (e.k) {
    case 'resonance': {
      const d = EL[e.el];
      hud.toast(`${d.name} · ${d.res} ${e.points}`, `共鸣激活：${d.tiers[e.tier - 1] ?? ''}`, d.color, e.tier === 3);
      break;
    }
    case 'sheng':
      hud.toast(`相生 · ${e.name}`, e.desc, EL[e.el].color);
      break;
    case 'taiji':
      hud.toast('五行圆满 · 太极', '每 30 秒全屏轮转五行之力', 0xffd98a, true);
      break;
    case 'elite': {
      const info = ELITE_INFO[e.type];
      hud.toast(e.count > 1 ? `${info.label} ×${e.count}` : info.label, '击败它获得宝箱', info.color);
      break;
    }
    case 'surge':
      hud.toast('妖潮来袭', '撑过这 30 秒', 0xff6b5a, true);
      break;
    case 'boss':
      hud.toast('夜主 · 九尾 降临', '击败它，迎来天明', 0xffb46b, true);
      break;
    case 'combo':
      hud.toast(`连斩 ${e.n}`, '', 0xffd98a, e.n >= 500);
      break;
    case 'pickup':
      if (e.kind === 'bell') hud.toast('引魂铃', '魂火尽归', 0x5fd4c4);
      break;
    default:
      break;
  }
}
