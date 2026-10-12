// 加载 Blender / Pillow 生成的图集（public/assets/，由 art/post/pack_atlas.py 打包）。
// 某张图集还没有时，对应部分沿用代码生成的占位图，游戏照常运行。

import { Assets, type Spritesheet, type Texture } from 'pixi.js';
import { DIRS, type ArtSet, type Socket } from './art';
import { createPlaceholderArt } from './placeholders';

/** pack_atlas.py 写在 meta.lantern.assets 里的角色信息 */
interface AssetMeta {
  size?: [number, number];
  anchor?: [number, number];
  anims?: Record<string, { frames: number; fps?: number; dirs?: string[]; stride_units?: number }>;
  sockets?: Record<string, Record<string, Record<string, [number, number][]>>>;
}

interface SheetMeta {
  lantern?: { assets?: Record<string, AssetMeta> };
}

async function tryLoad<T>(url: string): Promise<T | null> {
  try {
    return (await Assets.load<T>(url)) ?? null;
  } catch {
    return null;
  }
}

function frame(sheet: Spritesheet, name: string): Texture {
  const t = sheet.textures[name];
  if (!t) throw new Error(`图集缺少帧 ${name}`);
  return t;
}

function seq(sheet: Spritesheet, prefix: string, n: number): Texture[] {
  const out: Texture[] = [];
  for (let i = 0; i < n; i++) out.push(frame(sheet, `${prefix}_${String(i).padStart(2, '0')}`));
  return out;
}

const sock = (p: [number, number] | undefined): Socket => ({ x: p?.[0] ?? 0, y: p?.[1] ?? 0 });

/** 角色图集（主角、妖物、道具）。缺任何一部分就整张不用：ParticleContainer 要求它们在同一张图上。
 *  先全部取出，确认齐全后再一次性替换。 */
function applyActors(art: ArtSet, sheet: Spritesheet): void {
  const assets = (sheet.data.meta as SheetMeta).lantern?.assets ?? {};
  const hero = assets.hero;
  const idle = hero?.anims?.idle;
  const walk = hero?.anims?.walk;
  if (!hero || !idle || !walk) throw new Error('角色图集缺少 hero 的 idle/walk');
  const lantern = hero.sockets?.lantern;
  const heroArt: ArtSet['hero'] = {
    idle: DIRS.map((d) => seq(sheet, `hero/idle_${d}`, idle.frames)),
    walk: DIRS.map((d) => seq(sheet, `hero/walk_${d}`, walk.frames)),
    lantern: {
      idle: DIRS.map((d) => Array.from({ length: idle.frames }, (_, f) => sock(lantern?.idle?.[d]?.[f]))),
      walk: DIRS.map((d) => Array.from({ length: walk.frames }, (_, f) => sock(lantern?.walk?.[d]?.[f]))),
    },
    strideUnits: walk.stride_units ?? 64,
    idleFps: idle.fps ?? 6,
  };
  const enemies = {} as ArtSet['enemies'];
  for (const name of ['shade', 'wisp'] as const) {
    const m = assets[name];
    const animName = m?.anims ? Object.keys(m.anims)[0] : undefined;
    const a = animName ? m?.anims?.[animName] : undefined;
    if (!m || !animName || !a) throw new Error(`角色图集缺少 ${name}`);
    const prefix = `${name}/${animName}_E`;
    const frames = seq(sheet, prefix, a.frames);
    enemies[name] = {
      frames,
      flash: frames.map((_, i) => frame(sheet, `${prefix}_${String(i).padStart(2, '0')}_flash`)),
      eyes: frames.map((_, i) => sock(m.sockets?.eyes?.[animName]?.E?.[i])),
    };
  }
  // 石块：rock_a、rock_b……各取第一帧
  const rocks = Object.keys(assets)
    .filter((k) => k.startsWith('rock'))
    .sort()
    .map((k) => frame(sheet, `${k}/idle_S_00`));
  if (!rocks.length) throw new Error('角色图集缺少 rock');
  const props: ArtSet['props'] = {
    rocks,
    stoneLantern: frame(sheet, 'stone_lantern/idle_S_00'),
    stoneLanternFlame: sock(assets.stone_lantern?.sockets?.flame?.idle?.S?.[0]),
  };
  art.hero = heroArt;
  art.enemies = enemies;
  art.props = props;
}

export interface LoadReport {
  vfx: boolean;
  ground: boolean;
  paper: boolean;
  actors: boolean;
  errors: string[];
}

/** pack_atlas.py 维护的清单：已经打包好的图集。只加载清单里有的，避免请求不存在的文件。 */
interface AssetIndex {
  atlases?: string[];
  paper?: boolean;
}

export async function loadArt(): Promise<{ art: ArtSet; report: LoadReport }> {
  const art = createPlaceholderArt();
  const report: LoadReport = { vfx: false, ground: false, paper: false, actors: false, errors: [] };
  let index: AssetIndex = {};
  try {
    const res = await fetch('./assets/index.json', { cache: 'no-cache' });
    if (res.ok) index = (await res.json()) as AssetIndex;
  } catch {
    // 没有清单就全部用占位图
  }
  const has = (n: string) => index.atlases?.includes(n) ?? false;
  const [vfx, ground, paper, actors] = await Promise.all([
    has('vfx') ? tryLoad<Spritesheet>('./assets/vfx.json') : null,
    has('ground') ? tryLoad<Spritesheet>('./assets/ground.json') : null,
    index.paper ? tryLoad<Texture>('./assets/paper.webp') : null,
    has('actors') ? tryLoad<Spritesheet>('./assets/actors.json') : null,
  ]);

  if (vfx) {
    try {
      const t = (n: string) => frame(vfx, `vfx/${n}`);
      art.vfx = {
        light: t('light'),
        glow: t('glow'),
        eyes: t('eyes'),
        shadow: t('shadow'),
        spark: t('spark'),
        gem: [t('gem_0'), t('gem_1'), t('gem_2')],
        flame: [t('flame_0'), t('flame_1'), t('flame_2'), t('flame_3')],
        ink: [t('ink_0'), t('ink_1'), t('ink_2')],
        lantern: t('lantern'),
      };
      report.vfx = true;
    } catch (e) {
      report.errors.push(String(e));
    }
  }
  if (ground) {
    try {
      const keys = Object.keys(ground.textures).sort();
      const wash = keys.filter((k) => k.startsWith('ground/wash_')).map((k) => frame(ground, k));
      const grass = keys.filter((k) => k.startsWith('ground/grass_')).map((k) => frame(ground, k));
      if (!wash.length || !grass.length) throw new Error('地面图集缺少 wash 或 grass');
      art.ground.wash = wash;
      art.ground.grass = grass;
      report.ground = true;
    } catch (e) {
      report.errors.push(String(e));
    }
  }
  if (paper) {
    paper.source.addressMode = 'repeat';
    art.ground.paper = paper;
    report.paper = true;
  }
  if (actors) {
    try {
      applyActors(art, actors);
      report.actors = true;
    } catch (e) {
      report.errors.push(String(e));
    }
  }
  return { art, report };
}
