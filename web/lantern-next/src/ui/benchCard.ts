// 跑分结果卡片：表格 + 一键复制。

import type { StageResult } from '../debug/bench';

export function showBenchCard(results: StageResult[], text: string, actions: { again(): void; back(): void }): void {
  document.getElementById('bench-card')?.remove();
  const el = document.createElement('section');
  el.id = 'bench-card';
  el.className = 'screen bench-card';
  const rows = results
    .map((r) => {
      const good = r.fps >= 50 && r.p95 <= 25;
      const ok = r.fps >= 40;
      return `<tr class="${good ? 'good' : ok ? 'ok' : 'bad'}"><td>${r.enemies}</td><td>${r.fps.toFixed(1)}</td><td>${r.p95.toFixed(1)}</td><td>${r.worst.toFixed(0)}</td><td>${r.lights}</td></tr>`;
    })
    .join('');
  el.innerHTML = `
    <h2 class="bench-title">跑分结果</h2>
    <table class="bench-table">
      <thead><tr><th>妖物</th><th>帧率</th><th>P95 帧时间 ms</th><th>最慢 ms</th><th>光源</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <pre class="bench-text"></pre>
    <div class="row">
      <button class="btn primary" type="button" data-act="copy">复制结果</button>
      <button class="btn" type="button" data-act="again">再跑一次</button>
      <button class="btn ghost" type="button" data-act="back">返回</button>
    </div>
    <p class="hint">请把结果复制给我，或者截图这一页。</p>`;
  (el.querySelector('.bench-text') as HTMLElement).textContent = text;
  const copyBtn = el.querySelector('[data-act="copy"]') as HTMLButtonElement;
  copyBtn.addEventListener('click', () => {
    const done = () => {
      copyBtn.textContent = '已复制';
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done, () => selectText(el));
    } else selectText(el);
  });
  el.querySelector('[data-act="again"]')?.addEventListener('click', () => {
    el.remove();
    actions.again();
  });
  el.querySelector('[data-act="back"]')?.addEventListener('click', () => {
    el.remove();
    actions.back();
  });
  document.body.appendChild(el);
}

/** 剪贴板不可用时，选中文字让用户手动复制 */
function selectText(root: HTMLElement): void {
  const pre = root.querySelector('.bench-text');
  if (!pre) return;
  const range = document.createRange();
  range.selectNodeContents(pre);
  const sel = getSelection();
  sel?.removeAllRanges();
  sel?.addRange(range);
}
