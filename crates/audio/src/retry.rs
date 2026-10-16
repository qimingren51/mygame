//! 没有输出设备时按真实时间重试：先每 3 秒，失败一次间隔翻倍，最长 15 秒；恢复后停止。
//! 没有声卡的机器（CI、服务器）每次尝试都会让系统音频库在终端打一串错误，所以不能一直 3 秒一次。

use std::time::Duration;

const FIRST_INTERVAL: Duration = Duration::from_secs(3);
const MAX_INTERVAL: Duration = Duration::from_secs(15);

pub(crate) struct AudioRetry {
    next: Option<Duration>,
    interval: Duration,
    attempts: u32,
}

impl Default for AudioRetry {
    fn default() -> Self {
        Self { next: Some(Duration::ZERO), interval: FIRST_INTERVAL, attempts: 0 }
    }
}

impl AudioRetry {
    pub(crate) fn is_due(&self, now: Duration) -> bool {
        self.next.is_some_and(|next| now >= next)
    }

    /// 已经试过几次（含第一次启动）
    pub(crate) fn attempts(&self) -> u32 {
        self.attempts
    }

    pub(crate) fn finish(&mut self, now: Duration, ready: bool) {
        self.attempts += 1;
        // 从本次尝试计时，切回窗口或长帧之后也不补发积压的尝试。
        self.next = if ready { None } else { Some(now + self.interval) };
        if !ready {
            self.interval = (self.interval * 2).min(MAX_INTERVAL);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn failures_back_off_from_three_to_fifteen_seconds() {
        let mut retry = AudioRetry::default();
        let mut now = Duration::ZERO;
        assert!(retry.is_due(now));
        for wait in [3, 6, 12, 15, 15, 15] {
            retry.finish(now, false);
            assert!(!retry.is_due(now));
            now += Duration::from_secs(wait);
            assert!(!retry.is_due(now - Duration::from_millis(1)));
            assert!(retry.is_due(now));
        }
        assert_eq!(retry.attempts(), 6);
    }

    #[test]
    fn recovery_stops_retries() {
        let mut retry = AudioRetry::default();
        retry.finish(Duration::ZERO, false);
        retry.finish(Duration::from_secs(3), false);
        retry.finish(Duration::from_secs(9), true);
        assert!(!retry.is_due(Duration::from_secs(9)));
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
        assert!(!retry.is_due(now + Duration::from_secs(5)));
        assert!(retry.is_due(now + Duration::from_secs(6)));
    }
}
