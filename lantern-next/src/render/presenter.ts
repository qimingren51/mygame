// 画面总控：每帧读取模拟状态（只读），按插值系数画出世界。
// 图层从下到上：宣纸 → 地面装饰 → 影子 → 墨迹 → 角色（y 排序）→ 暗层（光照图）
//             → 火焰 → 自发光（叠加，可加辉光）→ 伤害数字 → 屏幕闪光。

import { AdvancedBloomFilter } from 'pixi-filters/advanced-bloom';
import { Container, Rectangle, Sprite, Texture, type Renderer } from 'pixi.js';
import { FX, FX_CRIT } from '../core/fxqueue';
import { SIM_DT } from '../core/loop';
import { TAU } from '../core/math';
import { LIGHT_RADIUS } from '../data/balance';
import { ENEMY, ENEMY_TYPES } from '../data/enemies';
import { setView, type World } from '../sim/state';
import { ParticleActors, SpriteActors, type ActorBatch, type ActorMode } from './actors';
import type { ActorAnim, ArtSet } from './art';
import { Camera } from './camera';
import { DamageNumbers, FlashLights, FxParticles } from './fx';
import { Ground } from './ground';
import { Lighting } from './lighting';
import { packColor, ParticleLayer } from './particles';
import type { BloomMode, Quality } from './quality';

const LANTERN_LIGHT = 0xffe0b0;
const FLAME_LIGHT = 0xffa860;
const SOUL_LIGHT = 0xbfefff;
const STONE_LIGHT = 0xffc890;
const WARM_CORE = 0xffd9a0;

/** 主角朝向切换的滞后角度：超过扇区边界这么多才换方向，避免斜着走时来回闪 */
const DIR_HYSTERESIS = 0.12;

export interface PresenterOptions {
  actors: ActorMode;
  maxLights: number;
  /** 场上魂火最多给多少个发光（其余只画不发光） */
  gemLights: number;
}

export interface FrameStats {
  actors: number;
  lights: number;
  glow: number;
  particles: number;
}

export class Presenter {
  readonly stage = new Container();
  readonly cam = new Camera();
  private readonly world = new Container();
  private readonly worldTop = new Container();
  private readonly ground: Ground;
  private readonly shadows: ParticleLayer;
  private readonly ink: ParticleLayer;
  readonly actors: ActorBatch;
  readonly lighting: Lighting;
  private readonly flames: ParticleLayer;
  private readonly glowRoot = new Container();
  private readonly glow: ParticleLayer;
  private readonly numbers = new DamageNumbers();
  private readonly fxp: FxParticles;
  private readonly flashLights = new FlashLights();
  private readonly screenFlash = new Sprite(Texture.WHITE);
  private flashA = 0;
  private bloom: BloomMode = 'baked';
  private bloomFilter: AdvancedBloomFilter | null = null;
  private readonly inv: number;
  private readonly anims: ActorAnim[];
  private readonly eyes: { x: number; y: number }[];
  private readonly eyeColor: number[];
  private readonly typeScale: number[];
  private heroDir = 2;
  private walkDist = 0;
  private lastHX = 0;
  private lastHY = 0;
  private time = 0;
  readonly stats: FrameStats = { actors: 0, lights: 0, glow: 0, particles: 0 };
  /** 调试开关 */
  showNumbers = true;
  lightsOn = true;
  private readonly art: ArtSet;
  private readonly opts: PresenterOptions;

