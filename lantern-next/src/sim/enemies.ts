// 妖物存储：按字段分数组（SoA），上千只时也不产生内存垃圾。
// 死亡的槽位放进空闲列表复用；对外用“句柄”（槽位 + 代号）引用某只妖物，
// 槽位被复用后旧句柄自动失效，避免引用到“同一个位置的另一只妖物”。

export const ENEMY_CAP = 2048;
const SLOT_BITS = 11; // 2^11 = 2048
const SLOT_MASK = (1 << SLOT_BITS) - 1;

export class Enemies {
  readonly cap = ENEMY_CAP;

  // 位置与上一步位置（画面插值用）
  readonly x = new Float32Array(ENEMY_CAP);
  readonly y = new Float32Array(ENEMY_CAP);
  readonly px = new Float32Array(ENEMY_CAP);
  readonly py = new Float32Array(ENEMY_CAP);

  readonly r = new Float32Array(ENEMY_CAP);
  readonly hp = new Float32Array(ENEMY_CAP);
  readonly maxHp = new Float32Array(ENEMY_CAP);
  readonly speed = new Float32Array(ENEMY_CAP);
  readonly dmg = new Float32Array(ENEMY_CAP);

  // 状态计时
  readonly flash = new Float32Array(ENEMY_CAP);
  readonly slow = new Float32Array(ENEMY_CAP);
  readonly slowAmt = new Float32Array(ENEMY_CAP);
  readonly frozen = new Float32Array(ENEMY_CAP);
  readonly stun = new Float32Array(ENEMY_CAP);
  readonly kx = new Float32Array(ENEMY_CAP);
  readonly ky = new Float32Array(ENEMY_CAP);
  readonly wob = new Float32Array(ENEMY_CAP);
  readonly cdLamp = new Float32Array(ENEMY_CAP);
  // 灼烧（火·焚）
  readonly burnT = new Float32Array(ENEMY_CAP);
  readonly burnStacks = new Float32Array(ENEMY_CAP);
  readonly burnDps = new Float32Array(ENEMY_CAP);
  readonly burnAcc = new Float32Array(ENEMY_CAP);
  readonly burnShow = new Float32Array(ENEMY_CAP);
  // 夜主的出招计时
  readonly atk = new Float32Array(ENEMY_CAP);
  readonly summon = new Float32Array(ENEMY_CAP);

  readonly type = new Uint8Array(ENEMY_CAP);
  readonly alive = new Uint8Array(ENEMY_CAP);
  readonly gen = new Uint16Array(ENEMY_CAP);

  /** 用过的最大槽位 + 1，遍历时到这里为止 */
  hi = 0;
  count = 0;

  private readonly free = new Int32Array(ENEMY_CAP);
  private freeTop = 0;

  /** 分配一个槽位，满了返回 -1。 */
  alloc(): number {
    let i: number;
    if (this.freeTop > 0) i = this.free[--this.freeTop] as number;
    else if (this.hi < ENEMY_CAP) i = this.hi++;
    else return -1;
    this.alive[i] = 1;
    this.count++;
    this.flash[i] = 0;
    this.slow[i] = 0;
    this.slowAmt[i] = 0;
    this.frozen[i] = 0;
    this.stun[i] = 0;
    this.kx[i] = 0;
    this.ky[i] = 0;
    this.cdLamp[i] = 0;
    this.burnT[i] = 0;
    this.burnStacks[i] = 0;
    this.burnDps[i] = 0;
    this.burnAcc[i] = 0;
    this.burnShow[i] = 0;
    this.atk[i] = 2;
    this.summon[i] = 7;
    return i;
  }

  kill(i: number): void {
    if (!this.alive[i]) return;
    this.alive[i] = 0;
    this.gen[i] = ((this.gen[i] as number) + 1) & 0xffff;
    this.free[this.freeTop++] = i;
    this.count--;
  }

  handle(i: number): number {
    return i | ((this.gen[i] as number) << SLOT_BITS);
  }

  /** 句柄 → 槽位；妖物已死或槽位已被复用时返回 -1。 */
  resolve(h: number): number {
    if (h < 0) return -1;
    const i = h & SLOT_MASK;
    return this.alive[i] && this.gen[i] === h >>> SLOT_BITS ? i : -1;
  }

  clear(): void {
    this.alive.fill(0);
    this.hi = 0;
    this.count = 0;
    this.freeTop = 0;
  }
}
