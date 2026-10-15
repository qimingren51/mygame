import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

// 旧版逻辑封在浏览器闭包里；直接执行真实函数，替身只负责画面和音效。
test('旧版燃灯清掉贴身弹幕后不再造成伤害', () => {
  const source = readFileSync(new URL('../lantern/game.js', import.meta.url), 'utf8');
  const extract = (name) => {
    const start = source.indexOf(`  function ${name}(`);
    assert.ok(start >= 0);
    return source.slice(start, source.indexOf('\n  }', start) + 4);
  };
  const G = {
    ult: 1, t: 0, effects: [], enemies: [],
    player: { x: 0, y: 0, r: 10 },
    foes: [{ x: 0, y: 0, r: 5, vx: 0, vy: 0, life: 2, dmg: 14 }],
  };
  let damage = 0;
  runInNewContext(`${extract('ultimate')}\n${extract('updateFoes')}\nultimate(); updateFoes(1 / 60);`, {
    G, state: 'play', viewRadius: () => 500, sfxFlash: () => {}, SFX: { ult: () => {} },
    damagePlayer: (n) => { damage += n; },
  });
  assert.equal(G.foes.length, 0);
  assert.equal(G.ult, 0);
  assert.equal(damage, 0);
});
