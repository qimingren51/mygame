//! 青藤与万木春：真实连线、命中返光、短缠绕共用一张网格，不生成逐藤/逐粒实体。
//! 只有茎叶跟随当前有效句柄；已结算命中的返光可独立收完，不能借此保留一条断藤。

use std::f32::consts::TAU;

use bevy::asset::RenderAssetUsages;
use bevy::camera::visibility::NoFrustumCulling;
use bevy::mesh::PrimitiveTopology;
use bevy::prelude::*;
use bevy::sprite_render::AlphaMode2d;
use lantern_content::{Content, WeaponBehavior};
use lantern_core::step::DT;
use lantern_sim::combat::Source;
use lantern_sim::enemies::EnemyHandle;
use lantern_sim::weapons::Form;
use lantern_sim::{
    AppState, Arsenal, Enemies, GameContent, Player, Pos, PrevPos, RunState, SimEvent, SimOutbox, Tick,
};

use crate::telegraphs::Readability;
use crate::{Feel, layer, to_screen};

const RETURN_TIME: f32 = 0.30;
const THORN_TIME: f32 = 0.10;
const MAX_PULSES: usize = 256;
const SEEK_TICKS: u64 = 60;
/// 藤在脚点上方少许悬起；两个端点采用同一高度，不改变连线距离。
const LIFT: Vec2 = Vec2::new(0.0, -8.0);
const INK: Color = Color::srgb(0.09, 0.08, 0.055);
const STEM: Color = Color::srgb(0.28, 0.55, 0.34);
const LEAF: Color = Color::srgb(0.43, 0.69, 0.43);
const LIGHT: Color = Color::srgb(0.78, 0.94, 0.56);

#[derive(Clone, Copy, Debug)]
struct Curve {
    from: Vec2,
    a: Vec2,
    b: Vec2,
    to: Vec2,
}

impl Curve {
    fn between(from: Vec2, to: Vec2, phase: f32, time: f32) -> Self {
        let delta = to - from;
        let side = delta.normalize_or_zero().perp();
        let bend = (delta.length() * 0.12).min(24.0);
        let sway = (time * 2.0 + phase).sin() * 3.0;
        let sign = if phase.sin() >= 0.0 { 1.0 } else { -1.0 };
        Self {
            from,
            a: from.lerp(to, 0.32) + side * (bend * sign + sway),
            b: from.lerp(to, 0.73) - side * (bend * sign * 0.45 - sway * 0.5),
            to,
        }
    }

    fn point(self, t: f32) -> Vec2 {
        let t = t.clamp(0.0, 1.0);
        let v = 1.0 - t;
        self.from * v.powi(3) + self.a * (3.0 * v * v * t) + self.b * (3.0 * v * t * t) + self.to * t.powi(3)
    }

    fn tangent(self, t: f32) -> Vec2 {
        (self.point((t + 0.01).min(1.0)) - self.point((t - 0.01).max(0.0))).normalize_or(Vec2::X)
    }
}

fn phase(target: EnemyHandle) -> f32 {
    (target.raw() & 255) as f32 * 0.37
}

struct Link {
    weapon: u16,
    target: EnemyHandle,
    curve: Curve,
    foot: Vec2,
    radius: f32,
    root: f32,
    phase: f32,
}

fn live_links(
    c: &Content,
    arsenal: &Arsenal,
    en: &Enemies,
    player: Vec2,
    alpha: f32,
    time: f32,
) -> Vec<Link> {
    let mut links = Vec::new();
    for slot in &arsenal.0 {
        let WeaponBehavior::Vine { bind, .. } = slot.behavior(c) else { continue };
        let Some(vine) = &slot.vine else { continue };
        for link in vine.links.iter().take(slot.count as usize) {
            let Some(target) = link.target else { continue };
            let Some(i) = en.resolve(target) else { continue };
            if en.cloaked[i] {
                continue;
            }
            let foot = Vec2::new(en.px[i], en.py[i]).lerp(Vec2::new(en.x[i], en.y[i]), alpha);
            let phase = phase(target);
            links.push(Link {
                weapon: slot.def as u16,
                target,
                curve: Curve::between(player + LIFT, foot + LIFT, phase, time),
                foot,
                radius: en.r[i],
                root: if slot.form == Form::Evolved && bind.is_some() { en.root[i].max(0.0) } else { 0.0 },
                phase,
            });
        }
    }
    links
}

