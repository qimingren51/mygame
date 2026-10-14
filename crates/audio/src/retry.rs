//! 无设备时每隔三秒真实时间重试；恢复后停止重试。

use std::time::Duration;

const RETRY_INTERVAL: Duration = Duration::from_secs(3);

pub(crate) struct AudioRetry {
    next: Option<Duration>,
}

impl Default for AudioRetry {
    fn default() -> Self {
        Self { next: Some(Duration::ZERO) }
    }
}

impl AudioRetry {
    pub(crate) fn is_due(&self, now: Duration) -> bool {
        self.next.is_some_and(|next| now >= next)
    }

    pub(crate) fn finish(&mut self, now: Duration, ready: bool) {
        // 从本次尝试计时，切回窗口或长帧之后也不补发积压的尝试。
        self.next = if ready { None } else { Some(now + RETRY_INTERVAL) };
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn failures_retry_every_three_seconds() {
        let mut retry = AudioRetry::default();
        let mut now = Duration::ZERO;
        assert!(retry.is_due(now));
        for _ in 0..10 {
            retry.finish(now, false);
            assert!(!retry.is_due(now));
            now += Duration::from_secs(3);
            assert!(!retry.is_due(now - Duration::from_millis(1)));
            assert!(retry.is_due(now));
        }
    }

    #[test]
    fn recovery_stops_retries() {
        let mut retry = AudioRetry::default();
        retry.finish(Duration::ZERO, false);
        retry.finish(Duration::from_secs(3), false);
        retry.finish(Duration::from_secs(6), true);
        assert!(!retry.is_due(Duration::from_secs(6)));
        assert!(!retry.is_due(Duration::MAX));
    }

    #[test]
    fn late_attempt_does_not_burst_to_catch_up() {
        let mut retry = AudioRetry::default();
        retry.finish(Duration::ZERO, false);
        let now = Duration::from_secs(3600);
        assert!(retry.is_due(now));
        retry.finish(now, false);
        assert!(!retry.is_due(now));
        assert!(!retry.is_due(now + Duration::from_secs(2)));
        assert!(retry.is_due(now + Duration::from_secs(3)));
    }
}
