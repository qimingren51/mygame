//! 青丘长曲式；48 kHz 单声道 PCM，共用伴奏的变奏通过 Arc 复用采样。

use std::sync::Arc;

use super::{BAR, FRAMES, LAYERS, STEP, THEME};
use crate::synth::{Buf, SAMPLE_RATE, drone, jiao};

#[derive(Clone, Copy)]
struct Note {
    step: u8,
    degree: i32,
    len: u8,
}

const fn n(step: u8, degree: i32, len: u8) -> Note {
    Note { step, degree, len }
}

// A：E–G–A 的附点呼唤，抬到 D 再落回 E；B：高八度回应，末小节长收在 E。
// degree 为 E 角音阶中的级数，5 = E4；时值单位为八分音符，空隙留给换气。
const MELODY: &[Note] = &[
    n(0, 5, 3),
    n(3, 6, 1),
    n(4, 7, 3),
    n(7, 6, 1),
    n(8, 5, 4),
    n(12, 4, 2),
    n(14, 5, 2),
    n(16, 6, 2),
    n(18, 7, 2),
    n(20, 9, 4),
    n(24, 8, 3),
    n(27, 7, 1),
    n(28, 6, 2),
    n(30, 5, 2),
    n(32, 10, 3),
    n(35, 9, 1),
    n(36, 8, 2),
    n(38, 7, 2),
    n(40, 9, 4),
    n(44, 8, 2),
    n(46, 7, 2),
    n(48, 6, 3),
    n(51, 7, 1),
    n(52, 6, 2),
    n(54, 4, 2),
    n(56, 5, 8),
];
const BASS: [i32; 8] = [-5, -2, -3, -5, -2, -1, -3, -5];
const OSTINATO: [i32; 4] = [0, 2, 4, 2];
const BELLS: &[Note] = &[n(0, 10, 4), n(16, 9, 4), n(32, 10, 4), n(40, 9, 4), n(56, 10, 8)];

// C/D：把重心移到 A、C，长短句交替，以 E 收束，仍只用青丘角调音集。
const CONTRAST: &[Note] = &[
    n(0, 7, 6),
    n(6, 8, 2),
    n(8, 10, 3),
    n(11, 9, 1),
    n(12, 8, 4),
    n(16, 7, 2),
    n(18, 5, 2),
    n(20, 6, 2),
    n(22, 7, 2),
    n(24, 4, 4),
    n(28, 5, 4),
    n(32, 8, 4),
    n(36, 7, 2),
    n(38, 8, 2),
    n(40, 9, 6),
    n(46, 7, 2),
    n(48, 8, 2),
    n(50, 6, 2),
    n(52, 4, 4),
    n(56, 5, 8),
];
// 发展段：呼唤动机的二度模进、切分推进，后半句逐级下行归 E。
const DEVELOPMENT: &[Note] = &[
    n(0, 6, 3),
    n(3, 7, 3),
    n(6, 8, 2),
    n(8, 7, 3),
    n(11, 8, 3),
    n(14, 9, 2),
    n(16, 8, 3),
    n(19, 9, 3),
    n(22, 10, 2),
    n(24, 9, 4),
    n(28, 7, 4),
    n(32, 10, 2),
    n(34, 9, 2),
    n(36, 8, 4),
    n(40, 7, 3),
    n(43, 6, 3),
    n(46, 5, 2),
    n(48, 4, 4),
    n(52, 6, 2),
    n(54, 4, 2),
    n(56, 5, 8),
];

/// 八个八小节段落，64 小节约 182.86 秒；固定曲式天然可复现，不读取模拟随机流。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Section {
    Theme,
    Ornament,
    Contrast,
    Dialogue,
    ContrastFlowers,
    Development,
    Bridge,
    Return,
}
pub(super) const FORM: [Section; 8] = [
    Section::Theme,
    Section::Ornament,
    Section::Contrast,
    Section::Dialogue,
    Section::ContrastFlowers,
    Section::Development,
    Section::Bridge,
    Section::Return,
];
pub(super) const CYCLE_FRAMES: usize = FRAMES * FORM.len();

