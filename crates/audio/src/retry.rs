//! 无设备时按真实时间退避；恢复后停止重试。

use std::time::Duration;

const INITIAL_DELAY: Duration = Duration::from_secs(3);
const MAX_DELAY: Duration = Duration::from_secs(30);

pub(crate) struct RetryBackoff {
    next: Option<Duration>,
    delay: Duration,
}

impl Default for RetryBackoff {
    fn default() -> Self {
        Self { next: Some(Duration::ZERO), delay: INITIAL_DELAY }
    }
}

impl RetryBackoff {
    pub(crate) fn is_due(&self, now: Duration) -> bool {
        self.next.is_some_and(|next| now >= next)
    }

    pub(crate) fn finish(&mut self, now: Duration, ready: bool) {
        if ready {
            self.next = None;
            self.delay = INITIAL_DELAY;
        } else {
            // 从本次尝试计时，切回窗口或长帧之后也不补发积压的尝试。
            self.next = Some(now + self.delay);
            self.delay = (self.delay * 2).min(MAX_DELAY);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn failures_back_off_from_three_seconds_and_cap_at_thirty() {
        let mut retry = RetryBackoff::default();
        let mut now = Duration::ZERO;
        assert!(retry.is_due(now));
        for delay in [3, 6, 12, 24, 30, 30, 30] {
            retry.finish(now, false);
            assert!(!retry.is_due(now));
            now += Duration::from_secs(delay);
            assert!(!retry.is_due(now - Duration::from_millis(1)));
            assert!(retry.is_due(now));
        }
    }

    #[test]
    fn recovery_stops_retries_and_resets_backoff() {
        let mut retry = RetryBackoff::default();
        retry.finish(Duration::ZERO, false);
        retry.finish(Duration::from_secs(3), false);
        retry.finish(Duration::from_secs(9), true);
        assert!(!retry.is_due(Duration::from_secs(9)));
        assert!(!retry.is_due(Duration::MAX));

        retry.finish(Duration::from_secs(100), false);
        assert!(!retry.is_due(Duration::from_secs(102)));
        assert!(retry.is_due(Duration::from_secs(103)));
    }

    #[test]
    fn late_attempt_does_not_burst_to_catch_up() {
        let mut retry = RetryBackoff::default();
        retry.finish(Duration::ZERO, false);
        let now = Duration::from_secs(3600);
        assert!(retry.is_due(now));
        retry.finish(now, false);
        assert!(!retry.is_due(now));
        assert!(!retry.is_due(now + Duration::from_secs(5)));
        assert!(retry.is_due(now + Duration::from_secs(6)));
    }
}
