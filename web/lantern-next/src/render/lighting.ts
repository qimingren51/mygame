// 光照图：“灯照见画”的核心。
// 每帧把所有光源（径向渐变贴图，叠加混合）画进一张低分辨率的 RenderTexture，
// 底色是夜色；再把它以正片叠底（multiply）盖在地面和角色上。
// 光照到的地方显出原本的颜色，其余地方只剩夜色。

import { Container, RenderTexture, Sprite, type Renderer, type Texture } from 'pixi.js';
import type { Camera } from './camera';
import { packColor, ParticleLayer } from './particles';

export const NIGHT_AMBIENT = 0x161b2c;

export class Lighting {
  /** 光照图的渲染根节点，不挂在舞台上。它自身保持单位变换：
   *  Pixi 8 的 ParticleContainer 不会叠加根节点自己的变换，镜头变换要放在下一层。 */
  private readonly root = new Container();
  private readonly camLayer = new Container();
  private readonly lights: ParticleLayer;
  private rt: RenderTexture;
  /** 盖在世界上的暗层 */
  readonly darkness: Sprite;
  /** 光照图相对 CSS 像素的比例（0.5 = 半分辨率） */
  scale = 0.5;
  ambient = NIGHT_AMBIENT;
  /** 本帧画了多少个光源（性能面板用） */
  count = 0;
  private readonly texSize: number;
  private readonly lightTex: Texture;
  readonly maxLights: number;

  constructor(lightTex: Texture, maxLights: number) {
    this.lightTex = lightTex;
    this.maxLights = maxLights;
    this.lights = new ParticleLayer(lightTex, maxLights, 'add');
    this.camLayer.addChild(this.lights.view);
    this.root.addChild(this.camLayer);
    this.rt = RenderTexture.create({ width: 8, height: 8, resolution: 1, antialias: false });
    this.darkness = new Sprite(this.rt);
    this.darkness.blendMode = 'multiply';
    this.texSize = lightTex.frame.width;
  }

  resize(cssW: number, cssH: number, scale: number): void {
    this.scale = scale;
    const w = Math.max(8, Math.ceil(cssW * scale));
    const h = Math.max(8, Math.ceil(cssH * scale));
    if (w !== this.rt.width || h !== this.rt.height) {
      // 直接 resize 时，引用它的 Sprite 不会更新自己的尺寸（贴图不是 dynamic），所以换一张新的
      const old = this.rt;
      this.rt = RenderTexture.create({ width: w, height: h, resolution: 1, antialias: false });
      this.darkness.texture = this.rt;
      old.destroy(true);
    }
    this.darkness.scale.set(cssW / w, cssH / h);
  }

  begin(): void {
    this.lights.begin();
  }

  /** 添加一个光源：位置和半径是世界单位，intensity 0~1 */
  add(x: number, y: number, radius: number, color: number, intensity = 1): void {
    const k = (radius * 2) / this.texSize;
    this.lights.add(this.lightTex, x, y, k, k, packColor(color, intensity));
  }

  /** 渲染光照图。要在渲染舞台之前调用。 */
  render(renderer: Renderer, cam: Camera): void {
    this.lights.end();
    this.count = this.lights.count;
    cam.apply(this.camLayer, this.scale);
    renderer.render({ container: this.root, target: this.rt, clear: true, clearColor: this.ambient });
  }
}
