// 固定步长主循环：模拟每步固定 1/60 秒，画面按插值系数画在两步之间。
// 这样 30Hz（iPhone 低电量）和 120Hz（ProMotion）屏幕上的玩法完全一致。

export const SIM_DT = 1 / 60;

export class FixedStep {
  /** 一帧最多补几步，防止卡顿后“死亡螺旋”。 */
  maxSteps = 4;
  /** 慢镜头等时间缩放，由画面层控制。 */
  timeScale = 1;
  /** 调试加速倍数。 */
  speed = 1;
  private acc = 0;

  /** 推进真实时间，返回插值系数（0~1）。 */
  advance(realDt: number, step: (dt: number) => void): number {
    this.acc += Math.min(Math.max(realDt, 0), 0.1) * this.timeScale * this.speed;
    const max = this.maxSteps * this.speed;
    let n = 0;
    while (this.acc >= SIM_DT && n < max) {
      step(SIM_DT);
      this.acc -= SIM_DT;
      n++;
    }
    // 追不上时丢弃积压的时间
    if (this.acc >= SIM_DT) this.acc = 0;
    return this.acc / SIM_DT;
  }

  reset(): void {
    this.acc = 0;
  }
}
