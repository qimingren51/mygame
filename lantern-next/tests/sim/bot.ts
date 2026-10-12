// 无界面机器人：替玩家做升级选择、确认宝箱和进化，并给出一个固定的走位脚本。
// 选卡策略：进化 > 已有法器升级 > 新法器（最多 4 件）> 对应进化的心法 > 心法升级 > 其他。

import { WEAPONS } from '../../src/data/weapons';
import type { InputFrame, Option, World } from '../../src/sim/state';

function score(w: World, o: Option): number {
  switch (o.type) {
    case 'evo':
      return 1000;
    case 'wup':
      return 100;
    case 'wnew':
      return w.weapons.length < 4 ? 90 : 10;
    case 'pnew':
      return w.weapons.some((x) => WEAPONS[x.id].evoPassive === o.id) ? 80 : 30;
    case 'pup':
      return 40;
    default:
      return 1;
  }
}

/** 在选择阶段替玩家下命令；play 阶段什么也不做 */
export function respond(w: World): void {
  if (w.phase === 'levelup' && w.choice) {
    let best = 0;
    let bestScore = -1;
    w.choice.options.forEach((o, i) => {
      const s = score(w, o);
      if (s > bestScore) {
        bestScore = s;
        best = i;
      }
    });
    w.commands.push({ k: 'choose', i: best });
  } else if (w.phase === 'chest' || w.phase === 'evo') {
    w.commands.push({ k: 'ack' });
  }
}

/** 走位：绕大圈，偶尔变向；每 2 秒闪避一次 */
export function botInput(w: World, input: InputFrame): void {
  const a = w.tick * 0.01;
  input.mx = Math.cos(a);
  input.my = Math.sin(a * 0.7);
  if (w.tick % 120 === 0) w.commands.push({ k: 'dash' });
}
