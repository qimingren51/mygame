// 提灯夜行 · 主角绘制（斜俯视）
// 与 game.js 分开，方便单独渲染预览图检查造型。
// 坐标约定：(x, y) 为身体中心，脚底在 y + 10；side = 1 朝右，-1 朝左。
const LanternSprites = (() => {
  'use strict';

  const TAU = Math.PI * 2;
  const SCALE = 1.2; // 只放大画面，碰撞范围不变

  const C = {
    skin: '#EBCFA6',
    hair: '#16161F',
    robe: '#33407A',
    robeDark: '#252E58',
    robeLine: '#1B2244',
    sleeve: '#3D4B8C',
    collar: '#E9E2D0',
    sash: '#9A3B2F',
    pants: '#1C2033',
    shoe: '#0D0F1A',
    hatLight: '#A88350',
    hatDark: '#7A5A34',
    brim: '#8E7044',
    brimEdge: '#B8925A',
    brimUnder: '#4E3A22',
    scarf: '#C9392F',
    pole: '#6B5332',
  };

  function pose(side, moving, t) {
    const bob = moving ? Math.abs(Math.sin(t * 10)) * 1.4 : Math.sin(t * 2) * 0.35;
    const step = moving ? Math.sin(t * 10) : 0;
    // 灯杆顶端相对身体中心的位置
    return { bob, step, tipX: side * 19 * SCALE, tipY: (-10 - bob) * SCALE };
  }

  function ellipse(ctx, x, y, rx, ry, fill) {
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.ellipse(x, y, rx, ry, 0, 0, TAU);
    ctx.fill();
  }

  function leg(ctx, x, lift) {
    ctx.fillStyle = C.pants;
    ctx.fillRect(x - 1.6, 3 - lift, 3.2, 6);
    ellipse(ctx, x + 0.8, 9.3 - lift, 2.4, 1.3, C.shoe);
  }

  function drawHero(ctx, x, y, side, moving, t, alpha = 1) {
    const { bob, step } = pose(side, moving, t);
    ctx.save();
    ctx.globalAlpha = alpha;
    ellipse(ctx, x, y + 10.5 * SCALE, 10 * SCALE, 3.2 * SCALE, 'rgba(0, 0, 0, 0.4)');
    ctx.translate(x, y);
    ctx.scale(side * SCALE, SCALE);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // 腿：脚踩在地上，不随身体起伏
    const lift = moving ? 1.6 : 0;
    leg(ctx, -2.5 - step * 2.2, Math.max(0, -step) * lift);
    leg(ctx, 2 + step * 2.2, Math.max(0, step) * lift);

    ctx.translate(0, -bob);

    // 红绸围巾，在身后飘
    const w1 = Math.sin(t * 7) * 1.6;
    const w2 = Math.sin(t * 7 + 1.3) * 2.2;
    const len = moving ? 15 : 10;
    ctx.fillStyle = C.scarf;
    ctx.beginPath();
    ctx.moveTo(-1, -7.6);
    ctx.quadraticCurveTo(-len * 0.5, -9.5 + w1, -len, -6.5 + w2);
    ctx.lineTo(-len + 1.2, -4 + w2);
    ctx.quadraticCurveTo(-len * 0.5, -6 + w1, -1, -4.8);
    ctx.closePath();
    ctx.fill();

    // 后侧袖子
    const swing = moving ? -step * 0.35 : 0;
    ctx.save();
    ctx.translate(-3.5, -5.5);
    ctx.rotate(0.35 + swing);
    ctx.fillStyle = C.robeDark;
    ctx.beginPath();
    ctx.roundRect(-2.4, 0, 4.8, 8.5, 2);
    ctx.fill();
    ctx.restore();

    // 长袍：亮面 + 背光面
    ctx.fillStyle = C.robe;
    ctx.beginPath();
    ctx.moveTo(-6, -7);
    ctx.quadraticCurveTo(0, -8.8, 6, -7);
    ctx.lineTo(9, 4.5);
    ctx.quadraticCurveTo(0, 7, -9, 4.5);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = C.robeDark;
    ctx.beginPath();
    ctx.moveTo(-6, -7);
    ctx.quadraticCurveTo(-3, -7.9, -1, -8);
    ctx.lineTo(-2, 6.2);
    ctx.quadraticCurveTo(-6, 5.8, -9, 4.5);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = C.robeLine;
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    ctx.moveTo(-6, -7);
    ctx.quadraticCurveTo(0, -8.8, 6, -7);
    ctx.lineTo(9, 4.5);
    ctx.quadraticCurveTo(0, 7, -9, 4.5);
    ctx.closePath();
    ctx.stroke();

    // 交领
    ctx.fillStyle = C.collar;
    ctx.beginPath();
    ctx.moveTo(-1.2, -7.8);
    ctx.lineTo(3, -2.4);
    ctx.lineTo(3.9, -3.6);
    ctx.lineTo(0.6, -8.1);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = C.robeLine;
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    ctx.moveTo(4.2, -7.2);
    ctx.lineTo(2.2, -3.2);
    ctx.stroke();

    // 腰带与垂下的带尾
    ctx.fillStyle = C.sash;
    ctx.fillRect(-7.8, -1.6, 16.4, 2.4);
    ctx.beginPath();
    ctx.moveTo(5, 0.6);
    ctx.lineTo(6.6, 0.6);
    ctx.lineTo(7.2 + Math.sin(t * 5) * 0.5, 5);
    ctx.lineTo(5.6, 5);
    ctx.closePath();
    ctx.fill();

    // 头：后脑头发 + 发髻，脸朝前
    ellipse(ctx, -5.2, -11.2, 2.5, 2.5, C.hair);
    ellipse(ctx, 1, -12, 6, 6, C.skin);
    ctx.fillStyle = C.hair;
    ctx.beginPath();
    ctx.arc(1, -12, 6, Math.PI * 0.6, Math.PI * 1.55);
    ctx.lineTo(1, -12);
    ctx.closePath();
    ctx.fill();
    // 眼睛与腮红
    ellipse(ctx, 4.2, -11.4, 0.9, 1.4, '#1A1A24');
    ellipse(ctx, 4.5, -11.9, 0.35, 0.35, '#FFFFFF');
    ellipse(ctx, 4.6, -9.2, 1.3, 0.7, 'rgba(230, 120, 110, 0.5)');

    // 斗笠：檐下阴影、宽檐、锥顶（亮面 + 背光面）
    ellipse(ctx, 1, -15.4, 12, 2.4, 'rgba(0, 0, 0, 0.28)');
    ctx.fillStyle = C.brim;
    ctx.strokeStyle = C.brimEdge;
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    ctx.ellipse(0.5, -16.8, 13.5, 3.4, 0, 0, TAU);
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = C.brimUnder;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.ellipse(0.5, -16.4, 13.5, 3.4, 0, 0.15, Math.PI - 0.15);
    ctx.stroke();
    ctx.fillStyle = C.hatLight;
    ctx.beginPath();
    ctx.moveTo(-10.5, -17.4);
    ctx.lineTo(0.5, -26);
    ctx.lineTo(11.5, -17.4);
    ctx.quadraticCurveTo(0.5, -14.8, -10.5, -17.4);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = C.hatDark;
    ctx.beginPath();
    ctx.moveTo(-10.5, -17.4);
    ctx.lineTo(0.5, -26);
    ctx.lineTo(-1.2, -15.7);
    ctx.quadraticCurveTo(-5.5, -15.9, -10.5, -17.4);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = 'rgba(74, 56, 34, 0.55)';
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    ctx.moveTo(0.5, -26);
    ctx.lineTo(4.5, -15.6);
    ctx.moveTo(0.5, -26);
    ctx.lineTo(8.5, -16.4);
    ctx.moveTo(0.5, -26);
    ctx.lineTo(-5, -16.2);
    ctx.stroke();
    ellipse(ctx, 0.5, -26, 1, 1, C.brimUnder);

    // 前侧宽袖与手，握住灯杆
    ctx.fillStyle = C.sleeve;
    ctx.strokeStyle = C.robeLine;
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    ctx.moveTo(1.2, -6.8);
    ctx.quadraticCurveTo(7, -6.4, 9.6, -3.4);
    ctx.lineTo(8.6, -0.4);
    ctx.quadraticCurveTo(5, -1.2, 0.8, -2.6);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = C.pole;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(8.6, -0.8);
    ctx.lineTo(19, -10);
    ctx.stroke();
    ellipse(ctx, 9.8, -2, 1.5, 1.5, C.skin);

    ctx.restore();
  }

  // 红纸灯笼，挂在灯杆顶端，走动时向后荡
  function drawLantern(ctx, x, y, side, moving, t) {
    const { tipX, tipY } = pose(side, moving, t);
    const px = x + tipX;
    const py = y + tipY;
    const swing = Math.sin(t * 3) * 0.12 - (moving ? side * 0.3 : 0);
    const lx = px + Math.sin(swing) * 8 * SCALE;
    const ly = py + Math.cos(swing) * 8 * SCALE;
    const flicker = 1 + Math.sin(t * 13) * 0.05 + Math.sin(t * 7.3) * 0.04;
    const g = ctx.createRadialGradient(lx, ly, 0, lx, ly, 28 * flicker);
    g.addColorStop(0, 'rgba(255, 220, 160, 0.75)');
    g.addColorStop(0.35, 'rgba(255, 140, 80, 0.3)');
    g.addColorStop(1, 'rgba(255, 140, 80, 0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(lx, ly, 28 * flicker, 0, TAU);
    ctx.fill();
    ctx.strokeStyle = '#3A2E24';
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    ctx.moveTo(px, py);
    ctx.lineTo(lx, ly - 6 * SCALE);
    ctx.stroke();
    ctx.save();
    ctx.translate(lx, ly);
    ctx.rotate(-swing);
    ctx.scale(SCALE, SCALE);
    ellipse(ctx, 0, 0, 5, 6, '#D9443A');
    ellipse(ctx, -0.6, -0.5, 2.6, 4, 'rgba(255, 200, 120, 0.75)');
    ctx.strokeStyle = 'rgba(242, 181, 68, 0.7)';
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    ctx.ellipse(0, 0, 2.5, 6, 0, 0, TAU);
    ctx.moveTo(0, -6);
    ctx.lineTo(0, 6);
    ctx.stroke();
    ctx.fillStyle = '#3A2E24';
    ctx.fillRect(-3, -7.5, 6, 2);
    ctx.fillRect(-3, 5.5, 6, 2);
    ctx.strokeStyle = '#F2B544';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, 7.5);
    ctx.lineTo(0, 11);
    ctx.stroke();
    ctx.restore();
  }

  return { drawHero, drawLantern, SCALE };
})();
