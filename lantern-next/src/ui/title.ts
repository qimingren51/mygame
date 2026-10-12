// 标题界面：开始、跑分、音乐 / 音效 / 全屏开关。

import { setEnabled, settings, unlock } from '../audio/engine';
import { sfx } from '../audio/sfx';
import { fullscreenSupported, isFullscreen, isIOS, isStandalone, isTouch, onFullscreenChange, toggleFullscreen } from '../platform/fullscreen';

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

export interface TitleActions {
  start(): void;
  bench(): void;
}

export function setupTitle(actions: TitleActions): { show(): void; hide(): void } {
  const screen = $<HTMLElement>('title');

  $<HTMLButtonElement>('start-btn').addEventListener('click', () => {
    unlock();
    sfx.select();
    actions.start();
  });
  $<HTMLButtonElement>('bench-btn').addEventListener('click', () => {
    unlock();
    sfx.select();
    actions.bench();
  });

  const audioBtns = document.querySelectorAll<HTMLButtonElement>('[data-audio]');
  const syncAudio = () => {
    for (const b of audioBtns) {
      const kind = b.dataset.audio as 'music' | 'sfx';
      const on = settings[kind];
      b.textContent = `${kind === 'music' ? '音乐' : '音效'} ${on ? '开' : '关'}`;
      b.classList.toggle('off', !on);
    }
  };
  for (const b of audioBtns) {
    b.addEventListener('click', () => {
      unlock();
      const kind = b.dataset.audio as 'music' | 'sfx';
      setEnabled(kind, !settings[kind]);
      syncAudio();
      sfx.click();
    });
  }
  syncAudio();

  const fsBtns = document.querySelectorAll<HTMLButtonElement>('[data-fs]');
  const syncFs = () => {
    for (const b of fsBtns) {
      b.hidden = !fullscreenSupported();
      b.textContent = isFullscreen() ? '退出全屏' : '全屏';
    }
  };
  for (const b of fsBtns) b.addEventListener('click', () => toggleFullscreen());
  onFullscreenChange(syncFs);
  syncFs();

  // iPhone 不支持网页全屏：提示添加到主屏幕
  const hint = $<HTMLElement>('fs-hint');
  if (isTouch() && isIOS() && !isStandalone()) {
    hint.textContent = '想要全屏：点浏览器的“分享”按钮 → “添加到主屏幕”，再从桌面图标打开';
    hint.hidden = false;
  }

  return {
    show: () => {
      screen.hidden = false;
    },
    hide: () => {
      screen.hidden = true;
    },
  };
}