impl Section {
    fn accompaniment(self) -> Self {
        match self {
            Self::Ornament | Self::Dialogue | Self::Return => Self::Theme,
            Self::ContrastFlowers => Self::Contrast,
            Self::Bridge => Self::Development,
            other => other,
        }
    }

    fn bass(self) -> [i32; 8] {
        match self.accompaniment() {
            Self::Contrast => [-3, -2, -3, -5, -2, -1, -2, -5],
            Self::Development => [-4, -3, -2, -1, -2, -3, -1, -5],
            _ => BASS,
        }
    }

    fn melody(self) -> Vec<Note> {
        let base = match self {
            Self::Contrast | Self::ContrastFlowers => CONTRAST,
            Self::Development => DEVELOPMENT,
            _ => MELODY,
        };
        if self == Self::Bridge {
            // A 句时值扩展一倍：留白、低八度箫回应，再引向主题再现。
            return MELODY
                .iter()
                .filter(|n| n.step < 32)
                .map(|n| Note { step: n.step * 2, degree: n.degree, len: n.len * 2 })
                .collect();
        }
        let mut notes = Vec::new();
        for &note in base {
            let Note { step, degree, len } = note;
            match self {
                Self::Ornament | Self::ContrastFlowers if len >= 3 && step != 56 => {
                    notes.push(n(step, degree, len - 1));
                    notes.push(n(step + len - 1, degree + if self == Self::Ornament { 1 } else { -1 }, 1));
                }
                Self::Dialogue => notes.push(n(step, degree + if step / 8 % 2 == 0 { -5 } else { 0 }, len)),
                Self::Return if len >= 4 => {
                    notes.push(n(step, degree, len - 2));
                    notes.push(n(step + len - 2, degree + 1, 1));
                    notes.push(n(step + len - 1, degree, 1));
                }
                _ => notes.push(note),
            }
        }
        notes
    }
}

/// 16 位单声道保留 48 kHz 采样率；声像仍在播放时处理，不预存双份相同左右声道。
/// 变奏仅新增旋律 PCM，低音、织体、鼓、钟共享原伴奏；天明直接复用第一段。
pub(super) struct Score {
    sections: [[Arc<[i16]>; LAYERS]; FORM.len()],
}

impl Score {
    pub(super) fn new() -> Self {
        let mut rendered: Vec<(Section, [Arc<[i16]>; LAYERS])> = Vec::new();
        for section in FORM {
            let stems = std::array::from_fn(|layer| {
                if layer != 1
                    && layer != 2
                    && let Some((_, stems)) = rendered.iter().find(|(s, _)| *s == section.accompaniment())
                {
                    return Arc::clone(&stems[layer]);
                }
                render_stem(section, layer)
            });
            rendered.push((section, stems));
        }
        Self {
            sections: rendered
                .into_iter()
                .map(|(_, stems)| stems)
                .collect::<Vec<_>>()
                .try_into()
                .ok()
                .unwrap(),
        }
    }

    pub(super) fn sample(&self, layer: usize, index: i64, dawn: bool) -> f32 {
        if index < 0 || (dawn && index >= FRAMES as i64) {
            return 0.0;
        }
        let index = index as usize % if dawn { FRAMES } else { CYCLE_FRAMES };
        f32::from(self.sections[index / FRAMES][layer][index % FRAMES]) / 32767.0
    }

    #[cfg(test)]
    pub(super) fn pcm_bytes(&self) -> usize {
        let mut unique = Vec::new();
        let mut bytes = 0;
        for stem in self.sections.iter().flatten() {
            let ptr = Arc::as_ptr(stem);
            if !unique.contains(&ptr) {
                unique.push(ptr);
                bytes += stem.len() * size_of::<i16>();
            }
        }
        bytes
    }
}

