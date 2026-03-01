use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{Mutex, watch};
use tokio::time;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum WatchdogMode {
    Normal,
    GrokkingRun,
}

#[derive(Debug, Clone, Copy)]
pub struct ResourceBudget {
    pub boinc_gpu_pct: f32,
    pub folding_gpu_pct: f32,
    pub uft_gpu_pct: f32,
}

impl ResourceBudget {
    pub fn normal() -> Self {
        Self {
            boinc_gpu_pct: 15.0,
            folding_gpu_pct: 10.0,
            uft_gpu_pct: 75.0,
        }
    }

    pub fn grokking() -> Self {
        Self {
            boinc_gpu_pct: 0.0,
            folding_gpu_pct: 0.0,
            uft_gpu_pct: 100.0,
        }
    }
}

#[derive(Debug, Clone)]
pub struct WatchdogState {
    pub mode: WatchdogMode,
    pub budget: ResourceBudget,
    pub boinc_running: bool,
    pub folding_running: bool,
    pub violations: u32,
    pub grokking_remaining_secs: u64,
}

pub struct Watchdog {
    state: Arc<Mutex<WatchdogState>>,
    mode_tx: watch::Sender<WatchdogMode>,
    mode_rx: watch::Receiver<WatchdogMode>,
}

impl Watchdog {
    pub fn new() -> Self {
        let (mode_tx, mode_rx) = watch::channel(WatchdogMode::Normal);
        Self {
            state: Arc::new(Mutex::new(WatchdogState {
                mode: WatchdogMode::Normal,
                budget: ResourceBudget::normal(),
                boinc_running: true,
                folding_running: true,
                violations: 0,
                grokking_remaining_secs: 0,
            })),
            mode_tx,
            mode_rx,
        }
    }

    pub fn subscribe(&self) -> watch::Receiver<WatchdogMode> {
        self.mode_rx.clone()
    }

    pub async fn status(&self) -> WatchdogState {
        self.state.lock().await.clone()
    }

    pub async fn trigger_grokking_run(&self, duration_secs: u64) {
        let mut state = self.state.lock().await;
        state.mode = WatchdogMode::GrokkingRun;
        state.budget = ResourceBudget::grokking();
        state.boinc_running = false;
        state.folding_running = false;
        state.grokking_remaining_secs = duration_secs;
        let _ = self.mode_tx.send(WatchdogMode::GrokkingRun);
    }

    pub async fn end_grokking_run(&self) {
        let mut state = self.state.lock().await;
        state.mode = WatchdogMode::Normal;
        state.budget = ResourceBudget::normal();
        state.boinc_running = true;
        state.folding_running = true;
        state.grokking_remaining_secs = 0;
        let _ = self.mode_tx.send(WatchdogMode::Normal);
    }

    pub async fn record_violation(&self) {
        let mut state = self.state.lock().await;
        state.violations += 1;
    }

    pub async fn check_resource_compliance(
        &self,
        boinc_actual_pct: f32,
        folding_actual_pct: f32,
    ) -> bool {
        let state = self.state.lock().await;
        if state.mode == WatchdogMode::GrokkingRun {
            return true;
        }
        let boinc_ok = boinc_actual_pct >= state.budget.boinc_gpu_pct * 0.8;
        let folding_ok = folding_actual_pct >= state.budget.folding_gpu_pct * 0.8;
        boinc_ok && folding_ok
    }

    pub fn spawn_timer(self: &Arc<Self>, duration_secs: u64) -> tokio::task::JoinHandle<()> {
        let watchdog = Arc::clone(self);
        tokio::spawn(async move {
            let mut remaining = duration_secs;
            while remaining > 0 {
                time::sleep(Duration::from_secs(1)).await;
                remaining -= 1;
                let mut state = watchdog.state.lock().await;
                state.grokking_remaining_secs = remaining;
            }
            watchdog.end_grokking_run().await;
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_normal_mode_defaults() {
        let wd = Watchdog::new();
        let status = wd.status().await;
        assert_eq!(status.mode, WatchdogMode::Normal);
        assert!(status.boinc_running);
        assert!(status.folding_running);
        assert_eq!(status.budget.boinc_gpu_pct, 15.0);
        assert_eq!(status.budget.folding_gpu_pct, 10.0);
        assert_eq!(status.budget.uft_gpu_pct, 75.0);
    }

    #[tokio::test]
    async fn test_grokking_run_pauses_distributed() {
        let wd = Watchdog::new();
        wd.trigger_grokking_run(300).await;
        let status = wd.status().await;
        assert_eq!(status.mode, WatchdogMode::GrokkingRun);
        assert!(!status.boinc_running);
        assert!(!status.folding_running);
        assert_eq!(status.budget.uft_gpu_pct, 100.0);
        assert_eq!(status.grokking_remaining_secs, 300);
    }

    #[tokio::test]
    async fn test_end_grokking_restores_normal() {
        let wd = Watchdog::new();
        wd.trigger_grokking_run(60).await;
        wd.end_grokking_run().await;
        let status = wd.status().await;
        assert_eq!(status.mode, WatchdogMode::Normal);
        assert!(status.boinc_running);
        assert!(status.folding_running);
    }

    #[tokio::test]
    async fn test_compliance_check_normal() {
        let wd = Watchdog::new();
        assert!(wd.check_resource_compliance(15.0, 10.0).await);
        assert!(wd.check_resource_compliance(12.0, 8.0).await);
        assert!(!wd.check_resource_compliance(5.0, 3.0).await);
    }

    #[tokio::test]
    async fn test_compliance_always_true_in_grokking() {
        let wd = Watchdog::new();
        wd.trigger_grokking_run(60).await;
        assert!(wd.check_resource_compliance(0.0, 0.0).await);
    }

    #[tokio::test]
    async fn test_violation_counter() {
        let wd = Watchdog::new();
        wd.record_violation().await;
        wd.record_violation().await;
        let status = wd.status().await;
        assert_eq!(status.violations, 2);
    }

    #[tokio::test]
    async fn test_mode_subscription() {
        let wd = Watchdog::new();
        let mut rx = wd.subscribe();
        assert_eq!(*rx.borrow(), WatchdogMode::Normal);
        wd.trigger_grokking_run(10).await;
        rx.changed().await.unwrap();
        assert_eq!(*rx.borrow(), WatchdogMode::GrokkingRun);
    }
}