#[derive(Clone, Copy)]
struct Pulse {
    weapon: u16,
    target: EnemyHandle,
    impact: Vec2,
    age: f32,
    crit: bool,
}

fn vine_hit(c: &Content, event: &SimEvent) -> Option<Pulse> {
    let SimEvent::Hit {
        weapon: Some(weapon), source: Source::Weapon(source), target, impact_pos, crit, ..
    } = *event
    else {
        return None;
    };
    if weapon != source
        || !c.weapons.get(weapon as usize).is_some_and(|w| matches!(w.behavior, WeaponBehavior::Vine { .. }))
    {
        return None;
    }
    Some(Pulse { weapon, target, impact: impact_pos, age: 0.0, crit })
}

#[derive(Resource, Default)]
pub(crate) struct VineView {
    pulses: Vec<Pulse>,
    tick: Option<u64>,
}

impl VineView {
    /// 同 Tick 不重复消费事件；暂停也不推进。跳播只重建实时藤链，不补播旧命中。
    fn advance(&mut self, tick: u64) -> bool {
        let previous = self.tick.replace(tick);
        if previous.is_some_and(|old| tick < old || tick - old > SEEK_TICKS) {
            self.pulses.clear();
            return false;
        }
        if previous == Some(tick) {
            return false;
        }
        let dt = previous.map_or(0.0, |old| (tick - old) as f32 * DT);
        self.pulses.retain_mut(|pulse| {
            pulse.age += dt;
            pulse.age < RETURN_TIME
        });
        true
    }

    fn push(&mut self, pulse: Pulse) {
        if self.pulses.len() == MAX_PULSES {
            self.pulses.remove(0);
        }
        self.pulses.push(pulse);
    }
}

#[derive(Component)]
pub(crate) struct VineMesh;

pub(crate) fn spawn(
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<ColorMaterial>>,
    mut state: ResMut<VineView>,
) {
    *state = VineView::default();
    commands.spawn((
        VineMesh,
        Mesh2d(meshes.add(Picture::default().finish())),
        MeshMaterial2d(materials.add(ColorMaterial { alpha_mode: AlphaMode2d::Blend, ..default() })),
        Transform::from_xyz(0.0, 0.0, layer::WEAPONS + 0.4),
        Visibility::Hidden,
        NoFrustumCulling,
        DespawnOnExit(AppState::Run),
    ));
}

#[derive(Default)]
struct Picture {
    positions: Vec<[f32; 3]>,
    colors: Vec<[f32; 4]>,
}

impl Picture {
    fn triangle(&mut self, points: [Vec2; 3], colors: [Color; 3], z: f32) {
        for (point, color) in points.into_iter().zip(colors) {
            self.positions.push(to_screen(point).extend(z).to_array());
            self.colors.push(color.to_linear().to_f32_array());
        }
    }

    fn ribbon(&mut self, points: &[Vec2], width: f32, color: Color, z: f32, clear_start: bool) {
        if points.len() < 2 {
            return;
        }
        let normals: Vec<_> = (0..points.len())
            .map(|i| {
                (points[(i + 1).min(points.len() - 1)] - points[i.saturating_sub(1)])
                    .normalize_or_zero()
                    .perp()
            })
            .collect();
        for i in 0..points.len() - 1 {
            let (a, b) = (points[i], points[i + 1]);
            let (na, nb) = (normals[i], normals[i + 1]);
            let half = width * 0.5;
            // 近身短段收细并退开，多个目标也不能在主角脚下堆出一枚硬结。
            let strength = |point: Vec2| {
                if clear_start { ((point.distance(points[0]) - 8.0) / 18.0).clamp(0.0, 1.0) } else { 1.0 }
            };
            let (ga, gb) = (strength(a), strength(b));
            let (ha, hb) = (half * ga, half * gb);
            let (ca, cb) = (color.with_alpha(color.alpha() * ga), color.with_alpha(color.alpha() * gb));
            self.triangle([a - na * ha, a + na * ha, b + nb * hb], [ca, ca, cb], z);
            self.triangle([a - na * ha, b + nb * hb, b - nb * hb], [ca, cb, cb], z);
            for side in [-1.0, 1.0] {
                let (ai, bi) = (a + na * ha * side, b + nb * hb * side);
                let (ao, bo) = (a + na * (ha + 0.55) * side, b + nb * (hb + 0.55) * side);
                self.triangle([ai, ao, bo], [ca, ca.with_alpha(0.0), cb.with_alpha(0.0)], z);
                self.triangle([ai, bo, bi], [ca, cb.with_alpha(0.0), cb], z);
            }
        }
    }

