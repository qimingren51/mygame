//! 法器的表现归属；按内容 ID 识别，不假定 RON 排列顺序。

use crate::Content;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WeaponIdentity {
    Lamp,
    Sword,
    Bell,
    Crane,
    Seal,
    CoinSword,
}

impl WeaponIdentity {
    pub const ALL: [Self; 6] =
        [Self::Lamp, Self::Sword, Self::Bell, Self::Crane, Self::Seal, Self::CoinSword];

    pub fn from_id(id: &str) -> Option<Self> {
        match id {
            "lamp" => Some(Self::Lamp),
            "sword" => Some(Self::Sword),
            "bell" => Some(Self::Bell),
            "crane" => Some(Self::Crane),
            "seal" => Some(Self::Seal),
            "coin_sword" => Some(Self::CoinSword),
            _ => None,
        }
    }

    pub fn resolve(content: &Content, weapon: Option<u16>) -> Option<Self> {
        Self::from_id(&content.weapons.get(usize::from(weapon?))?.id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identity_follows_id_after_reordering() {
        let mut c =
            Content::load(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
                .unwrap();
        c.weapons.reverse();
        for (id, identity) in
            ["lamp", "sword", "bell", "crane", "seal", "coin_sword"].into_iter().zip(WeaponIdentity::ALL)
        {
            assert_eq!(WeaponIdentity::resolve(&c, Some(c.weapon_index(id).unwrap() as u16)), Some(identity));
        }
        assert_eq!(WeaponIdentity::resolve(&c, None), None);
        assert_eq!(WeaponIdentity::resolve(&c, Some(u16::MAX)), None);
        assert_eq!(WeaponIdentity::from_id("unknown"), None);
    }
}
