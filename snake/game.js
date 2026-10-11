(() => {
  'use strict';

  const COLS = 20;
  const ROWS = 20;
  const BASE_STEP_MS = 150;   // 初始速度：每步间隔
  const MIN_STEP_MS = 70;     // 最快速度
  const SPEEDUP_PER_FOOD = 3; // 每吃一个食物缩短的间隔
  const HIGHSCORE_KEY = 'snake_highscore';

  const DIRS = {
    up: { x: 0, y: -1 },
    down: { x: 0, y: 1 },
    left: { x: -1, y: 0 },
    right: { x: 1, y: 0 },
  };

  const canvas = document.getElementById('board');
  const ctx = canvas.getContext('2d');
  const wrap = document.getElementById('board-wrap');
  const scoreEl = document.getElementById('score');
  const bestEl = document.getElementById('best');
  const pauseBtn = document.getElementById('pause');
  const overlay = document.getElementById('overlay');
  const overlayTitle = document.getElementById('overlay-title');
  const overlayText = document.getElementById('overlay-text');
  const overlayBtn = document.getElementById('overlay-button');

  // state: 'ready' | 'running' | 'paused' | 'over'
  let state = 'ready';
  let snake, dir, queue, food, score, stepMs, acc;
  let best = loadBest();
  let lastTime = 0;
  let colors = readColors();

  function loadBest() {
    try {
      return parseInt(localStorage.getItem(HIGHSCORE_KEY), 10) || 0;
    } catch {
      return 0;
    }
  }

  function saveBest(value) {
    try {
      localStorage.setItem(HIGHSCORE_KEY, String(value));
    } catch {
      // 隐私模式等情况下存储不可用，忽略即可
    }
  }

  function readColors() {
    const style = getComputedStyle(document.documentElement);
    const get = (name) => style.getPropertyValue(name).trim();
    return {
      board: get('--board'),
      boardAlt: get('--board-alt'),
      snake: get('--snake'),
      head: get('--snake-head'),
      food: get('--food'),
    };
  }

  function reset() {
    const cx = Math.floor(COLS / 2);
    const cy = Math.floor(ROWS / 2);
    snake = [
      { x: cx, y: cy },
      { x: cx - 1, y: cy },
      { x: cx - 2, y: cy },
    ];
    dir = DIRS.right;
    queue = [];
    score = 0;
    stepMs = BASE_STEP_MS;
    acc = 0;
    placeFood();
    updateHud();
  }

  function placeFood() {
    const free = [];
    for (let y = 0; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        if (!snake.some((s) => s.x === x && s.y === y)) free.push({ x, y });
      }
    }
    food = free.length ? free[Math.floor(Math.random() * free.length)] : null;
  }

  function step() {
    if (queue.length) dir = queue.shift();

    const head = snake[0];
    const next = { x: head.x + dir.x, y: head.y + dir.y };
    const eating = food !== null && next.x === food.x && next.y === food.y;
    // 不吃食物时尾巴会移走，所以可以走进当前尾巴所在的格子
    const body = eating ? snake : snake.slice(0, -1);

    const hitWall = next.x < 0 || next.x >= COLS || next.y < 0 || next.y >= ROWS;
    const hitSelf = body.some((s) => s.x === next.x && s.y === next.y);
    if (hitWall || hitSelf) {
      endGame(false);
      return;
    }

    snake.unshift(next);
    if (eating) {
      score++;
      stepMs = Math.max(MIN_STEP_MS, BASE_STEP_MS - score * SPEEDUP_PER_FOOD);
      placeFood();
      updateHud();
      if (food === null) endGame(true);
    } else {
      snake.pop();
    }
  }

  function turn(name) {
    if (state === 'over') return;
    if (state !== 'running') start();

    const d = DIRS[name];
    const last = queue.length ? queue[queue.length - 1] : dir;
    const reverse = d.x === -last.x && d.y === -last.y;
    if (d === last || reverse) return;
    // 最多缓存两步，快速连按（如先上再左）不会丢操作
    if (queue.length < 2) queue.push(d);
  }

  function start() {
    if (state === 'ready' || state === 'over') reset();
    state = 'running';
    acc = 0;
    showOverlay(null);
    pauseBtn.textContent = '暂停';
  }

  function pause() {
    if (state !== 'running') return;
    state = 'paused';
    pauseBtn.textContent = '继续';
    showOverlay('已暂停', '按空格或点击继续', '继续');
  }

  function togglePause() {
    if (state === 'running') pause();
    else start();
  }

  function endGame(won) {
    state = 'over';
    pauseBtn.textContent = '开始';
    const newRecord = score > best;
    if (newRecord) {
      best = score;
      saveBest(best);
      updateHud();
    }
    const text = `得分 ${score}${newRecord ? '，新纪录！' : ''}`;
    showOverlay(won ? '你赢了！' : '游戏结束', text, '再来一局');
  }

  function showOverlay(title, text, buttonLabel) {
    if (title === null) {
      overlay.hidden = true;
      return;
    }
    overlayTitle.textContent = title;
    overlayText.textContent = text;
    overlayBtn.textContent = buttonLabel;
    overlay.hidden = false;
  }

  function updateHud() {
    scoreEl.textContent = score;
    bestEl.textContent = best;
  }

  // ---- 绘制 ----

  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const size = Math.round(rect.width * dpr);
    if (canvas.width !== size || canvas.height !== size) {
      canvas.width = size;
      canvas.height = size;
    }
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
    ctx.fill();
  }

  function draw() {
    const cell = canvas.width / COLS;

    for (let y = 0; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        ctx.fillStyle = (x + y) % 2 === 0 ? colors.board : colors.boardAlt;
        ctx.fillRect(x * cell, y * cell, cell + 1, cell + 1);
      }
    }

    if (food) {
      ctx.fillStyle = colors.food;
      ctx.beginPath();
      ctx.arc((food.x + 0.5) * cell, (food.y + 0.5) * cell, cell * 0.36, 0, Math.PI * 2);
      ctx.fill();
    }

    const pad = cell * 0.08;
    for (let i = snake.length - 1; i >= 0; i--) {
      const s = snake[i];
      ctx.fillStyle = i === 0 ? colors.head : colors.snake;
      roundRect(s.x * cell + pad, s.y * cell + pad, cell - pad * 2, cell - pad * 2, cell * 0.25);
    }
  }

  function frame(time) {
    // 限制单帧最大间隔，避免切回标签页时一次走很多步
    const dt = Math.min(time - lastTime, 200);
    lastTime = time;

    if (state === 'running') {
      acc += dt;
      while (acc >= stepMs && state === 'running') {
        acc -= stepMs;
        step();
      }
    }

    resizeCanvas();
    draw();
    requestAnimationFrame(frame);
  }

  // ---- 输入 ----

  const KEY_DIRS = {
    ArrowUp: 'up', KeyW: 'up',
    ArrowDown: 'down', KeyS: 'down',
    ArrowLeft: 'left', KeyA: 'left',
    ArrowRight: 'right', KeyD: 'right',
  };

  document.addEventListener('keydown', (e) => {
    const name = KEY_DIRS[e.code];
    if (name) {
      e.preventDefault();
      turn(name);
    } else if (e.code === 'Space' || e.code === 'Enter' || e.code === 'KeyP') {
      e.preventDefault();
      if (e.repeat) return;
      togglePause();
    }
  });

  // 在棋盘上滑动控制方向
  let swipeStart = null;
  wrap.addEventListener('pointerdown', (e) => {
    swipeStart = { x: e.clientX, y: e.clientY };
  });
  wrap.addEventListener('pointerup', (e) => {
    if (!swipeStart) return;
    const dx = e.clientX - swipeStart.x;
    const dy = e.clientY - swipeStart.y;
    swipeStart = null;
    if (Math.max(Math.abs(dx), Math.abs(dy)) < 24) return;
    if (Math.abs(dx) > Math.abs(dy)) turn(dx > 0 ? 'right' : 'left');
    else turn(dy > 0 ? 'down' : 'up');
  });
  wrap.addEventListener('pointercancel', () => {
    swipeStart = null;
  });

  document.querySelectorAll('.dpad button').forEach((btn) => {
    btn.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      turn(btn.dataset.dir);
    });
  });

  overlayBtn.addEventListener('click', start);
  pauseBtn.addEventListener('click', () => {
    pauseBtn.blur(); // 避免之后按空格同时触发按钮点击
    togglePause();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) pause();
  });

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    colors = readColors();
  });

  reset();
  requestAnimationFrame((time) => {
    lastTime = time;
    frame(time);
  });
})();
