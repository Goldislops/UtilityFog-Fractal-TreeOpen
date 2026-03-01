use std::net::SocketAddr;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use dashmap::DashMap;
use tonic::{transport::Server, Request, Response, Status};
use tracing::{info, warn};
use uuid::Uuid;

mod cluster_proto {
    tonic::include_proto!("utilityfog.cluster");
}

use cluster_proto::{
    cluster_service_server::{ClusterService, ClusterServiceServer},
    task_status::State as TaskState,
    Empty, GpuAffinityRequest, GpuAffinityResponse, HeartbeatPing, HeartbeatPong,
    NodeInfo, NodeList, PendingAssignment, RegistrationAck, TaskId, TaskReceipt,
    TaskRequest, TaskResult, TaskStatus,
};

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[derive(Debug, Clone)]
struct TaskEntry {
    id: String,
    task_type: String,
    payload: Vec<u8>,
    branch_id: String,
    priority: u32,
    assigned_node: String,
    assigned_gpu: String,
    state: i32,
    progress: f32,
    queued_at: u64,
    started_at: u64,
}

pub struct VanguardCluster {
    nodes: Arc<DashMap<String, NodeInfo>>,
    tasks: Arc<DashMap<String, TaskEntry>>,
    gpu_affinity: Arc<DashMap<String, i32>>,
}

impl VanguardCluster {
    fn new() -> Self {
        Self {
            nodes: Arc::new(DashMap::new()),
            tasks: Arc::new(DashMap::new()),
            gpu_affinity: Arc::new(DashMap::new()),
        }
    }

    fn pick_node(&self, gpu_pref: i32) -> Option<(String, String)> {
        let mut best_node = None;
        let mut best_gpu = None;
        let mut lowest_util: f32 = f32::MAX;

        for entry in self.nodes.iter() {
            let node = entry.value();
            for gpu in &node.gpus {
                if !gpu.available {
                    continue;
                }
                let is_5090 = gpu.model.contains("5090");
                let is_4090 = gpu.model.contains("4090");
                let ok = match gpu_pref {
                    1 => is_5090,
                    2 => is_4090,
                    _ => true,
                };
                if !ok {
                    continue;
                }
                let bias = match gpu_pref {
                    3 if is_5090 => -10.0,
                    4 if is_4090 => -10.0,
                    _ => 0.0,
                };
                let score = gpu.utilization + bias;
                if score < lowest_util {
                    lowest_util = score;
                    best_node = Some(node.node_id.clone());
                    best_gpu = Some(gpu.gpu_id.clone());
                }
            }
        }
        best_node.zip(best_gpu)
    }
}

#[tonic::async_trait]
impl ClusterService for VanguardCluster {
    async fn submit_task(
        &self,
        request: Request<TaskRequest>,
    ) -> Result<Response<TaskReceipt>, Status> {
        let req = request.into_inner();
        let task_id = Uuid::new_v4().to_string();

        let effective_pref = self
            .gpu_affinity
            .get(&req.task_type)
            .map(|v| *v)
            .unwrap_or(req.gpu_preference);

        let (node_id, gpu_id) = self
            .pick_node(effective_pref)
            .unwrap_or_else(|| ("pending".into(), "pending".into()));

        let ts = now_ms();
        let entry = TaskEntry {
            id: task_id.clone(),
            task_type: req.task_type,
            payload: req.payload,
            branch_id: req.branch_id,
            priority: req.priority,
            assigned_node: node_id.clone(),
            assigned_gpu: gpu_id.clone(),
            state: TaskState::Queued as i32,
            progress: 0.0,
            queued_at: ts,
            started_at: 0,
        };
        self.tasks.insert(task_id.clone(), entry);

        info!(task_id = %task_id, node = %node_id, gpu = %gpu_id, "task submitted");

        Ok(Response::new(TaskReceipt {
            task_id,
            assigned_node: node_id,
            assigned_gpu: gpu_id,
            queued_at_ms: ts,
        }))
    }

