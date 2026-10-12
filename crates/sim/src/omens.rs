//! 夜签抽取：开局从 `omens.ron` 里不放回地抽 3 张给玩家选（移植自网页版 lantern/game.js 的 drawOmens）。
//! 只用种子派生的“夜签”随机流，同一种子抽到的夜签总是相同。

use lantern_content::{Content, Element};
use lantern_core::{Stream, Streams};

use crate::OmenPick;

/// 用这一局的种子抽 n 张夜签。
pub fn draw_omens(content: &Content, seed: u64, n: usize) -> Vec<OmenPick> {
    let mut streams = Streams::new(seed);
    let rng = streams.get(Stream::Omen);
    let mut pool: Vec<usize> = (0..content.omens.len()).collect();
    let mut out = Vec::with_capacity(n);
    while out.len() < n && !pool.is_empty() {
        let i = pool.remove(rng.below(pool.len() as u32) as usize);
        let def = &content.omens[i];
        let element = def.pick_element.then(|| Element::ALL[rng.below(Element::ALL.len() as u32) as usize]);
        out.push(OmenPick { id: def.id.clone(), element });
    }
    out
}

/// 夜签好处的文字（{el} 换成选定的五行名）。
pub fn omen_good(content: &Content, pick: &OmenPick) -> String {
    let Some(i) = content.omen_index(&pick.id) else { return String::new() };
    let good = &content.omens[i].good;
    match pick.element {
        Some(el) => good.replace("{el}", &content.element(el).name),
        None => good.clone(),
    }
}
