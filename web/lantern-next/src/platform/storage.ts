// localStorage 封装：键名自动加上游戏前缀（由文件夹名在构建时生成，
// 预览期是 lantern-next_，切换为 lantern/ 后是 lantern_，与旧版存档兼容）。
// 隐私模式等存储不可用的情况下静默失败。

export const STORE_PREFIX = __STORE_PREFIX__;

export function loadJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(STORE_PREFIX + key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function saveJSON(key: string, value: unknown): void {
  try {
    localStorage.setItem(STORE_PREFIX + key, JSON.stringify(value));
  } catch {
    // 忽略
  }
}
