// 模拟 → 画面 / 界面 / 音频 的低频事件。
// 模拟只发出“发生了什么”，不关心怎么显示、怎么发声。
// 事件先排队，每帧由画面层统一取走处理。

import type { ElementId } from '../data/elements';
import type { PickupKind } from '../sim/state';
import type { WeaponId } from '../data/weapons';

export type SimEvent =
  | { k: 'hurt'; amount: number }
  | { k: 'heal'; amount: number }
  | { k: 'dash' }
  | { k: 'shake'; amount: number }
  | { k: 'flash'; color: number; a: number }
  /** 进入升级选择 */
  | { k: 'levelReady' }
  /** 宝箱揭晓 */
  | { k: 'chest'; n: number }
  /** 进化演出开始 */
  | { k: 'evolve'; id: WeaponId }
  | { k: 'resonance'; el: ElementId; tier: number; points: number }
  | { k: 'sheng'; name: string; desc: string; el: ElementId }
  | { k: 'taiji' }
  | { k: 'pickup'; kind: PickupKind }
  | { k: 'elite'; type: 'fox' | 'ghoul' | 'stonelord'; count: number }
  | { k: 'surge' }
  | { k: 'boss' }
  | { k: 'combo'; n: number }
  | { k: 'ult' }
  | { k: 'sword' }
  | { k: 'bell'; big: boolean }
  | { k: 'seal' }
  | { k: 'blast' }
  | { k: 'intensity'; level: number }
  | { k: 'over'; won: boolean };

export class EventBus {
  private queue: SimEvent[] = [];

  emit(e: SimEvent): void {
    this.queue.push(e);
  }

  /** 取走本帧的全部事件。 */
  drain(handler: (e: SimEvent) => void): void {
    const q = this.queue;
    if (!q.length) return;
    this.queue = [];
    for (const e of q) handler(e);
  }

  clear(): void {
    this.queue.length = 0;
  }
}