  constructor(art: ArtSet, opts: PresenterOptions) {
    this.art = art;
    this.opts = opts;
    this.inv = 1 / art.pxPerUnit;
    const vfxTex = art.vfx.light;
    this.ground = new Ground(art);
    this.shadows = new ParticleLayer(vfxTex, 4096);
    this.ink = new ParticleLayer(vfxTex, 2048);
    this.actors = opts.actors === 'A' ? new ParticleActors(art.hero.idle[0]?.[0] as Texture) : new SpriteActors();
    this.lighting = new Lighting(art.vfx.light, opts.maxLights);
    this.flames = new ParticleLayer(vfxTex, 256);
    this.glow = new ParticleLayer(vfxTex, 8192, 'add');

    this.world.addChild(this.ground.paper, this.ground.decals, this.shadows.view, this.ink.view, this.actors.view);
    this.glowRoot.addChild(this.glow.view);
    this.worldTop.addChild(this.flames.view, this.glowRoot);
    this.stage.addChild(this.world, this.lighting.darkness, this.worldTop, this.numbers.layer.view, this.screenFlash);
    this.screenFlash.alpha = 0;

    // 每种妖物用哪套贴图；没有专属美术的先借用影妖，按体型缩放
    const shade = art.enemies.shade;
    const wisp = art.enemies.wisp;
    this.anims = ENEMY_TYPES.map((t) => (t === 'wisp' ? wisp : shade));
    this.eyes = ENEMY_TYPES.map((t) => (t === 'wisp' ? wisp.eyes : shade.eyes));
    this.eyeColor = ENEMY_TYPES.map((t) => ENEMY[t].eye);
    this.typeScale = ENEMY_TYPES.map((t) => (t === 'wisp' || t === 'shade' ? 1 : ENEMY[t].r / ENEMY.shade.r));
    this.fxp = new FxParticles(art);
  }

  /** 尺寸或画质变化时调用 */
  resize(renderer: Renderer, cssW: number, cssH: number, q: Quality, world: World): void {
    renderer.resize(cssW, cssH, q.res);
    this.cam.resize(cssW, cssH, q.res);
    this.lighting.resize(cssW, cssH, q.ls);
    this.screenFlash.width = cssW;
    this.screenFlash.height = cssH;
    this.setBloom(q.bloom, cssW, cssH);
    setView(world, this.cam.viewW, this.cam.viewH);
  }

  private setBloom(mode: BloomMode, cssW: number, cssH: number): void {
    this.bloom = mode;
    if (mode === 'filter') {
      this.bloomFilter ??= new AdvancedBloomFilter({ threshold: 0.2, bloomScale: 1.1, brightness: 1, blur: 6, quality: 4 });
      this.bloomFilter.blendMode = 'add';
      this.glowRoot.filters = [this.bloomFilter];
      this.glowRoot.filterArea = new Rectangle(0, 0, cssW, cssH);
    } else {
      this.glowRoot.filters = null;
    }
  }

