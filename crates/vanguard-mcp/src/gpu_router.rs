use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Debug, Clone)]
pub struct GpuNode {
    pub node_id: String,
    pub hostname: String,
    pub ip: String,
    pub grpc_port: u16,
    pub gpus: Vec<GpuSlot>,
}

#[derive(Debug, Clone)]
pub struct GpuSlot {
    pub gpu_id: String,
    pub model: GpuModel,
    pub vram_mb: u64,
    pub utilization: f32,
    pub temperature_c: f32,
    pub power_watts: f32,
    pub active_tasks: u32,
    pub available: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GpuModel {
    Rtx5090,
    Rtx4090,
    Unknown,
}

impl GpuModel {
    pub fn from_str(s: &str) -> Self {
        if s.contains("5090") {
            GpuModel::Rtx5090
        } else if s.contains("4090") {
            GpuModel::Rtx4090
        } else {
            GpuModel::Unknown
        }
    }

    pub fn compute_weight(&self) -> f64 {
        match self {
            GpuModel::Rtx5090 => 2.5,
            GpuModel::Rtx4090 => 1.5,
            GpuModel::Unknown => 1.0,
        }
    }

    pub fn vram_budget_mb(&self) -> u64 {
        match self {
            GpuModel::Rtx5090 => 32768,
            GpuModel::Rtx4090 => 24576,
            GpuModel::Unknown => 8192,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RoutingStrategy {
    LeastLoaded,
    RoundRobin,
    AffinityFirst,
    VramCapacity,
}

pub struct GpuRouter {
    nodes: Arc<RwLock<HashMap<String, GpuNode>>>,
    round_robin_counter: Arc<tokio::sync::Mutex<usize>>,
    boinc_reserve_pct: f32,
    folding_reserve_pct: f32,
    grokking_active: Arc<tokio::sync::Mutex<bool>>,
}

#[derive(Debug, Clone)]
pub struct RouteDecision {
    pub node_id: String,
    pub gpu_id: String,
    pub model: GpuModel,
    pub estimated_util: f32,
}

impl GpuRouter {
    pub fn new(boinc_reserve_pct: f32, folding_reserve_pct: f32) -> Self {
        Self {
            nodes: Arc::new(RwLock::new(HashMap::new())),
            round_robin_counter: Arc::new(tokio::sync::Mutex::new(0)),
            boinc_reserve_pct,
            folding_reserve_pct,
            grokking_active: Arc::new(tokio::sync::Mutex::new(false)),
        }
    }

    pub async fn register_node(&self, node: GpuNode) {
        let mut nodes = self.nodes.write().await;
        nodes.insert(node.node_id.clone(), node);
    }

    pub async fn update_gpu_status(&self, node_id: &str, gpu_id: &str, util: f32, temp: f32, power: f32) {
        let mut nodes = self.nodes.write().await;
        if let Some(node) = nodes.get_mut(node_id) {
            for gpu in &mut node.gpus {
                if gpu.gpu_id == gpu_id {
                    gpu.utilization = util;
                    gpu.temperature_c = temp;
                    gpu.power_watts = power;
                }
            }
        }
    }

    pub async fn effective_capacity(&self, gpu: &GpuSlot) -> f32 {
        let grokking = *self.grokking_active.lock().await;
        if grokking {
            return 100.0 - gpu.utilization;
        }
        let reserved = self.boinc_reserve_pct + self.folding_reserve_pct;
        let ceiling = 100.0 - reserved;
        (ceiling - gpu.utilization).max(0.0)
    }

    pub async fn route(
        &self,
        strategy: RoutingStrategy,
        preferred_model: Option<GpuModel>,
        min_vram_mb: u64,
    ) -> Option<RouteDecision> {
        let nodes = self.nodes.read().await;
        let mut candidates: Vec<(&GpuNode, &GpuSlot)> = Vec::new();

        for node in nodes.values() {
            for gpu in &node.gpus {
                if !gpu.available {
                    continue;
                }
                if gpu.vram_mb < min_vram_mb {
                    continue;
                }
                if gpu.temperature_c > 85.0 {
                    continue;
                }
                candidates.push((node, gpu));
            }
        }

        if candidates.is_empty() {
            return None;
        }

        if let Some(pref) = preferred_model {
            let pref_candidates: Vec<_> = candidates.iter().filter(|(_, g)| g.model == pref).cloned().collect();
            if !pref_candidates.is_empty() {
                return self.select_from(&pref_candidates, strategy).await;
            }
        }

        self.select_from(&candidates, strategy).await
    }

    async fn select_from(
        &self,
        candidates: &[(&GpuNode, &GpuSlot)],
        strategy: RoutingStrategy,
    ) -> Option<RouteDecision> {
        match strategy {
            RoutingStrategy::LeastLoaded => {
                let best = candidates
                    .iter()
                    .min_by(|a, b| a.1.utilization.partial_cmp(&b.1.utilization).unwrap())?;
                Some(RouteDecision {
                    node_id: best.0.node_id.clone(),
                    gpu_id: best.1.gpu_id.clone(),
                    model: best.1.model,
                    estimated_util: best.1.utilization,
                })
            }
            RoutingStrategy::RoundRobin => {
                let mut counter = self.round_robin_counter.lock().await;
                let idx = *counter % candidates.len();
                *counter = counter.wrapping_add(1);
                let pick = &candidates[idx];
                Some(RouteDecision {
                    node_id: pick.0.node_id.clone(),
                    gpu_id: pick.1.gpu_id.clone(),
                    model: pick.1.model,
                    estimated_util: pick.1.utilization,
                })
            }
            RoutingStrategy::AffinityFirst | RoutingStrategy::VramCapacity => {
                let best = candidates
                    .iter()
                    .max_by_key(|(_, g)| g.vram_mb)?;
                Some(RouteDecision {
                    node_id: best.0.node_id.clone(),
                    gpu_id: best.1.gpu_id.clone(),
                    model: best.1.model,
                    estimated_util: best.1.utilization,
                })
            }
        }
    }

    pub async fn set_grokking(&self, active: bool) {
        let mut g = self.grokking_active.lock().await;
        *g = active;
    }

    pub async fn is_grokking(&self) -> bool {
        *self.grokking_active.lock().await
    }

    pub async fn node_count(&self) -> usize {
        self.nodes.read().await.len()
    }

    pub async fn total_gpus(&self) -> usize {
        self.nodes.read().await.values().map(|n| n.gpus.len()).sum()
    }

    pub async fn cluster_summary(&self) -> ClusterSummary {
        let nodes = self.nodes.read().await;
        let mut total_5090 = 0u32;
        let mut total_4090 = 0u32;
        let mut total_vram_mb = 0u64;
        let mut avg_util = 0.0f32;
        let mut gpu_count = 0u32;

        for node in nodes.values() {
            for gpu in &node.gpus {
                match gpu.model {
                    GpuModel::Rtx5090 => total_5090 += 1,
                    GpuModel::Rtx4090 => total_4090 += 1,
                    _ => {}
                }
                total_vram_mb += gpu.vram_mb;
                avg_util += gpu.utilization;
                gpu_count += 1;
            }
        }
        if gpu_count > 0 {
            avg_util /= gpu_count as f32;
        }

        ClusterSummary {
            node_count: nodes.len() as u32,
            rtx5090_count: total_5090,
            rtx4090_count: total_4090,
            total_vram_mb,
            avg_utilization: avg_util,
            grokking_active: *self.grokking_active.lock().await,
            boinc_reserve_pct: self.boinc_reserve_pct,
            folding_reserve_pct: self.folding_reserve_pct,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ClusterSummary {
    pub node_count: u32,
    pub rtx5090_count: u32,
    pub rtx4090_count: u32,
    pub total_vram_mb: u64,
    pub avg_utilization: f32,
    pub grokking_active: bool,
    pub boinc_reserve_pct: f32,
    pub folding_reserve_pct: f32,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_cluster() -> (GpuRouter, GpuNode, GpuNode) {
        let router = GpuRouter::new(15.0, 10.0);
        let node_285k = GpuNode {
            node_id: "intel-285k".into(),
            hostname: "vanguard-primary".into(),
            ip: "192.168.1.100".into(),
            grpc_port: 50051,
            gpus: vec![
                GpuSlot {
                    gpu_id: "gpu-0".into(),
                    model: GpuModel::Rtx5090,
                    vram_mb: 32768,
                    utilization: 20.0,
                    temperature_c: 55.0,
                    power_watts: 200.0,
                    active_tasks: 1,
                    available: true,
                },
                GpuSlot {
                    gpu_id: "gpu-1".into(),
                    model: GpuModel::Rtx5090,
                    vram_mb: 32768,
                    utilization: 40.0,
                    temperature_c: 60.0,
                    power_watts: 250.0,
                    active_tasks: 2,
                    available: true,
                },
                GpuSlot {
                    gpu_id: "gpu-2".into(),
                    model: GpuModel::Rtx5090,
                    vram_mb: 32768,
                    utilization: 10.0,
                    temperature_c: 50.0,
                    power_watts: 150.0,
                    active_tasks: 0,
                    available: true,
                },
            ],
        };
        let node_9950x3d = GpuNode {
            node_id: "amd-9950x3d".into(),
            hostname: "compute-secondary".into(),
            ip: "192.168.1.101".into(),
            grpc_port: 50052,
            gpus: vec![
                GpuSlot {
                    gpu_id: "gpu-0".into(),
                    model: GpuModel::Rtx4090,
                    vram_mb: 24576,
                    utilization: 30.0,
                    temperature_c: 58.0,
                    power_watts: 280.0,
                    active_tasks: 1,
                    available: true,
                },
                GpuSlot {
                    gpu_id: "gpu-1".into(),
                    model: GpuModel::Rtx4090,
                    vram_mb: 24576,
                    utilization: 50.0,
                    temperature_c: 65.0,
                    power_watts: 300.0,
                    active_tasks: 2,
                    available: true,
                },
            ],
        };
        (router, node_285k, node_9950x3d)
    }

    #[tokio::test]
    async fn test_route_least_loaded() {
        let (router, n1, n2) = make_cluster();
        router.register_node(n1).await;
        router.register_node(n2).await;

        let decision = router.route(RoutingStrategy::LeastLoaded, None, 0).await.unwrap();
        assert_eq!(decision.node_id, "intel-285k");
        assert_eq!(decision.gpu_id, "gpu-2");
        assert_eq!(decision.estimated_util, 10.0);
    }

    #[tokio::test]
    async fn test_route_prefer_5090() {
        let (router, n1, n2) = make_cluster();
        router.register_node(n1).await;
        router.register_node(n2).await;

        let decision = router.route(RoutingStrategy::LeastLoaded, Some(GpuModel::Rtx5090), 0).await.unwrap();
        assert_eq!(decision.model, GpuModel::Rtx5090);
    }

    #[tokio::test]
    async fn test_route_prefer_4090() {
        let (router, n1, n2) = make_cluster();
        router.register_node(n1).await;
        router.register_node(n2).await;

        let decision = router.route(RoutingStrategy::LeastLoaded, Some(GpuModel::Rtx4090), 0).await.unwrap();
        assert_eq!(decision.model, GpuModel::Rtx4090);
        assert_eq!(decision.node_id, "amd-9950x3d");
    }

    #[tokio::test]
    async fn test_vram_filter() {
        let (router, n1, n2) = make_cluster();
        router.register_node(n1).await;
        router.register_node(n2).await;

        let decision = router.route(RoutingStrategy::LeastLoaded, None, 30000).await.unwrap();
        assert_eq!(decision.model, GpuModel::Rtx5090);
    }

    #[tokio::test]
    async fn test_cluster_summary() {
        let (router, n1, n2) = make_cluster();
        router.register_node(n1).await;
        router.register_node(n2).await;

        let summary = router.cluster_summary().await;
        assert_eq!(summary.node_count, 2);
        assert_eq!(summary.rtx5090_count, 3);
        assert_eq!(summary.rtx4090_count, 2);
        assert_eq!(summary.total_vram_mb, 3 * 32768 + 2 * 24576);
    }

    #[tokio::test]
    async fn test_grokking_toggle() {
        let (router, _, _) = make_cluster();
        assert!(!router.is_grokking().await);
        router.set_grokking(true).await;
        assert!(router.is_grokking().await);
        router.set_grokking(false).await;
        assert!(!router.is_grokking().await);
    }
}
