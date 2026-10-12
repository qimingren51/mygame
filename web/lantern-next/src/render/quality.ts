// 画质自适应：帧时间偏高时逐级降低画质，回落后再逐级恢复。
// 屏幕刷新间隔取最近几秒里最短的帧间隔，所以低电量模式下的 30Hz 不会被误判为卡顿。

export type BloomMode = 'off' | 'baked' | 'filter';

export interface Quality {
  /** 画面分辨率（设备像素 / CSS 像素） */
  res: number;
  /** 光照图比例 */
  ls: number;
  bloom: BloomMode;
}

export interface QualityLocks {
  res?: number;
  ls?: number;
  bloom?: BloomMode;
}

export class QualityScaler {
  readonly levels: Quality[];
  level = 0;
  /** 关掉后保持当前档位不变（调试面板用） */
  auto = true;
  private readonly win = new Float32Array(60);
  private wi = 0;
  private filled = 0;
  private minDt = 1000;
  private minAge = 0;
  private sinceEval = 0;
  private sinceChange = 0;
  private goodRuns = 0;
  private sinceUpgrade = Infinity;
  /** 升档后 10 秒内又降回来的次数；达到 2 次就不再尝试升档 */
  private bounces = 0;

  constructor(maxRes: number, base: BloomMode, locks: QualityLocks) {
    const res0 = locks.res ?? maxRes;
    const ls0 = locks.ls ?? 0.5;
    const bloom0 = locks.bloom ?? base;
    const levels: Quality[] = [{ res: res0, ls: ls0, bloom: bloom0 }];
    const last = () => levels[levels.length - 1] as Quality;
    if (locks.res === undefined) {
      for (const r of [1.5, 1.25]) if (last().res > r + 0.01) levels.push({ ...last(), res: r });
    }
    if (locks.ls === undefined && last().ls > 0.25) levels.push({ ...last(), ls: 0.25 });
    if (locks.bloom === undefined) {
      if (last().bloom === 'filter') levels.push({ ...last(), bloom: 'baked' });
      else if (last().bloom === 'baked') levels.push({ ...last(), bloom: 'off' });
    }
    this.levels = levels;
  }

  get current(): Quality {
    return this.levels[this.level] as Quality;
  }

  /** 每帧调用一次，传入帧间隔（毫秒）；档位变化时返回 true。 */
  sample(dtMs: number): boolean {
    if (dtMs <= 0 || dtMs > 250) return false; // 切后台、调试暂停之类的不算
    this.win[this.wi] = dtMs;
    this.wi = (this.wi + 1) % this.win.length;
    this.filled = Math.min(this.filled + 1, this.win.length);
    this.minAge += dtMs;
    if (dtMs < this.minDt || this.minAge > 4000) {
      this.minDt = Math.max(dtMs, 4);
      this.minAge = 0;
    }
    this.sinceEval += dtMs;
    this.sinceChange += dtMs;
    this.sinceUpgrade += dtMs;
    if (!this.auto || this.sinceEval < 1000 || this.filled < this.win.length) return false;
    this.sinceEval = 0;

    let sum = 0;
    for (let i = 0; i < this.win.length; i++) sum += this.win[i] as number;
    const avg = sum / this.win.length;
    const refresh = Math.max(this.minDt, 1000 / 125);

    if (avg > refresh * 1.3 && avg > 18 && this.sinceChange > 2000 && this.level < this.levels.length - 1) {
      if (this.sinceUpgrade < 10000) this.bounces++;
      this.level++;
      this.changed();
      return true;
    }
    if (avg < refresh * 1.08) {
      this.goodRuns++;
      if (this.goodRuns >= 8 && this.level > 0 && this.bounces < 2 && this.sinceChange > 10000) {
        this.level--;
        this.sinceUpgrade = 0;
        this.changed();
        return true;
      }
    } else {
      this.goodRuns = 0;
    }
    return false;
  }

  private changed(): void {
    this.sinceChange = 0;
    this.filled = 0;
    this.goodRuns = 0;
  }
}