    fn leaf(&mut self, root: Vec2, axis: Vec2, side: f32, gain: f32) {
        let dir = (axis * 0.4 + axis.perp() * side).normalize_or(Vec2::Y);
        let tip = root + dir * 8.0;
        let center = root.lerp(tip, 0.5);
        let edge = dir.perp() * 2.6;
        self.triangle([root, center + edge, tip], [INK.with_alpha(gain * 0.8); 3], 0.15);
        self.triangle([root, tip, center - edge], [INK.with_alpha(gain * 0.8); 3], 0.15);
        self.triangle([root, center + edge * 0.7, tip], [LEAF.with_alpha(gain * 0.8); 3], 0.17);
        self.triangle([root, tip, center - edge * 0.7], [STEM.with_alpha(gain * 0.9); 3], 0.17);
    }

    fn vine(&mut self, link: &Link, lite: bool, gain: f32) {
        let segments = if lite { 10 } else { 20 };
        let points: Vec<_> = (0..=segments).map(|i| link.curve.point(i as f32 / segments as f32)).collect();
        self.ribbon(&points, 5.4, INK.with_alpha(gain * 0.82), 0.0, true);
        self.ribbon(&points, 3.1, STEM.with_alpha(gain * 0.85), 0.05, true);
        self.ribbon(&points, 0.7, LEAF.with_alpha(gain * 0.7), 0.10, true);
        if link.curve.from.distance_squared(link.curve.to) >= 36.0 * 36.0 {
            for i in 0..if lite { 1 } else { 2 } {
                let t = 0.35 + i as f32 * 0.32;
                if link.curve.point(t).distance(link.curve.from) < 26.0 {
                    continue;
                }
                self.leaf(link.curve.point(t), link.curve.tangent(t), if i == 0 { 1.0 } else { -1.0 }, gain);
            }
        }
    }

    fn binding(&mut self, link: &Link, lite: bool, time: f32, gain: f32) {
        if link.root <= 0.0 {
            return;
        }
        let count = if lite { 14 } else { 28 };
        let radius = link.radius.clamp(5.0, 32.0);
        let fade = (link.root / 0.20).clamp(0.0, 1.0) * gain;
        let points: Vec<_> = (0..=count)
            .map(|i| {
                let t = i as f32 / count as f32;
                let angle = t * TAU * 1.6 + link.phase + time * 0.7;
                link.foot
                    + Vec2::new(
                        angle.cos() * radius * 0.72,
                        -4.0 - t * radius * 1.7 + angle.sin() * radius * 0.16,
                    )
            })
            .collect();
        self.ribbon(&points, 3.6, INK.with_alpha(fade * 0.75), 0.2, false);
        self.ribbon(&points, 1.8, LEAF.with_alpha(fade * 0.85), 0.22, false);
    }

    fn dot(&mut self, center: Vec2, radius: f32, color: Color, z: f32) {
        for i in 0..8 {
            let a = Vec2::from_angle(i as f32 * TAU / 8.0) * radius;
            let b = Vec2::from_angle((i + 1) as f32 * TAU / 8.0) * radius;
            self.triangle(
                [center, center + a, center + b],
                [color, color.with_alpha(0.0), color.with_alpha(0.0)],
                z,
            );
        }
    }

    fn pulse(&mut self, pulse: &Pulse, links: &[Link], player: Vec2, time: f32, lite: bool, gain: f32) {
        let curve = pulse_curve(pulse, links, player, time);
        let u = (pulse.age / RETURN_TIME).clamp(0.0, 1.0);
        let at = curve.point(1.0 - u);
        let fade = ((1.0 - u) * 5.0).min(1.0) * gain;
        let size = if pulse.crit { 2.2 } else { 1.8 };
        self.dot(at, size * 2.2, LEAF.with_alpha(fade * 0.30), 0.3);
        self.dot(at, size, LIGHT.with_alpha(fade * 0.95), 0.32);
        if pulse.age < THORN_TIME {
            let fade = (1.0 - pulse.age / THORN_TIME) * gain;
            let count = if lite { 2 } else { 3 };
            for i in 0..count {
                let dir = Vec2::from_angle(phase(pulse.target) + i as f32 * TAU / count as f32);
                let base = pulse.impact + LIFT + dir * 2.0;
                self.triangle(
                    [base + dir.perp(), base + dir * (4.0 + fade * 3.0), base - dir.perp()],
                    [LEAF.with_alpha(fade * 0.8), LIGHT.with_alpha(fade * 0.8), STEM.with_alpha(fade * 0.8)],
                    0.35,
                );
            }
        }
    }

