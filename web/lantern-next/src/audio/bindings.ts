// 把模拟事件翻译成声音。画面层取走事件时顺便转给这里。

import type { SimEvent } from '../core/bus';
import { FX } from '../core/fxqueue';
import { muffle, setIntensity, setMusic } from './music';
import { sfx } from './sfx';

export function onSimEvent(e: SimEvent): void {
  switch (e.k) {
    case 'hurt':
      sfx.hurt();
      break;
    case 'heal':
      sfx.heal();
      break;
    case 'dash':
      sfx.dash();
      break;
    case 'levelReady':
      sfx.levelUp();
      muffle(true);
      break;
    case 'chest':
      sfx.chest(e.n);
      muffle(true);
      break;
    case 'evolve':
      sfx.evolution();
      break;
    case 'resonance':
    case 'taiji':
      sfx.resonance();
      break;
    case 'elite':
    case 'surge':
      sfx.warn(false);
      break;
    case 'boss':
      sfx.warn(true);
      setMusic('boss');
      break;
    case 'combo':
      sfx.combo();
      break;
    case 'ult':
      sfx.ult();
      break;
    case 'sword':
      sfx.sword();
      break;
    case 'bell':
      if (e.big) sfx.bigBell();
      else sfx.bellPulse();
      break;
    case 'seal':
      sfx.seal();
      break;
    case 'blast':
      sfx.blast();
      break;
    case 'pickup':
      if (e.kind === 'bell') sfx.soulBell();
      break;
    case 'intensity':
      setIntensity(e.level);
      break;
    case 'over':
      muffle(true);
      setMusic('none');
      if (e.won) sfx.victory();
      else sfx.defeat();
      break;
    case 'sheng':
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