  /** 画一帧。alpha 是模拟的插值系数，dt 是真实经过的秒数。 */
  frame(renderer: Renderer, w: World, alpha: number, dt: number): void {
    this.time += dt;
    const inv = this.inv;
    const p = w.player;
    const hx = p.px + (p.x - p.px) * alpha;
    const hy = p.py + (p.y - p.py) * alpha;

    this.consumeEvents(w);

    const cam = this.cam;
    cam.update(hx, hy, dt);
    cam.apply(this.world);
    cam.apply(this.worldTop);
    this.ground.update(cam);

    this.actors.begin();
    this.shadows.begin();
    this.ink.begin();
    this.flames.begin();
    this.glow.begin();
    this.lighting.begin();

    const shadowTex = this.art.vfx.shadow;
    const shadowW = shadowTex.frame.width;
    const baked = this.bloom === 'baked';

    // ---- 主角
    const hero = this.art.hero;
    if (p.moving) this.heroDir = pickDir(this.heroDir, p.faceX, p.faceY);
    const moved = Math.hypot(hx - this.lastHX, hy - this.lastHY);
    this.lastHX = hx;
    this.lastHY = hy;
    let heroTex: Texture;
    let sock: { x: number; y: number };
    if (p.moving || p.dashT > 0) {
      this.walkDist += Math.min(moved, 30);
      const frames = hero.walk[this.heroDir] as Texture[];
      const f = Math.floor((this.walkDist / 64) * frames.length) % frames.length;
      heroTex = frames[f] as Texture;
      sock = hero.lantern.walk[this.heroDir]?.[f] ?? { x: 0, y: 0 };
    } else {
      const frames = hero.idle[this.heroDir] as Texture[];
      const f = Math.floor(this.time * 6) % frames.length;
      heroTex = frames[f] as Texture;
      sock = hero.lantern.idle[this.heroDir]?.[f] ?? { x: 0, y: 0 };
    }
    const hurtBlink = p.iframe > 0 && p.dashT <= 0 && Math.sin(this.time * 40) > 0;
    this.actors.push(heroTex, hx, hy, inv, inv, hy, 0xffffff, hurtBlink ? 0.45 : 1);
    this.shadows.add(shadowTex, hx, hy, (p.r * 2.4) / shadowW, (p.r * 2.4) / shadowW, packColor(0xffffff, 0.8));
    const lx = hx + sock.x * inv;
    const ly = hy + sock.y * inv;
    const flicker = 1 + Math.sin(this.time * 13) * 0.02 + Math.sin(this.time * 7.3) * 0.02;
    this.lighting.add(lx, ly, LIGHT_RADIUS * Math.sqrt(w.stats.area) * flicker, LANTERN_LIGHT, 1);
    const lan = this.art.vfx.lantern;
    this.glow.add(lan, lx, ly, inv, inv, packColor(WARM_CORE, 0.9));
    if (baked) this.glow.add(this.art.vfx.glow, lx, ly, 0.9, 0.9, packColor(WARM_CORE, 0.45));

    // ---- 妖物
    const en = w.enemies;
    const t = this.time;
    const glowTex = this.art.vfx.glow;
    const eyesTex = this.art.vfx.eyes;
    for (let i = 0; i < en.hi; i++) {
      if (!en.alive[i]) continue;
      const ox = en.px[i] as number;
      const oy = en.py[i] as number;
      const ex = ox + ((en.x[i] as number) - ox) * alpha;
      const ey = oy + ((en.y[i] as number) - oy) * alpha;
      if (!cam.visible(ex, ey, 80)) continue;
      const type = en.type[i] as number;
      const anim = this.anims[type] as ActorAnim;
      const k = this.typeScale[type] as number;
      const n = anim.frames.length;
      const f = Math.floor(t * 8 + i * 0.37) % n;
      const flash = (en.flash[i] as number) > 0;
      const tex = (flash ? anim.flash[f] : anim.frames[f]) as Texture;
      const mirror = hx < ex ? -1 : 1;
      const bob = Math.sin(t * 3 + i * 1.7) * 1.5;
      this.actors.push(tex, ex, ey + bob, inv * k * mirror, inv * k, ey);
      const r = en.r[i] as number;
      this.shadows.add(shadowTex, ex, ey, (r * 1.8) / shadowW, (r * 1.8) / shadowW, packColor(0xffffff, 0.55));
      const eye = this.eyes[type] as { x: number; y: number };
      const eyeX = ex + eye.x * inv * k * mirror;
      const eyeY = ey + bob + eye.y * inv * k;
      const ec = this.eyeColor[type] as number;
      this.glow.add(eyesTex, eyeX, eyeY, inv * k, inv * k, packColor(ec, flash ? 0.4 : 1));
      if (baked) this.glow.add(glowTex, eyeX, eyeY, 0.32 * k, 0.2 * k, packColor(ec, 0.35));
    }

    // ---- 竖立的道具
    const props = this.ground.props;
    const pr = this.art.props;
    for (const prop of props) {
      if (!cam.visible(prop.x, prop.y, 100)) continue;
      const tex = prop.kind === 'rock' ? (pr.rocks[prop.variant] as Texture) : pr.stoneLantern;
      this.actors.push(tex, prop.x, prop.y, inv * (prop.flip ? -1 : 1), inv, prop.y);
      if (prop.kind === 'stoneLantern') {
        const fx = prop.x + pr.stoneLanternFlame.x * inv * (prop.flip ? -1 : 1);
        const fy = prop.y + pr.stoneLanternFlame.y * inv;
        const fl = 1 + Math.sin(t * 9 + prop.phase) * 0.04 + Math.sin(t * 5.1 + prop.phase * 2) * 0.04;
        this.lighting.add(fx, fy + 10, 120 * fl, STONE_LIGHT, 0.9);
        this.glow.add(lan, fx, fy, inv * 0.8, inv * 0.8, packColor(WARM_CORE, 0.85));
        if (baked) this.glow.add(glowTex, fx, fy, 0.7, 0.7, packColor(WARM_CORE, 0.4));
      }
    }

    // ---- 灯火（绕身的火焰）
    const L = w.lamp;
    if (L.count > 0) {
      const omega = 3.2 + L.lv * 0.12;
      const base = L.angle - (1 - alpha) * omega * SIM_DT;
      const flameTex = this.art.vfx.flame;
      const fs = (L.size / 10) * inv;
      for (let f = 0; f < L.count; f++) {
        const a = base + (f * TAU) / L.count;
        const fx = hx + Math.cos(a) * L.radius;
        const fy = hy + Math.sin(a) * L.radius;
        const tex = flameTex[Math.floor(t * 12 + f) % flameTex.length] as Texture;
        this.flames.add(tex, fx, fy, fs, fs, packColor(0xffffff, 1));
        if (baked) this.glow.add(glowTex, fx, fy - 3, 0.55, 0.55, packColor(FLAME_LIGHT, 0.5));
        this.lighting.add(fx, fy, 64, FLAME_LIGHT, 0.75);
      }
    }

    // ---- 魂火
    const g = w.gems;
    const gemTex = this.art.vfx.gem;
    let gemLights = this.opts.gemLights;
    for (let i = 0; i < g.n; i++) {
      const ox = g.px[i] as number;
      const oy = g.py[i] as number;
      const gx = ox + ((g.x[i] as number) - ox) * alpha;
      const gy = oy + ((g.y[i] as number) - oy) * alpha;
      if (!cam.visible(gx, gy, 30)) continue;
      const v = g.v[i] as number;
      const tier = v >= 10 ? 2 : v >= 3 ? 1 : 0;
      const bob = Math.sin(t * 4 + i) * 1.5 - 4;
      this.glow.add(gemTex[tier] as Texture, gx, gy + bob, inv, inv, packColor(SOUL_LIGHT, 0.95));
      if (gemLights > 0) {
        gemLights--;
        this.lighting.add(gx, gy, 26 + tier * 6, SOUL_LIGHT, 0.5);
      }
    }

    // ---- 特效
    this.fxp.update(dt);
    this.fxp.draw(this.ink, this.glow);
    this.flashLights.update(dt, this.lighting);
    this.numbers.layer.view.visible = this.showNumbers;
    if (this.showNumbers) this.numbers.draw(dt, cam);
    if (this.flashA > 0) {
      this.flashA = Math.max(0, this.flashA - dt * 3);
      this.screenFlash.alpha = this.flashA;
    } else this.screenFlash.alpha = 0;

    this.actors.end();
    this.shadows.end();
    this.ink.end();
    this.flames.end();
    this.glow.end();
    this.lighting.darkness.visible = this.lightsOn;
    if (this.lightsOn) this.lighting.render(renderer, cam);
    renderer.render(this.stage);

    this.stats.actors = this.actors.count;
    this.stats.lights = this.lighting.count;
    this.stats.glow = this.glow.count;
    this.stats.particles = this.fxp.count;
  }

