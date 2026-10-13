//! 界面只提交意图，存档写入与即时消息统一在平台层执行。

use bevy::prelude::*;
use lantern_sim::{AppState, Flow, GameContent, ReplayPlayback, RunMode, RunSetup, RunState};

use crate::profile::{LastPick, Recorded, RunRecord};
use crate::{HubNews, Profile};

pub enum ProfileCommand {
    BuyMeta(String),
    BuyAttribute(String),
    RefundAttributes,
    ToggleAttribute(String),
    Pick(LastPick),
    SawScroll {
        region: String,
        dawn: bool,
    },
    /// 长卷已经呈现，跳过或立刻离开也算看过。
    SawHub,
}

impl Command for ProfileCommand {
    type Out = ();
    fn apply(self, world: &mut World) {
        let content = world.resource::<GameContent>().0.clone();
        world.resource_scope(|world, mut p: Mut<Profile>| {
            let mut news = world.resource_mut::<HubNews>();
            let changed = match self {
                Self::BuyMeta(id) => {
                    let bought = p.buy_meta(&content, &id);
                    news.meta_lit |= bought;
                    bought
                }
                Self::BuyAttribute(id) => p.buy_attribute(&content, &id),
                Self::RefundAttributes => {
                    let refunded = p.refund_attributes() > 0;
                    news.refunded |= refunded;
                    refunded
                }
                Self::ToggleAttribute(id) => {
                    p.toggle_attribute(&content, &id);
                    true
                }
                Self::Pick(last) => {
                    p.last = last;
                    true
                }
                Self::SawScroll { region, dawn } => {
                    p.saw_scroll(&region, dawn);
                    true
                }
                Self::SawHub => {
                    p.see_hub(&content, &news);
                    *news = HubNews::default();
                    true
                }
            };
            if changed && let Err(e) = p.save() {
                warn!("保存存档失败：{e}");
            }
        });
    }
}

/// 本次结算的存档结果，供界面只读。
#[derive(Resource, Default)]
pub struct LastRecorded {
    pub recorded: Recorded,
    pub counts: bool,
}

pub(crate) fn register(app: &mut App) {
    app.init_resource::<HubNews>()
        .init_resource::<LastRecorded>()
        .add_systems(OnEnter(AppState::Title), upgrade)
        .add_systems(OnEnter(RunState::Over), record);
}

fn upgrade(content: Res<GameContent>, mut p: ResMut<Profile>) {
    if p.upgrade(&content.0)
        && let Err(e) = p.save()
    {
        warn!("保存存档失败：{e}");
    }
}

fn record(
    content: Res<GameContent>,
    flow: Res<Flow>,
    setup: Res<RunSetup>,
    playback: Option<Res<ReplayPlayback>>,
    mut p: ResMut<Profile>,
    mut news: ResMut<HubNews>,
    mut last: ResMut<LastRecorded>,
) {
    *last = LastRecorded::default();
    let Some(r) = &flow.result else { return };
    last.counts = playback.is_none() && !matches!(setup.mode, RunMode::Bench { .. }) && !setup.god;
    if !last.counts {
        return;
    }
    let before = p.clone();
    last.recorded = p.record(
        &content.0,
        RunRecord { result: r, tier: setup.tier, attributes: !setup.attributes.is_empty() },
    );
    *news = HubNews::after_run(&content.0, &before, &p, r, &last.recorded);
    if let Err(e) = p.save() {
        warn!("保存存档失败：{e}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{path::Path, sync::Arc};

    #[test]
    fn commands_apply_purchases_and_only_acknowledge_presented_lines() {
        let c =
            lantern_content::Content::load(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
                .unwrap();
        let mut world = World::new();
        world.insert_resource(GameContent(Arc::new(c)));
        world.insert_resource(Profile::default());
        world.insert_resource(HubNews::default());
        world.resource_mut::<Profile>().oil = 200;
        ProfileCommand::SawHub.apply(&mut world);
        ProfileCommand::BuyMeta("luck".into()).apply(&mut world);
        assert_eq!(world.resource::<Profile>().oil, 0);
        assert!(world.resource::<HubNews>().meta_lit);
        ProfileCommand::BuyMeta("luck".into()).apply(&mut world);
        assert_eq!(world.resource::<Profile>().meta_level("luck"), 1, "不足时不扣油、不升级");
        ProfileCommand::SawHub.apply(&mut world);
        let p = world.resource::<Profile>();
        assert!(p.hub_lights_seen.contains("meta/luck/1"));
        assert!(p.hub_lines_seen.contains("smith_first_light"));
        assert!(!world.resource::<HubNews>().meta_lit, "即时消息只在本次呈现");
    }
}