fn render_stem(section: Section, layer: usize) -> Arc<[i16]> {
    let mut b = Buf::new(THEME as f32 + 0.01);
    let bass = section.bass();
    let accompaniment = section.accompaniment();
    for (bar, &root) in bass.iter().enumerate() {
        let at = (bar as f64 * BAR) as f32;
        match layer {
            0 => b.pluck(jiao(root), at, 0.13, 2.2),
            3 => {
                let pattern: &[usize] = match accompaniment {
                    Section::Contrast => &[0, 3, 6],
                    Section::Development => &[0, 3, 5, 7],
                    _ => &[0, 2, 4, 6],
                };
                for (k, &step) in pattern.iter().enumerate() {
                    if bar == 7 && k > 1 {
                        continue;
                    }
                    let t = at + (step as f64 * STEP) as f32;
                    let degree = if accompaniment == Section::Theme {
                        OSTINATO[k]
                    } else {
                        root + 5 + [0, 2, 1, 2][k]
                    };
                    b.pluck(jiao(degree), t, if k == 0 { 0.045 } else { 0.03 }, 0.55);
                    b.wood(t, if k == 0 { 0.055 } else { 0.035 }, 780.0 + k as f32 * 65.0);
                }
            }
            4 => {
                b.drum(at, 0.18, 82.0);
                let second = if accompaniment == Section::Development { 5.0 } else { 4.0 };
                if accompaniment != Section::Contrast || bar % 2 == 1 {
                    b.drum(at + (STEP * second) as f32, 0.12, 100.0);
                }
                if bar % 2 == 1 && bar != 7 {
                    b.drum(at + (STEP * 7.0) as f32, 0.09, 115.0);
                }
                if bar == 0 || bar == 4 {
                    b.gong(jiao(-10), at, 0.045);
                }
            }
            _ => {}
        }
    }
    if layer == 0 {
        let pad = drone(jiao(-5), jiao(-3));
        for (i, x) in b.data[..FRAMES].iter_mut().enumerate() {
            let edge = (i.min(FRAMES - 1 - i) as f32 / (SAMPLE_RATE as f32 * 0.18)).min(1.0);
            *x += pad.frames[i % pad.frames.len()].left * 0.048 * edge;
        }
    }
    if layer == 1 || layer == 2 {
        for Note { step, degree, len } in section.melody() {
            let at = (f64::from(step) * STEP) as f32;
            let dur = (f64::from(len) * STEP) as f32;
            let mut accent = if step % 8 == 0 { 1.0 } else { 0.82 };
            if section == Section::Dialogue {
                // 每小节交接主奏：弱声部仍托住骨架，不能把探索配器中的旋律抽空。
                let leads = (step / 8 % 2 == 0) == (layer == 1);
                accent *= if leads { 1.0 } else { 0.35 };
            }
            if section == Section::Bridge {
                accent *= if layer == 1 { 0.55 } else { 0.9 };
            }
            if layer == 1 {
                b.pluck(jiao(degree), at, 0.115 * accent, (dur * 1.15).min(2.65));
            } else {
                let degree = degree - if section == Section::Bridge { 5 } else { 0 };
                b.flute(jiao(degree), at + 0.025, dur - 0.07, 0.078 * accent);
            }
        }
    }
    if layer == 5 {
        for &Note { step, degree, len } in BELLS {
            let degree =
                if accompaniment == Section::Theme { degree } else { bass[usize::from(step / 8)] + 15 };
            b.bell(jiao(degree), (f64::from(step) * STEP) as f32, 0.09, (f64::from(len) * STEP) as f32 - 0.1);
        }
    }
    b.data.truncate(FRAMES);
    // 保留句尾长音，只处理末尾两毫秒；微量确定性三角抖动避免量化余音产生谐波。
    let mut noise = crate::synth::Noise(0x1357_9bdf);
    b.finish()
        .data
        .into_iter()
        .map(|v| (v * 32767.0 + (noise.next() + noise.next()) * 0.5).round().clamp(-32767.0, 32767.0) as i16)
        .collect::<Vec<_>>()
        .into()
}

