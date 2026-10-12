// 符剑飞剑：按字段分数组存储，删除时用末尾元素填补空位。
// 每把剑记住最近命中过的妖物（句柄），穿透时不会对同一只重复造成伤害。

export const SHOT_CAP = 512;
/** 每把剑记住的最近命中数；剑穿过一只妖物只要几帧，记最近 16 个足够 */
export const SHOT_HIT_MEMORY = 16;

export class Shots {
  readonly x = new Float32Array(SHOT_CAP);
  readonly y = new Float32Array(SHOT_CAP);
  readonly px = new Float32Array(SHOT_CAP);
  readonly py = new Float32Array(SHOT_CAP);
  readonly vx = new Float32Array(SHOT_CAP);
  readonly vy = new Float32Array(SHOT_CAP);
  readonly dmg = new Float32Array(SHOT_CAP);
  readonly pierce = new Float32Array(SHOT_CAP);
  readonly life = new Float32Array(SHOT_CAP);
  /** 追踪目标的句柄，-1 表示不追踪 */
  readonly target = new Int32Array(SHOT_CAP);
  /** 1 = 进化后的大剑 */
  readonly big = new Uint8Array(SHOT_CAP);
  /** 1 = 金·锐 6 点追加的飞剑（不再触发追加） */
  readonly bonus = new Uint8Array(SHOT_CAP);
  readonly hits = new Int32Array(SHOT_CAP * SHOT_HIT_MEMORY);
  readonly hitN = new Uint8Array(SHOT_CAP);
  n = 0;

  add(x: number, y: number, vx: number, vy: number, dmg: number, pierce: number, target: number, big: boolean, bonus: boolean): void {
    if (this.n >= SHOT_CAP) return;
    const i = this.n++;
    this.x[i] = x;
    this.y[i] = y;
    this.px[i] = x;
    this.py[i] = y;
    this.vx[i] = vx;
    this.vy[i] = vy;
    this.dmg[i] = dmg;
    this.pierce[i] = pierce;
    this.life[i] = 1.5;
    this.target[i] = target;
    this.big[i] = big ? 1 : 0;
    this.bonus[i] = bonus ? 1 : 0;
    this.hitN[i] = 0;
  }

  hasHit(i: number, handle: number): boolean {
    const n = Math.min(this.hitN[i] as number, SHOT_HIT_MEMORY);
    const o = i * SHOT_HIT_MEMORY;
    for (let k = 0; k < n; k++) if (this.hits[o + k] === handle) return true;
    return false;
  }

  markHit(i: number, handle: number): void {
    const n = this.hitN[i] as number;
    this.hits[i * SHOT_HIT_MEMORY + (n % SHOT_HIT_MEMORY)] = handle;
    this.hitN[i] = n >= 255 ? SHOT_HIT_MEMORY : n + 1;
  }

  remove(i: number): void {
    const last = --this.n;
    if (i === last) return;
    this.x[i] = this.x[last] as number;
    this.y[i] = this.y[last] as number;
    this.px[i] = this.px[last] as number;
    this.py[i] = this.py[last] as number;
    this.vx[i] = this.vx[last] as number;
    this.vy[i] = this.vy[last] as number;
    this.dmg[i] = this.dmg[last] as number;
    this.pierce[i] = this.pierce[last] as number;
    this.life[i] = this.life[last] as number;
    this.target[i] = this.target[last] as number;
    this.big[i] = this.big[last] as number;
    this.bonus[i] = this.bonus[last] as number;
    this.hitN[i] = this.hitN[last] as number;
    this.hits.copyWithin(i * SHOT_HIT_MEMORY, last * SHOT_HIT_MEMORY, (last + 1) * SHOT_HIT_MEMORY);
  }

  clear(): void {
    this.n = 0;
  }
}
