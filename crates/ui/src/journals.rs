//! 结算与说书人共用的手记册。只排已拾页，未知页不显示标题或正文。
use bevy::picking::events::PointerClick;
use bevy::prelude::*;
use lantern_content::{Content, JournalDef};
use lantern_platform::{Actions, Profile};
use lantern_sim::{AppState, GameContent};

use crate::{Fonts, INK, INK_DIM, PAPER, skin::Skin, text};

#[derive(Resource, Default)]
pub(crate) struct Reader {
    pub open: bool,
    pub selected: usize,
}

#[derive(Component)]
struct Book;

pub(crate) fn register(app: &mut App) {
    app.init_resource::<Reader>()
        .add_systems(OnEnter(AppState::Run), close)
        .add_systems(Update, (input, redraw).chain().after(crate::title::input).after(crate::results::input));
}

fn close(mut reader: ResMut<Reader>) {
    reader.open = false;
}

fn pages<'a>(content: &'a Content, profile: &Profile) -> Vec<&'a JournalDef> {
    let last = profile.journal_chapter() * 6;
    let mut pages: Vec<_> =
        content.journals.iter().filter(|j| j.page <= last && profile.journals.contains(&j.page)).collect();
    pages.sort_by_key(|j| j.page);
    pages
}

fn input(
    actions: Res<Actions>,
    profile: Res<Profile>,
    content: Res<GameContent>,
    mut reader: ResMut<Reader>,
) {
    if !reader.open {
        return;
    }
    if actions.back || actions.confirm {
        reader.open = false;
        return;
    }
    let n = pages(&content.0, &profile).len();
    let dir = actions.nav.y + actions.nav.x;
    if dir != 0 && n > 0 {
        reader.selected = (reader.selected as i32 + dir).rem_euclid(n as i32) as usize;
    }
}

fn redraw(
    mut commands: Commands,
    reader: Res<Reader>,
    profile: Res<Profile>,
    content: Res<GameContent>,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    roots: Query<Entity, With<Book>>,
) {
    if !reader.is_changed() {
        return;
    }
    for e in &roots {
        commands.entity(e).despawn();
    }
    if !reader.open {
        return;
    }
    let pages = pages(&content.0, &profile);
    let selected = reader.selected.min(pages.len().saturating_sub(1));
    commands
        .spawn((
            Book,
            GlobalZIndex(50),
            Node {
                position_type: PositionType::Absolute,
                width: percent(100),
                height: percent(100),
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                row_gap: px(16),
                ..default()
            },
            BackgroundColor(Color::srgba(0.02, 0.025, 0.03, 0.97)),
        ))
        .with_children(|root| {
            root.spawn((
                Node {
                    width: px(850),
                    min_height: px(440),
                    padding: UiRect::all(px(40)),
                    flex_direction: FlexDirection::Column,
                    row_gap: px(18),
                    ..default()
                },
                skin.image("panel"),
            ))
            .with_children(|p| {
                p.spawn(text(&fonts.title, 44.0, INK, "守灯人手记"));
                if pages.is_empty() {
                    p.spawn(text(&fonts.body, 20.0, INK_DIM, "纸还散在夜路上。点灯时，留心砖缝。"));
                    return;
                }
                p.spawn(Node { flex_wrap: FlexWrap::Wrap, column_gap: px(14), row_gap: px(10), ..default() })
                    .with_children(|row| {
                        for (i, j) in pages.iter().enumerate().skip(selected / 6 * 6).take(6) {
                            row.spawn((
                                Node { padding: UiRect::all(px(8)), ..default() },
                                BackgroundColor(if i == selected {
                                    Color::srgba(0.3, 0.2, 0.1, 0.15)
                                } else {
                                    Color::NONE
                                }),
                            ))
                            .with_children(|b| {
                                b.spawn(text(&fonts.body, 18.0, INK, &format!("第 {} 页", j.page)));
                            })
                            .observe(
                                move |_: On<PointerClick>, mut reader: ResMut<Reader>| {
                                    reader.selected = i;
                                },
                            );
                        }
                    });
                let j = pages[selected];
                let chapter = ["规矩", "那一夜", "五方", "熄灭", "借"][usize::from((j.page - 1) / 6)];
                p.spawn(text(&fonts.body, 17.0, INK_DIM, &format!("{chapter}　·　第 {} 页", j.page)));
                p.spawn((Node { max_width: px(750), ..default() }, text(&fonts.body, 23.0, INK, &j.text)));
                if !j.clue.is_empty() {
                    p.spawn(text(&fonts.body, 17.0, INK_DIM, &j.clue));
                }
            });
            root.spawn(Node { column_gap: px(30), ..default() }).with_children(|row| {
                for (label, direction) in [("上一页", -1), ("合上", 0), ("下一页", 1)] {
                    let n = pages.len();
                    row.spawn((
                        Node { padding: UiRect::all(px(10)), ..default() },
                        text(&fonts.body, 20.0, PAPER, label),
                    ))
                    .observe(move |_: On<PointerClick>, mut r: ResMut<Reader>| {
                        if direction == 0 {
                            r.open = false;
                        } else if n > 0 {
                            r.selected = (r.selected as i32 + direction).rem_euclid(n as i32) as usize;
                        }
                    });
                }
            });
            root.spawn(text(
                &fonts.body,
                18.0,
                PAPER,
                "方向键 / 手柄方向键　翻页　　Esc / Enter / 手柄 A、B　合上",
            ));
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reader_only_lists_owned_pages_in_unlocked_chapters() {
        let c = Content::load(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
            .unwrap();
        let mut p = Profile::default();
        // 即使存档留有后卷页码，标题、正文和翻页范围也要一起守住门槛。
        p.journals.extend([1, 7, 13, 19, 25, 30]);
        let listed = |p: &Profile| pages(&c, p).iter().map(|j| j.page).collect::<Vec<_>>();
        assert_eq!(listed(&p), [1]);
        p.events.insert("qingqiu_entered".into());
        assert_eq!(listed(&p), [1, 7]);
        p.events.insert("qingqiu_left_lantern".into());
        assert_eq!(listed(&p), [1, 7, 13]);
    }
}
