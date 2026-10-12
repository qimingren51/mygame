// 全屏：安卓与电脑用全屏接口；iPhone 不支持，需要“添加到主屏幕”后从桌面打开。

type FsDocument = Document & { webkitFullscreenEnabled?: boolean; webkitFullscreenElement?: Element | null; webkitExitFullscreen?: () => void };
type FsElement = HTMLElement & { webkitRequestFullscreen?: (opts?: FullscreenOptions) => void };
type OrientationWithLock = ScreenOrientation & { lock?: (o: string) => Promise<void> };

const doc = document as FsDocument;

export const fullscreenSupported = (): boolean => !!(doc.fullscreenEnabled || doc.webkitFullscreenEnabled);
export const isFullscreen = (): boolean => !!(doc.fullscreenElement || doc.webkitFullscreenElement);
export const isStandalone = (): boolean =>
  (navigator as Navigator & { standalone?: boolean }).standalone === true ||
  matchMedia('(display-mode: standalone), (display-mode: fullscreen)').matches;
export const isTouch = (): boolean => matchMedia('(pointer: coarse)').matches;
export const isIOS = (): boolean => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

export function enterFullscreen(): void {
  const el = document.documentElement as FsElement;
  const req = el.requestFullscreen?.bind(el) ?? el.webkitRequestFullscreen?.bind(el);
  if (!req || isFullscreen()) return;
  let result: unknown;
  try {
    result = req({ navigationUI: 'hide' });
  } catch {
    return;
  }
  Promise.resolve(result)
    .then(() => (screen.orientation as OrientationWithLock | undefined)?.lock?.('landscape'))
    .catch(() => {});
}

export function exitFullscreen(): void {
  const exit = doc.exitFullscreen?.bind(doc) ?? doc.webkitExitFullscreen?.bind(doc);
  if (exit && isFullscreen()) void exit();
}

export function toggleFullscreen(): void {
  if (isFullscreen()) exitFullscreen();
  else enterFullscreen();
}

export function onFullscreenChange(fn: () => void): void {
  document.addEventListener('fullscreenchange', fn);
  document.addEventListener('webkitfullscreenchange', fn);
}
