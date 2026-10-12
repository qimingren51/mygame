// 调试面板：游戏中点“调”打开，各项开关实时生效。
// 每个按钮点一下切到下一个取值。

export interface PanelItem<T> {
  label: string;
  values: readonly T[];
  get(): T;
  set(v: T): void;
  show?: (v: T) => string;
}

// 面板里的条目取值类型各不相同，这里只需要能读写
type AnyItem = PanelItem<any>;

export function createPanel(items: AnyItem[]): { toggle(): void; refresh(): void; el: HTMLElement } {
  const el = document.createElement('div');
  el.className = 'debug-panel';
  el.hidden = true;
  const buttons: { b: HTMLButtonElement; it: AnyItem }[] = [];
  for (const it of items) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'toggle';
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      const cur = it.get();
      const i = it.values.indexOf(cur);
      it.set(it.values[(i + 1) % it.values.length]);
      refresh();
    });
    el.appendChild(b);
    buttons.push({ b, it });
  }
  const refresh = () => {
    for (const { b, it } of buttons) {
      const v = it.get();
      b.textContent = `${it.label} ${it.show ? it.show(v) : String(v)}`;
    }
  };
  refresh();
  document.body.appendChild(el);
  return {
    el,
    refresh,
    toggle: () => {
      el.hidden = !el.hidden;
      refresh();
    },
  };
}