    fn finish(self) -> Mesh {
        Mesh::new(
            PrimitiveTopology::TriangleList,
            RenderAssetUsages::MAIN_WORLD | RenderAssetUsages::RENDER_WORLD,
        )
        .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, self.positions)
        .with_inserted_attribute(Mesh::ATTRIBUTE_COLOR, self.colors)
    }
}

fn pulse_curve(pulse: &Pulse, links: &[Link], player: Vec2, time: f32) -> Curve {
    links.iter().find(|link| link.weapon == pulse.weapon && link.target == pulse.target).map_or_else(
        || Curve::between(player + LIFT, pulse.impact + LIFT, phase(pulse.target), time),
        |link| link.curve,
    )
}

pub(crate) fn draw(
    content: Res<GameContent>,
    arsenal: Option<Res<Arsenal>>,
    enemies: Option<Res<Enemies>>,
    tick: Option<Res<Tick>>,
    run: Option<Res<State<RunState>>>,
    fixed: Res<Time<Fixed>>,
    player: Single<(&Pos, &PrevPos), With<Player>>,
    outbox: Res<SimOutbox>,
    feel: Res<Feel>,
    readability: Res<Readability>,
    mut state: ResMut<VineView>,
    q: Single<(&Mesh2d, &mut Visibility), With<VineMesh>>,
    mut meshes: ResMut<Assets<Mesh>>,
) {
    let (handle, mut visibility) = q.into_inner();
    let (Some(arsenal), Some(enemies), Some(tick)) = (arsenal, enemies, tick) else {
        *state = VineView::default();
        *visibility = Visibility::Hidden;
        return;
    };
    if run.is_some_and(|s| *s.get() == RunState::Over)
        || outbox.0.iter().any(|event| matches!(event, SimEvent::PlayerDied))
    {
        *state = VineView::default();
        *visibility = Visibility::Hidden;
        return;
    }
    let (pos, previous) = *player;
    let alpha = fixed.overstep_fraction();
    let player = previous.0.lerp(pos.0, alpha);
    let time = tick.secs();
    let links = live_links(&content.0, &arsenal, &enemies, player, alpha, time);
    if state.advance(tick.0) {
        for event in &outbox.0 {
            if let Some(pulse) = vine_hit(&content.0, event) {
                state.push(pulse);
            }
        }
    }
    let mut picture = Picture::default();
    let gain = readability.gain;
    for link in &links {
        picture.vine(link, feel.lite, gain);
        picture.binding(link, feel.lite, time, gain);
    }
    for pulse in &state.pulses {
        picture.pulse(pulse, &links, player, time, feel.lite, gain);
    }
    if picture.positions.is_empty() {
        *visibility = Visibility::Hidden;
    } else {
        *visibility = Visibility::Visible;
        if let Some(mut mesh) = meshes.get_mut(&handle.0) {
            *mesh = picture.finish();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lantern_content::Element;
    use lantern_sim::HitKind;
    use lantern_sim::weapons::WeaponSlot;

    fn fixture() -> (Content, Arsenal, Enemies, EnemyHandle) {
        let content =
            Content::load(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
                .unwrap();
        let mut enemies = Enemies::default();
        let i = enemies.alloc().unwrap();
        enemies.x[i] = 80.0;
        enemies.y[i] = 20.0;
        enemies.px[i] = 76.0;
        enemies.py[i] = 18.0;
        enemies.r[i] = 12.0;
        let target = enemies.handle(i);
        let mut slot = WeaponSlot::new(content.weapon_index("vine").unwrap());
        slot.count = 1;
        slot.radius = 140.0;
        slot.vine = Some(default());
        let state = slot.vine.as_mut().unwrap();
        state.links.resize_with(1, Default::default);
        state.links[0].target = Some(target);
        (content, Arsenal(vec![slot]), enemies, target)
    }

    #[test]
    fn stems_only_follow_current_live_links_and_never_reuse_a_dead_handle() {
        let (content, mut arsenal, mut enemies, target) = fixture();
        let links = live_links(&content, &arsenal, &enemies, Vec2::ZERO, 0.5, 1.0);
        assert_eq!(links.len(), 1);
        assert_eq!(links[0].curve.point(0.0), LIFT);
        assert_eq!(links[0].curve.point(1.0), Vec2::new(78.0, 19.0) + LIFT);
        arsenal.0[0].vine.as_mut().unwrap().links[0].target = None;
        assert!(live_links(&content, &arsenal, &enemies, Vec2::ZERO, 0.5, 1.0).is_empty());
        arsenal.0[0].vine.as_mut().unwrap().links[0].target = Some(target);
        let i = enemies.resolve(target).unwrap();
        enemies.cloaked[i] = true;
        assert!(live_links(&content, &arsenal, &enemies, Vec2::ZERO, 0.5, 1.0).is_empty());
        enemies.kill(i);
        let replacement = enemies.alloc().unwrap();
        assert_eq!(replacement, i);
        assert_ne!(enemies.handle(replacement), target);
        assert!(live_links(&content, &arsenal, &enemies, Vec2::ZERO, 0.5, 1.0).is_empty());
        assert!(Curve::between(Vec2::ZERO, Vec2::ZERO, 1.0, 4.0).point(0.5).is_finite());
    }

    #[test]
    fn only_confirmed_vine_weapon_hits_start_a_return_pulse() {
        let (content, arsenal, _, target) = fixture();
        let weapon = arsenal.0[0].def as u16;
        let hit = SimEvent::Hit {
            pos: Vec2::X * 80.0,
            impact_pos: Vec2::X * 72.0,
            incoming_dir: Vec2::X,
            weapon: Some(weapon),
            source: Source::Weapon(weapon),
            target,
            damage: 10.0,
            crit: false,
            kind: HitKind::Normal,
            element: Some(Element::Wood),
        };
        assert!(vine_hit(&content, &hit).is_some());
        for source in [Source::Burn, Source::Reaction(0), Source::Weapon(weapon + 1)] {
            let mut unrelated = hit;
            if let SimEvent::Hit { source: value, .. } = &mut unrelated {
                *value = source;
            }
            assert!(vine_hit(&content, &unrelated).is_none(), "元素色或weapon旁注不能伪造青藤命中");
        }
    }

    #[test]
    fn binding_requires_evolution_and_real_root_and_old_pulses_do_not_retarget() {
        let (content, mut arsenal, mut enemies, target) = fixture();
        let i = enemies.resolve(target).unwrap();
        enemies.root[i] = 0.8;
        assert_eq!(live_links(&content, &arsenal, &enemies, Vec2::ZERO, 1.0, 1.0)[0].root, 0.0);
        arsenal.0[0].form = Form::Evolved;
        assert_eq!(live_links(&content, &arsenal, &enemies, Vec2::ZERO, 1.0, 1.0)[0].root, 0.8);
        enemies.root[i] = 0.0;
        assert_eq!(live_links(&content, &arsenal, &enemies, Vec2::ZERO, 1.0, 1.0)[0].root, 0.0);
        let pulse = Pulse {
            weapon: arsenal.0[0].def as u16,
            target,
            impact: Vec2::new(60.0, 20.0),
            age: 0.0,
            crit: false,
        };
        enemies.kill(i);
        let next = enemies.alloc().unwrap();
        enemies.x[next] = 160.0;
        arsenal.0[0].vine.as_mut().unwrap().links[0].target = Some(enemies.handle(next));
        let links = live_links(&content, &arsenal, &enemies, Vec2::ZERO, 1.0, 1.0);
        assert_eq!(links.len(), 1);
        let curve = pulse_curve(&pulse, &links, Vec2::ZERO, 1.0);
        assert_eq!(curve.to, pulse.impact + LIFT, "已死目标的返光只记住实际命中点，不借用新妖物");
        assert_ne!(curve.to, links[0].curve.to);
    }

    #[test]
    fn hit_pulses_hold_when_paused_and_clear_on_replay_seek() {
        let mut state = VineView::default();
        let pulse =
            Pulse { weapon: 0, target: EnemyHandle::from_raw(0), impact: Vec2::X, age: 0.0, crit: false };
        assert!(state.advance(5));
        state.push(pulse);
        assert!(!state.advance(5));
        assert_eq!(state.pulses[0].age, 0.0);
        assert!(state.advance(9));
        assert!(state.pulses[0].age > 0.0);
        assert!(state.advance(40));
        assert!(state.pulses.is_empty());
        state.push(pulse);
        assert!(!state.advance(1));
        assert!(state.pulses.is_empty());
        assert!(state.advance(2));
        state.push(pulse);
        assert!(!state.advance(1000));
        assert!(state.pulses.is_empty());
    }
}
