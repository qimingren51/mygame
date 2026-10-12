// 把模拟事件翻译成声音。画面层取走事件时顺便转给这里。

import type { SimEvent } from '../core/bus';
import { FX } from '../core/fxqueue';
import { sfx } from './sfx';

export function onSimEvent(e: SimEvent): void {
  switch (e.k) {
    case 'hurt':
      sfx.hurt();
      break;
    case 'dash':
      sfx.dash();
      break;
    case 'levelReady':
      sfx.levelUp();
      break;
    case 'shake':
    case 'flash':
      break;
  }
}

export function onFx(code: number): void {
  if (code === FX.HIT) sfx.hit();
  else if (code === FX.KILL) sfx.kill();
  else if (code === FX.GEM_PICK) sfx.gem();
}