#[cfg(test)]
pub(super) fn test_score() -> Arc<Score> {
    static SCORE: std::sync::OnceLock<Arc<Score>> = std::sync::OnceLock::new();
    Arc::clone(SCORE.get_or_init(|| Arc::new(Score::new())))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn theme_is_jiao_with_two_complete_phrases_and_tonic_cadence() {
        let midi = |degree| (69.0 + 12.0 * (jiao(degree) / 440.0).log2()).round() as i32;
        let degrees =
            MELODY.iter().chain(BELLS).map(|n| n.degree).chain(BASS).chain(OSTINATO).chain([-10, -5, -3]);
        for degree in degrees {
            assert!([4, 7, 9, 0, 2].contains(&midi(degree).rem_euclid(12)));
        }
        assert_eq!(midi(0), 52);
        assert!((jiao(-5) * 2.0 - jiao(0)).abs() < 0.001);
        let mut end = 0;
        let mut bars = [false; 8];
        for note in MELODY {
            assert_eq!(note.step, end, "主题不得缺拍或重叠");
            assert!(note.len > 0);
            end = note.step + note.len;
            bars[usize::from(note.step / 8)] = true;
        }
        assert_eq!(end, 64);
        assert!(bars.into_iter().all(|b| b));
        assert!(MELODY.iter().any(|n| n.step == 32 && n.degree == 10));
        assert_eq!(MELODY.last().unwrap().degree, 5);
        assert_eq!(BASS[7], -5);
    }

    #[test]
    fn form_changes_only_at_phrases_and_keeps_modal_theme_skeleton() {
        assert!(CYCLE_FRAMES as f64 / f64::from(SAMPLE_RATE) >= 180.0);
        for section in FORM {
            let notes = section.melody();
            let mut end = 0;
            for note in &notes {
                assert_eq!(note.step, end, "{section:?} 不能缺拍或重叠");
                end = note.step + note.len;
                let midi = (69.0 + 12.0 * (jiao(note.degree) / 440.0).log2()).round() as i32;
                assert!([4, 7, 9, 0, 2].contains(&midi.rem_euclid(12)));
            }
            assert_eq!(end, 64);
            assert_eq!(notes.last().unwrap().degree, 5);
            if matches!(section, Section::Ornament | Section::Return) {
                for original in MELODY {
                    assert!(
                        notes.iter().any(|n| n.step == original.step && n.degree == original.degree),
                        "变奏保留每个原主题音的起点和音高"
                    );
                }
            }
        }
        for frame in 1..CYCLE_FRAMES {
            if frame / FRAMES != (frame - 1) / FRAMES {
                assert_eq!(frame % (FRAMES / 2), 0, "曲式轮转只能在乐句边界");
            }
        }
    }

    /// 检查真实 PCM 的四小节混音，不以段名、编号或静音层充当“不重复”。
    #[test]
    fn audible_phrases_do_not_repeat_for_three_minutes_and_mixes_have_headroom() {
        use super::super::MusicMode;
        use std::hash::{Hash, Hasher};
        let score = test_score();
        let modes =
            [MusicMode::Title, MusicMode::Explore, MusicMode::Siege, MusicMode::Boss, MusicMode::Dawn];
        for mode in modes {
            let mut fingerprints = Vec::new();
            let mut previous_rms = 0.0;
            for phrase in 0..FORM.len() * 2 {
                let mut hash = std::collections::hash_map::DefaultHasher::new();
                let mut energy = 0.0;
                let start = phrase * FRAMES / 2;
                for index in start..start + FRAMES / 2 {
                    let samples: [f32; LAYERS] =
                        std::array::from_fn(|layer| score.sample(layer, index as i64, false));
                    let bound: f32 = samples
                        .iter()
                        .enumerate()
                        .map(|(layer, v)| {
                            v.abs() * modes.iter().map(|m| m.levels()[layer]).fold(0.0, f32::max)
                        })
                        .sum();
                    assert!(bound < 0.85, "交叉淡变的混音余量不足：{bound}");
                    let v: f32 = samples.iter().zip(mode.levels()).map(|(s, l)| s * l).sum();
                    assert!(v.is_finite() && v.abs() < 0.7);
                    energy += f64::from(v * v);
                    v.to_bits().hash(&mut hash);
                }
                let rms = (energy / (FRAMES / 2) as f64).sqrt();
                assert!(rms > 0.008, "{mode:?}/{phrase} 不能用静默凑够三分钟");
                if previous_rms > 0.0 {
                    assert!((0.45..2.2).contains(&(rms / previous_rms)), "相邻乐句响度突兀");
                }
                previous_rms = rms;
                let fingerprint = hash.finish();
                assert!(!fingerprints.contains(&fingerprint), "{mode:?} 的第 {phrase} 句完全重复");
                fingerprints.push(fingerprint);
            }
        }
        let cadence = STEP as f32 * 60.0;
        let start = (cadence * SAMPLE_RATE as f32) as usize;
        let energy: f64 = (start..FRAMES - super::super::STEP_FRAMES)
            .map(|i| f64::from(score.sample(2, i as i64, true)).powi(2))
            .sum();
        assert!((energy / (FRAMES - super::super::STEP_FRAMES - start) as f64).sqrt() > 0.025);
        for stems in &score.sections {
            for stem in stems {
                assert_eq!(stem.len(), FRAMES);
                assert!(stem.last().unwrap().unsigned_abs() < 33);
            }
        }
    }

    #[test]
    fn pcm_budget_includes_all_sfx_ambience_and_dawn_reuses_original_theme() {
        let score = test_score();
        let sfx = crate::sfx::Sfx::new();
        let ambience = crate::ambience::Ambience::new();
        assert!(score.pcm_bytes() + sfx.pcm_bytes() + ambience.pcm_bytes() < 120 * 1024 * 1024);
        for index in 0..FRAMES {
            for layer in 0..LAYERS {
                assert_eq!(score.sample(layer, index as i64, true), score.sample(layer, index as i64, false));
            }
        }
        assert_eq!(score.sample(2, FRAMES as i64, true), 0.0);
        assert!(Arc::ptr_eq(&score.sections[0][0], &score.sections[1][0]));
        assert!(!Arc::ptr_eq(&score.sections[0][1], &score.sections[1][1]));
    }

    /// 独立测量实际配置，不把编译、检查混音或离线播放耗时计入合成。
    #[test]
    #[ignore = "手动性能测量：cargo test -p lantern_audio benchmark_synthesis -- --ignored --nocapture"]
    fn benchmark_synthesis() {
        use std::time::Instant;
        for trial in 1..=3 {
            use kira::{
                AudioManager, AudioManagerSettings, backend::mock::MockBackend, clock::ClockSpeed,
                track::TrackBuilder,
            };
            let mut manager = AudioManager::<MockBackend>::new(AudioManagerSettings::default()).unwrap();
            let clock = manager.add_clock(ClockSpeed::TicksPerSecond(1.0)).unwrap();
            let mut parent = manager.add_sub_track(TrackBuilder::new()).unwrap();
            let start = Instant::now();
            let mut music = super::super::Music::new(Some(clock), Some(&mut parent));
            let init_time = start.elapsed();
            let score = music.loading.take().unwrap().recv().unwrap();
            let music_time = start.elapsed();
            let start = Instant::now();
            let sfx = crate::sfx::Sfx::new();
            let sfx_time = start.elapsed();
            let start = Instant::now();
            let ambience = crate::ambience::Ambience::new();
            let ambience_time = start.elapsed();
            let mib = |bytes: usize| bytes as f64 / 1048576.0;
            println!(
                "trial={trial} music_init={init_time:?} music_ready={music_time:?} sfx={sfx_time:?} ambience={ambience_time:?} music_pcm={:.3} MiB sfx_pcm={:.3} MiB ambience_pcm={:.3} MiB total_pcm={:.3} MiB",
                mib(score.pcm_bytes()),
                mib(sfx.pcm_bytes()),
                mib(ambience.pcm_bytes()),
                mib(score.pcm_bytes() + sfx.pcm_bytes() + ambience.pcm_bytes())
            );
        }
    }
}
