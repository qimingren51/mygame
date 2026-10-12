// 模拟 → 画面 / 界面 / 音频 的低频事件。
// 模拟只发出“发生了什么”，不关心怎么显示、怎么发声。
// 事件先排队，每帧由画面层统一取走处理。

export type SimEvent =
  | { k: 'hurt'; amount: number }
  | { k: 'dash' }
  | { k: 'shake'; amount: number }
  | { k: 'flash'; color: number; a: number }
  | { k: 'levelReady' };

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
