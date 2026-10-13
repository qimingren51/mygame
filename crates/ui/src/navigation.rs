//! 网格按视觉上的行列移动，末行不满时夹到该行末项。
use bevy::prelude::IVec2;

pub(crate) fn grid(selected: usize, nav: IVec2, count: usize, columns: usize) -> usize {
    if count == 0 {
        return 0;
    }
    let selected = selected.min(count - 1);
    let rows = count.div_ceil(columns);
    let row = selected / columns;
    let col = selected % columns;
    if nav.y != 0 {
        let row = (row as i32 + nav.y).rem_euclid(rows as i32) as usize;
        (row * columns + col).min(count - 1)
    } else if nav.x != 0 {
        let width = columns.min(count - row * columns);
        row * columns + (col as i32 + nav.x).rem_euclid(width as i32) as usize
    } else {
        selected
    }
}

pub(crate) fn cycle_enabled(selected: usize, direction: i32, enabled: &[bool]) -> usize {
    if enabled.is_empty() {
        return 0;
    }
    let mut i = selected.min(enabled.len() - 1);
    for _ in 0..enabled.len() {
        i = (i as i32 + direction.signum()).rem_euclid(enabled.len() as i32) as usize;
        if enabled[i] {
            return i;
        }
    }
    selected.min(enabled.len() - 1)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn wraps_in_rows_and_reaches_partial_last_row() {
        assert_eq!(grid(0, IVec2::NEG_X, 7, 2), 1);
        assert_eq!(grid(5, IVec2::Y, 7, 2), 6);
        assert_eq!(grid(6, IVec2::Y, 7, 2), 0);
        assert_eq!(grid(1, IVec2::NEG_Y, 7, 2), 6);
    }
}
