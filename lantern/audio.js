// 提灯夜行 · 音频
// 所有音效与背景音乐都用 Web Audio 实时合成，不需要任何音频文件。
// 乐器：古筝式拨弦、编钟、太鼓、木鱼、锣；音阶：D 羽调五声音阶。
const LanternAudio = (() => {
  'use strict';

  const KEY = 'lantern_audio';
  const settings = { music: true, sfx: true };
  try {
    Object.assign(settings, JSON.parse(localStorage.getItem(KEY) || '{}'));
  } catch {
    // 存储不可用时使用默认设置
  }
  const saveSettings = () => {
    try {
      localStorage.setItem(KEY, JSON.stringify(settings));
    } catch {
      // 忽略
    }
  };

  const MUSIC_VOL = 0.42;
  const SFX_VOL = 0.75;

  let ctx = null;
  let master;
  let sfxBus;
  let musicBus;
  let musicFilter;
  let noiseBuf;
  const lastPlayed = {};

  // ---------------------------------------------------------------
  // 初始化（必须在用户手势里调用，浏览器才允许出声）
  // ---------------------------------------------------------------
  function init() {
    if (ctx) {
      if (ctx.state === 'suspended' && !document.hidden) ctx.resume();
      return;
    }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    ctx = new AC();

    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -16;
    comp.ratio.value = 4;
    comp.connect(ctx.destination);
    master = ctx.createGain();
    master.gain.value = 0.9;
    master.connect(comp);

    const reverb = ctx.createConvolver();
    reverb.buffer = makeImpulse(2.6);
    reverb.connect(master);

    sfxBus = ctx.createGain();
    sfxBus.gain.value = settings.sfx ? SFX_VOL : 0;
    sfxBus.connect(master);
    const sfxSend = ctx.createGain();
    sfxSend.gain.value = 0.18;
    sfxBus.connect(sfxSend);
    sfxSend.connect(reverb);

    musicFilter = ctx.createBiquadFilter();
    musicFilter.type = 'lowpass';
    musicFilter.frequency.value = 12000;
    musicBus = ctx.createGain();
    musicBus.gain.value = settings.music ? MUSIC_VOL : 0;
    musicFilter.connect(musicBus);
    musicBus.connect(master);
    const musicSend = ctx.createGain();
    musicSend.gain.value = 0.45;
    musicBus.connect(musicSend);
    musicSend.connect(reverb);

    noiseBuf = makeNoise(2);
    startDrone();
    setInterval(schedule, 50);
  }

  // 解锁音频。iPhone 上有三个坑：
  // 1. 只有“松手 / 点击”算用户手势，按下不算；所以每次手势都尝试恢复。
  // 2. 需要在手势里真正播放一次声音才会解锁；这里播放一个空白缓冲。
  // 3. 侧边静音键会静音网页合成的声音；把音频会话切到“播放”类型可以绕过。
  let silentEl = null;
  function unlock() {
    init();
    if (!ctx) return;
    if (ctx.state !== 'running' && !document.hidden) ctx.resume().catch(() => {});
    if (ctx.state !== 'running') {
      const src = ctx.createBufferSource();
      src.buffer = ctx.createBuffer(1, 1, 22050);
      src.connect(ctx.destination);
      src.start(0);
    }
    if (navigator.audioSession && navigator.audioSession.type !== 'playback') {
      try {
        navigator.audioSession.type = 'playback';
      } catch {
        // 不支持时忽略
      }
    }
    if (!silentEl) {
      // 循环播放一段静音音频，让 iOS 把页面当作媒体播放，从而无视静音键
      silentEl = document.createElement('audio');
      silentEl.setAttribute('playsinline', '');
      silentEl.setAttribute('x-webkit-airplay', 'deny');
      silentEl.loop = true;
      silentEl.src = URL.createObjectURL(makeSilentWav());
    }
    if (silentEl.paused && !document.hidden) silentEl.play().catch(() => {});
  }

  function makeSilentWav() {
    const rate = 8000;
    const samples = rate / 2;
    const buf = new ArrayBuffer(44 + samples * 2);
    const v = new DataView(buf);
    const str = (o, t) => {
      for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i));
    };
    str(0, 'RIFF');
    v.setUint32(4, 36 + samples * 2, true);
    str(8, 'WAVE');
    str(12, 'fmt ');
    v.setUint32(16, 16, true);
    v.setUint16(20, 1, true);
    v.setUint16(22, 1, true);
    v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true);
    v.setUint16(32, 2, true);
    v.setUint16(34, 16, true);
    str(36, 'data');
    v.setUint32(40, samples * 2, true);
    return new Blob([buf], { type: 'audio/wav' });
  }

  function makeNoise(sec) {
    const buf = ctx.createBuffer(1, Math.floor(ctx.sampleRate * sec), ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    return buf;
  }

  function makeImpulse(sec) {
    const len = Math.floor(ctx.sampleRate * sec);
    const buf = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3);
    }
    return buf;
  }

  // ---------------------------------------------------------------
  // 基础发声
  // ---------------------------------------------------------------
  function env(g, t, vol, attack, dur) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(Math.max(0.0002, vol), t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  }

  function osc(type, freq, t, dur, vol, dest, opt = {}) {
    const o = ctx.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    if (opt.slide) o.frequency.exponentialRampToValueAtTime(opt.slide, t + (opt.slideTime || dur));
    if (opt.detune) o.detune.value = opt.detune;
    const g = ctx.createGain();
    env(g, t, vol, opt.attack || 0.004, dur);
    o.connect(g);
    g.connect(dest);
    o.start(t);
    o.stop(t + dur + 0.05);
  }

  function noise(t, dur, vol, dest, opt = {}) {
    const src = ctx.createBufferSource();
    src.buffer = noiseBuf;
    const f = ctx.createBiquadFilter();
    f.type = opt.type || 'bandpass';
    f.frequency.setValueAtTime(opt.freq || 1200, t);
    if (opt.slide) f.frequency.exponentialRampToValueAtTime(opt.slide, t + dur);
    f.Q.value = opt.q || 1;
    const g = ctx.createGain();
    env(g, t, vol, opt.attack || 0.003, dur);
    src.connect(f);
    f.connect(g);
    g.connect(dest);
    const offset = Math.random() * Math.max(0, noiseBuf.duration - dur - 0.1);
    src.start(t, offset, dur + 0.05);
  }

  // D 羽调五声音阶：D F G A C
  const STEPS = [0, 3, 5, 7, 10];
  const ROOT = 146.83; // D3
  const pent = (i) => {
    const o = Math.floor(i / 5);
    const s = STEPS[((i % 5) + 5) % 5];
    return ROOT * Math.pow(2, o + s / 12);
  };

  // 古筝式拨弦：起音略高后回落，带泛音
  function pluck(freq, t, vol, dest, decay = 1.2) {
    const o = ctx.createOscillator();
    o.type = 'triangle';
    o.frequency.setValueAtTime(freq * 1.012, t);
    o.frequency.exponentialRampToValueAtTime(freq, t + 0.06);
    const g = ctx.createGain();
    env(g, t, vol, 0.003, decay);
    o.connect(g);
    g.connect(dest);
    o.start(t);
    o.stop(t + decay + 0.05);
    osc('sine', freq * 2, t, decay * 0.5, vol * 0.35, dest);
    osc('sine', freq * 3, t, decay * 0.25, vol * 0.12, dest);
    noise(t, 0.03, vol * 0.25, dest, { freq: Math.min(8000, freq * 4), q: 2 });
  }

  // 编钟：非整数倍泛音
  function bell(freq, t, vol, dest, decay = 2) {
    osc('sine', freq, t, decay, vol, dest);
    osc('sine', freq * 2.76, t, decay * 0.5, vol * 0.4, dest);
    osc('sine', freq * 5.4, t, decay * 0.25, vol * 0.18, dest);
  }

  // 太鼓
  function drum(t, vol, dest, pitch = 110) {
    osc('sine', pitch, t, 0.45, vol, dest, { slide: pitch * 0.42, slideTime: 0.3 });
    noise(t, 0.12, vol * 0.45, dest, { type: 'lowpass', freq: 420 });
  }

  // 木鱼
  function wood(t, vol, dest, pitch = 900) {
    osc('sine', pitch, t, 0.08, vol, dest);
    noise(t, 0.03, vol * 0.6, dest, { freq: pitch * 2, q: 6 });
  }

  // 锣
  function gong(freq, t, vol, dest) {
    [1, 1.48, 2.02, 2.74, 3.9].forEach((m, i) => {
      osc('sine', freq * m, t, 3.4 - i * 0.5, vol / (i + 1), dest, { detune: (Math.random() - 0.5) * 14, attack: 0.01 });
    });
    noise(t, 0.4, vol * 0.35, dest, { type: 'lowpass', freq: 700 });
  }

  // ---------------------------------------------------------------
  // 音效
  // ---------------------------------------------------------------
  const ready = () => ctx && settings.sfx && ctx.state === 'running';
  function can(name, gap) {
    const now = ctx.currentTime;
    if (lastPlayed[name] !== undefined && now - lastPlayed[name] < gap) return false;
    lastPlayed[name] = now;
    return true;
  }

  let gemChain = 0;
  let gemLast = 0;

  const sfx = {
    click() {
      if (!ready()) return;
      wood(ctx.currentTime, 0.12, sfxBus, 1300);
    },
    hit() {
      if (!ready() || !can('hit', 0.045)) return;
      noise(ctx.currentTime, 0.035, 0.07, sfxBus, { type: 'highpass', freq: 2500 + Math.random() * 1800 });
    },
    kill() {
      if (!ready() || !can('kill', 0.04)) return;
      osc('sine', 240 + Math.random() * 90, ctx.currentTime, 0.12, 0.1, sfxBus, { slide: 85 });
    },
    gem() {
      if (!ready() || !can('gem', 0.05)) return;
      const t = ctx.currentTime;
      if (t - gemLast > 0.6) gemChain = 0;
      gemLast = t;
      // 连续拾取时音高一路爬升
      const f = pent(10 + (gemChain++ % 12));
      osc('sine', f, t, 0.18, 0.06, sfxBus);
      osc('triangle', f * 2, t, 0.08, 0.025, sfxBus);
    },
    levelUp() {
      if (!ready()) return;
      const t = ctx.currentTime;
      [10, 12, 13, 15, 17].forEach((d, i) => pluck(pent(d), t + i * 0.06, 0.16, sfxBus, 0.9));
      bell(pent(20), t + 0.32, 0.08, sfxBus, 1.6);
    },
    select() {
      if (!ready()) return;
      const t = ctx.currentTime;
      pluck(pent(12), t, 0.18, sfxBus, 0.8);
      pluck(pent(15), t + 0.05, 0.14, sfxBus, 0.8);
    },
    chest(n) {
      if (!ready()) return;
      const t = ctx.currentTime;
      for (let i = 0; i < 6; i++) wood(t + i * 0.045 * (1 - i * 0.08), 0.1, sfxBus, 700 + i * 60);
      for (let i = 0; i < n; i++) bell(pent(12 + i * 2), t + 0.15 + i * 0.28 + 0.2, 0.14, sfxBus, 1.4);
    },
    evolution() {
      if (!ready()) return;
      const t = ctx.currentTime;
      gong(73.4, t, 0.32, sfxBus);
      drum(t, 0.6, sfxBus, 90);
      [5, 7, 10, 12, 15, 17, 20].forEach((d, i) => pluck(pent(d), t + 0.1 + i * 0.07, 0.15, sfxBus, 1));
      bell(pent(22), t + 0.7, 0.12, sfxBus, 2.5);
    },
    resonance() {
      if (!ready() || !can('res', 0.3)) return;
      const t = ctx.currentTime;
      [12, 15, 17].forEach((d, i) => pluck(pent(d), t + i * 0.08, 0.13, sfxBus, 1));
      bell(pent(19), t + 0.24, 0.07, sfxBus, 1.5);
    },
    ult() {
      if (!ready()) return;
      const t = ctx.currentTime;
      noise(t, 0.4, 0.25, sfxBus, { type: 'highpass', freq: 400, slide: 5000, attack: 0.3 });
      drum(t + 0.33, 0.9, sfxBus, 70);
      noise(t + 0.33, 0.9, 0.3, sfxBus, { type: 'lowpass', freq: 900, slide: 120 });
      gong(55, t + 0.33, 0.22, sfxBus);
    },
    dash() {
      if (!ready()) return;
      noise(ctx.currentTime, 0.18, 0.14, sfxBus, { freq: 700, slide: 3200, q: 1.4 });
    },
    hurt() {
      if (!ready() || !can('hurt', 0.2)) return;
      const t = ctx.currentTime;
      osc('sine', 190, t, 0.25, 0.28, sfxBus, { slide: 60 });
      noise(t, 0.12, 0.15, sfxBus, { type: 'lowpass', freq: 600 });
    },
    sword() {
      if (!ready() || !can('sword', 0.1)) return;
      noise(ctx.currentTime, 0.07, 0.045, sfxBus, { type: 'highpass', freq: 4500, slide: 7000 });
    },
    bellPulse() {
      if (!ready() || !can('bellp', 0.4)) return;
      bell(pent(15), ctx.currentTime, 0.06, sfxBus, 1.1);
    },
    bigBell() {
      if (!ready()) return;
      const t = ctx.currentTime;
      bell(pent(5), t, 0.22, sfxBus, 3);
      bell(pent(10), t + 0.02, 0.12, sfxBus, 2.5);
    },
    seal() {
      if (!ready() || !can('seal', 0.12)) return;
      drum(ctx.currentTime, 0.22, sfxBus, 95);
    },
    blast() {
      if (!ready() || !can('blast', 0.09)) return;
      const t = ctx.currentTime;
      osc('sine', 130, t, 0.2, 0.1, sfxBus, { slide: 50 });
      noise(t, 0.15, 0.07, sfxBus, { type: 'lowpass', freq: 900 });
    },
    warn(big) {
      if (!ready()) return;
      const t = ctx.currentTime;
      const n = big ? 3 : 2;
      for (let i = 0; i < n; i++) drum(t + i * 0.24, 0.55, sfxBus, big ? 75 : 95);
      if (big) gong(49, t + 0.72, 0.28, sfxBus);
    },
    soulBell() {
      if (!ready()) return;
      const t = ctx.currentTime;
      for (let i = 0; i < 8; i++) bell(pent(12 + i), t + i * 0.045, 0.06, sfxBus, 0.9);
    },
    heal() {
      if (!ready() || !can('heal', 0.5)) return;
      const t = ctx.currentTime;
      bell(pent(14), t, 0.1, sfxBus, 1.2);
      bell(pent(17), t + 0.08, 0.08, sfxBus, 1.2);
    },
    combo() {
      if (!ready()) return;
      const t = ctx.currentTime;
      bell(pent(17), t, 0.1, sfxBus, 1);
      bell(pent(20), t + 0.06, 0.08, sfxBus, 1.2);
    },
    event() {
      if (!ready()) return;
      const t = ctx.currentTime;
      bell(pent(13), t, 0.12, sfxBus, 1.6);
      bell(pent(16), t + 0.18, 0.1, sfxBus, 1.8);
    },
    coins() {
      if (!ready()) return;
      const t = ctx.currentTime;
      for (let i = 0; i < 10; i++) osc('sine', pent(15 + (i % 5)) * 2, t + i * 0.035, 0.12, 0.05, sfxBus);
    },
    victory() {
      if (!ready()) return;
      const t = ctx.currentTime + 0.1;
      const notes = [[10, 0], [12, 0.25], [14, 0.5], [17, 0.75], [15, 1.1], [14, 1.35], [12, 1.6], [15, 1.85], [20, 2.3]];
      notes.forEach(([d, at]) => pluck(pent(d), t + at, 0.18, sfxBus, 1.4));
      gong(73.4, t + 2.3, 0.2, sfxBus);
    },
    defeat() {
      if (!ready()) return;
      const t = ctx.currentTime + 0.1;
      [[14, 0], [12, 0.45], [11, 0.9], [9, 1.35], [5, 1.9]].forEach(([d, at]) => pluck(pent(d), t + at, 0.16, sfxBus, 1.8));
      drum(t + 1.9, 0.3, sfxBus, 70);
    },
  };

  // ---------------------------------------------------------------
  // 背景音乐：持续的低音 + 随机生成的五声旋律 + 随局势加强的鼓点
  // ---------------------------------------------------------------
  const music = { mode: 'none', intensity: 0, step: 0, next: 0, rng: Math.random, motif: [], bar: 0 };
  let drone = null;

  function startDrone() {
    const g = ctx.createGain();
    g.gain.value = 0;
    const f = ctx.createBiquadFilter();
    f.type = 'lowpass';
    f.frequency.value = 500;
    const a = ctx.createOscillator();
    const b = ctx.createOscillator();
    a.type = 'triangle';
    b.type = 'triangle';
    a.frequency.value = pent(-5); // D2
    b.frequency.value = pent(-2); // A2
    b.detune.value = 4;
    a.connect(f);
    b.connect(f);
    f.connect(g);
    g.connect(musicFilter);
    a.start();
    b.start();
    drone = { g, a, b };
  }

  function seededRng(seed) {
    let s = seed >>> 0 || 1;
    return () => {
      s = (s + 0x6d2b79f5) | 0;
      let t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // 生成 16 个八分音符的旋律动机（随机游走，留出呼吸）
  function makeMotif(restChance) {
    const r = music.rng;
    const out = [];
    let d = 10 + Math.floor(r() * 4);
    for (let i = 0; i < 16; i++) {
      if (r() < restChance || (i % 4 === 3 && r() < 0.5)) {
        out.push(null);
        continue;
      }
      d += Math.floor(r() * 5) - 2;
      d = Math.max(7, Math.min(17, d));
      out.push(d);
    }
    return out;
  }

  function mutateMotif() {
    const r = music.rng;
    music.motif = music.motif.map((n) => {
      if (r() > 0.3) return n;
      if (n === null) return r() < 0.5 ? 10 + Math.floor(r() * 6) : null;
      return Math.max(7, Math.min(17, n + Math.floor(r() * 5) - 2));
    });
  }

  const BPM = { title: 66, play: 84, boss: 104 };

  function stepDur() {
    const bpm = BPM[music.mode] + (music.mode === 'play' ? music.intensity * 5 : 0);
    return 60 / bpm / 2;
  }

  function schedule() {
    if (!ctx || music.mode === 'none' || ctx.state !== 'running') return;
    if (music.next < ctx.currentTime) music.next = ctx.currentTime + 0.05;
    while (music.next < ctx.currentTime + 0.2) {
      playStep(music.next, music.step);
      music.next += stepDur();
      music.step++;
    }
  }

  const BASS = [0, 3, 2, 0];

  function playStep(t, step) {
    const s = step % 16;
    if (s === 0) {
      music.bar++;
      if (music.bar % 4 === 0) {
        if (music.rng() < 0.35) music.motif = makeMotif(music.mode === 'title' ? 0.55 : 0.35);
        else mutateMotif();
      }
    }
    const mode = music.mode;
    const lvl = mode === 'boss' ? 3 : mode === 'title' ? -1 : music.intensity;
    const bus = musicFilter;

    // 低音拨弦
    if (s % 8 === 0) {
      const root = BASS[Math.floor(step / 8) % 4] + (mode === 'boss' ? -1 : 0);
      pluck(pent(root), t, mode === 'title' ? 0.12 : 0.15, bus, 1.6);
    }
    // 旋律
    const note = music.motif[s];
    if (note !== null && note !== undefined && (mode !== 'title' || s % 2 === 0)) {
      pluck(pent(note + (mode === 'boss' ? -1 : 0)), t, 0.1, bus, mode === 'title' ? 1.8 : 1.1);
    }
    // 打击乐随局势加强
    if (lvl >= 1 && s % 2 === 0) wood(t, s % 8 === 0 ? 0.08 : 0.045, bus, s % 8 === 0 ? 820 : 1050);
    if (lvl >= 2 && (s === 0 || s === 8)) drum(t, 0.3, bus, 100);
    if (lvl >= 3) {
      if (s === 6 || s === 12 || s === 14) drum(t, 0.26, bus, 85);
      if (s % 2 === 1) wood(t, 0.03, bus, 1400);
      if (s === 0 && music.bar % 4 === 0) gong(49, t, 0.12, bus);
    }
  }

  function setDrone(level, boss) {
    if (!drone) return;
    const t = ctx.currentTime;
    drone.g.gain.cancelScheduledValues(t);
    drone.g.gain.setTargetAtTime(level, t, 0.8);
    drone.b.frequency.setTargetAtTime(boss ? pent(-5) * Math.pow(2, 6 / 12) : pent(-2), t, 0.5);
  }

  function setMusic(mode, seed) {
    if (!ctx) return;
    if (mode === music.mode && seed === undefined) return;
    music.mode = mode;
    if (seed !== undefined) music.rng = seededRng(seed);
    if (mode === 'none') {
      setDrone(0);
      return;
    }
    if (mode !== 'boss' || !music.motif.length) music.motif = makeMotif(mode === 'title' ? 0.55 : 0.35);
    music.step = 0;
    music.bar = 0;
    music.next = ctx.currentTime + 0.1;
    setDrone(mode === 'title' ? 0.05 : mode === 'boss' ? 0.07 : 0.04, mode === 'boss');
  }

  function setIntensity(n) {
    music.intensity = n;
  }

  // 打开菜单时音乐变闷
  function muffle(on) {
    if (!ctx) return;
    musicFilter.frequency.setTargetAtTime(on ? 650 : 12000, ctx.currentTime, 0.15);
  }

  function setEnabled(kind, on) {
    settings[kind] = on;
    saveSettings();
    if (!ctx) return;
    const bus = kind === 'music' ? musicBus : sfxBus;
    bus.gain.setTargetAtTime(on ? (kind === 'music' ? MUSIC_VOL : SFX_VOL) : 0, ctx.currentTime, 0.05);
  }

  document.addEventListener('visibilitychange', () => {
    if (!ctx) return;
    if (document.hidden) {
      ctx.suspend();
      if (silentEl) silentEl.pause();
    } else {
      ctx.resume().catch(() => {});
      if (silentEl) silentEl.play().catch(() => {});
    }
  });

  return { init, unlock, sfx, setMusic, setIntensity, muffle, setEnabled, settings };
})();