    async fn get_task_status(
        &self,
        request: Request<TaskId>,
    ) -> Result<Response<TaskStatus>, Status> {
        let id = request.into_inner().task_id;
        let entry = self
            .tasks
            .get(&id)
            .ok_or_else(|| Status::not_found(format!("task {id} not found")))?;
        let e = entry.value();
        Ok(Response::new(TaskStatus {
            task_id: e.id.clone(),
            state: e.state,
            progress: e.progress,
            node_id: e.assigned_node.clone(),
            gpu_id: e.assigned_gpu.clone(),
            started_at_ms: e.started_at,
            elapsed_ms: if e.started_at > 0 {
                now_ms().saturating_sub(e.started_at)
            } else {
                0
            },
        }))
    }

    type StreamResultsStream =
        tokio_stream::wrappers::ReceiverStream<Result<TaskResult, Status>>;

    async fn stream_results(
        &self,
        request: Request<TaskId>,
    ) -> Result<Response<Self::StreamResultsStream>, Status> {
        let id = request.into_inner().task_id;
        let (tx, rx) = tokio::sync::mpsc::channel(32);

        let tasks = self.tasks.clone();
        tokio::spawn(async move {
            loop {
                if let Some(entry) = tasks.get(&id) {
                    let e = entry.value();
                    let is_final = e.state == TaskState::Complete as i32
                        || e.state == TaskState::Failed as i32;
                    let _ = tx
                        .send(Ok(TaskResult {
                            task_id: id.clone(),
                            result_payload: vec![],
                            progress: e.progress,
                            is_final,
                        }))
                        .await;
                    if is_final {
                        break;
                    }
                }
                tokio::time::sleep(std::time::Duration::from_millis(500)).await;
            }
        });

        Ok(Response::new(tokio_stream::wrappers::ReceiverStream::new(rx)))
    }

    async fn register_node(
        &self,
        request: Request<NodeInfo>,
    ) -> Result<Response<RegistrationAck>, Status> {
        let node = request.into_inner();
        let node_id = node.node_id.clone();
        let gpu_count = node.gpus.len();
        self.nodes.insert(node_id.clone(), node);

        info!(node = %node_id, gpus = gpu_count, "node registered");

        Ok(Response::new(RegistrationAck {
            accepted: true,
            cluster_id: "vanguard-cluster-01".into(),
            message: format!("node {node_id} registered with {gpu_count} GPUs"),
        }))
    }

    async fn heartbeat(
        &self,
        request: Request<HeartbeatPing>,
    ) -> Result<Response<HeartbeatPong>, Status> {
        let ping = request.into_inner();

        if let Some(mut node) = self.nodes.get_mut(&ping.node_id) {
            node.gpus = ping.gpu_status;
        } else {
            warn!(node = %ping.node_id, "heartbeat from unknown node");
        }

        let mut pending = Vec::new();
        for entry in self.tasks.iter() {
            let e = entry.value();
            if e.assigned_node == ping.node_id && e.state == TaskState::Queued as i32 {
                pending.push(PendingAssignment {
                    task_id: e.id.clone(),
                    gpu_id: e.assigned_gpu.clone(),
                });
            }
        }

        Ok(Response::new(HeartbeatPong {
            acknowledged: true,
            server_time_ms: now_ms(),
            pending,
        }))
    }

    async fn list_nodes(
        &self,
        _request: Request<Empty>,
    ) -> Result<Response<NodeList>, Status> {
        let nodes: Vec<NodeInfo> = self.nodes.iter().map(|e| e.value().clone()).collect();
        Ok(Response::new(NodeList { nodes }))
    }

    async fn set_gpu_affinity(
        &self,
        request: Request<GpuAffinityRequest>,
    ) -> Result<Response<GpuAffinityResponse>, Status> {
        let req = request.into_inner();
        self.gpu_affinity
            .insert(req.task_type.clone(), req.preference);
        info!(task_type = %req.task_type, pref = req.preference, "gpu affinity set");
        Ok(Response::new(GpuAffinityResponse {
            applied: true,
            message: format!("affinity for '{}' set to {}", req.task_type, req.preference),
        }))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();

    let addr: SocketAddr = "0.0.0.0:50051".parse()?;
    let cluster = VanguardCluster::new();

    info!(addr = %addr, "Vanguard MCP Cluster server starting");

    Server::builder()
        .add_service(ClusterServiceServer::new(cluster))
        .serve(addr)
        .await?;

    Ok(())
}