  private consumeEvents(w: World): void {
    w.bus.drain((e) => {
      switch (e.k) {
        case 'shake':
          this.cam.shake(e.amount);
          break;
        case 'flash':
          this.screenFlash.tint = e.color;
          this.flashA = Math.max(this.flashA, e.a);
          break;
        case 'hurt':
        case 'dash':
        case 'levelReady':
          break;
      }
    });
    const p = w.player;
    w.fx.drain((code, x, y, a, b) => {
      if (code === FX.HIT) {
        this.fxp.hit(x, y, p.x, p.y);
        this.numbers.add(x, y, a, (b & FX_CRIT) !== 0);
      } else if (code === FX.KILL) {
        const eye = this.eyeColor[a] ?? 0xffffff;
        this.fxp.kill(x, y, eye, b === 1);
        this.flashLights.add(x, y, b === 1 ? 140 : 70, eye, b === 1 ? 0.6 : 0.3);
      } else if (code === FX.GEM_PICK) {
        this.fxp.spark(x, y - 4, SOUL_LIGHT, 2);
      }
    });
  }
}

/** 由朝向向量选 8 个方向之一，带滞后。0=东，顺时针（屏幕 y 向下）。 */
export function pickDir(cur: number, fx: number, fy: number): number {
  const a = Math.atan2(fy, fx);
  const cand = Math.round(a / (Math.PI / 4)) & 7;
  if (cand === cur) return cur;
  let d = a - (cur * Math.PI) / 4;
  d = Math.atan2(Math.sin(d), Math.cos(d));
  return Math.abs(d) > Math.PI / 8 + DIR_HYSTERESIS ? cand : cur;
}
