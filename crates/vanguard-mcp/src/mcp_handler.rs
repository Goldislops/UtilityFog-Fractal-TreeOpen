use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

#[derive(Debug, Serialize, Deserialize)]
pub struct McpRequest {
    pub jsonrpc: String,
    pub id: Option<Value>,
    pub method: String,
    #[serde(default)]
    pub params: Value,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct McpResponse {
    pub jsonrpc: String,
    pub id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<McpError>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct McpError {
    pub code: i32,
    pub message: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    pub input_schema: Value,
}

pub fn server_info() -> Value {
    serde_json::json!({
        "name": "vanguard-mcp",
        "version": "0.1.0",
        "capabilities": {
            "tools": {}
        }
    })
}

pub fn tool_definitions() -> Vec<ToolDefinition> {
    vec![
        ToolDefinition {
            name: "submit_fractal_task".into(),
            description: "Submit a fractal branch physics calculation to the GPU cluster".into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {
                    "branch_id": { "type": "string", "description": "Fractal branch identifier" },
                    "topology": { "type": "string", "enum": ["sierpinski", "menger", "octahedral"] },
                    "depth": { "type": "integer", "minimum": 0 },
                    "steps": { "type": "integer", "minimum": 1 },
                    "gpu_preference": { "type": "string", "enum": ["any", "5090_only", "4090_only", "prefer_5090", "prefer_4090"] }
                },
                "required": ["branch_id", "topology", "depth", "steps"]
            }),
        },
        ToolDefinition {
            name: "cluster_status".into(),
            description: "Get current status of all GPU cluster nodes".into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {},
                "required": []
            }),
        },
        ToolDefinition {
            name: "task_status".into(),
            description: "Get status of a submitted task by ID".into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {
                    "task_id": { "type": "string" }
                },
                "required": ["task_id"]
            }),
        },
        ToolDefinition {
            name: "set_gpu_affinity".into(),
            description: "Set GPU preference for a task type".into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {
                    "task_type": { "type": "string" },
                    "preference": { "type": "string", "enum": ["any", "5090_only", "4090_only", "prefer_5090", "prefer_4090"] }
                },
                "required": ["task_type", "preference"]
            }),
        },
        ToolDefinition {
            name: "watchdog_status".into(),
            description: "Get BOINC/Folding@home watchdog resource guard status".into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {},
                "required": []
            }),
        },
        ToolDefinition {
            name: "trigger_grokking_run".into(),
            description: "Trigger a Grokking Run that temporarily claims all GPU resources".into(),
            input_schema: serde_json::json!({
                "type": "object",
                "properties": {
                    "duration_secs": { "type": "integer", "minimum": 1, "description": "How long to hold exclusive resources" },
                    "confirm": { "type": "boolean", "description": "Must be true to execute" }
                },
                "required": ["duration_secs", "confirm"]
            }),
        },
    ]
}

pub fn handle_request(req: &McpRequest) -> McpResponse {
    match req.method.as_str() {
        "initialize" => McpResponse {
            jsonrpc: "2.0".into(),
            id: req.id.clone(),
            result: Some(server_info()),
            error: None,
        },
        "tools/list" => {
            let tools: Vec<Value> = tool_definitions()
                .into_iter()
                .map(|t| serde_json::to_value(t).unwrap())
                .collect();
            McpResponse {
                jsonrpc: "2.0".into(),
                id: req.id.clone(),
                result: Some(serde_json::json!({ "tools": tools })),
                error: None,
            }
        }
        "tools/call" => {
            let tool_name = req.params.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let args = req.params.get("arguments").cloned().unwrap_or(Value::Null);
            let result = dispatch_tool(tool_name, &args);
            McpResponse {
                jsonrpc: "2.0".into(),
                id: req.id.clone(),
                result: Some(result),
                error: None,
            }
        }
        _ => McpResponse {
            jsonrpc: "2.0".into(),
            id: req.id.clone(),
            result: None,
            error: Some(McpError {
                code: -32601,
                message: format!("method '{}' not found", req.method),
            }),
        },
    }
}

fn dispatch_tool(name: &str, args: &Value) -> Value {
    match name {
        "submit_fractal_task" => {
            let branch_id = args.get("branch_id").and_then(|v| v.as_str()).unwrap_or("unknown");
            let topology = args.get("topology").and_then(|v| v.as_str()).unwrap_or("sierpinski");
            let depth = args.get("depth").and_then(|v| v.as_u64()).unwrap_or(2);
            let steps = args.get("steps").and_then(|v| v.as_u64()).unwrap_or(10);
            serde_json::json!({
                "content": [{
                    "type": "text",
                    "text": format!("Task queued: branch={branch_id} topology={topology} depth={depth} steps={steps}")
                }]
            })
        }
        "cluster_status" => serde_json::json!({
            "content": [{
                "type": "text",
                "text": "Cluster: vanguard-cluster-01\nNodes: query via gRPC ListNodes"
            }]
        }),
        "task_status" => {
            let task_id = args.get("task_id").and_then(|v| v.as_str()).unwrap_or("unknown");
            serde_json::json!({
                "content": [{
                    "type": "text",
                    "text": format!("Status for task {task_id}: query via gRPC GetTaskStatus")
                }]
            })
        }
        "set_gpu_affinity" => serde_json::json!({
            "content": [{ "type": "text", "text": "GPU affinity updated" }]
        }),
        "watchdog_status" => serde_json::json!({
            "content": [{
                "type": "text",
                "text": "Watchdog: ACTIVE\nBOINC reserved: 15% GPU per card\nFolding@home reserved: 10% GPU per card\nGrokking mode: OFF"
            }]
        }),
        "trigger_grokking_run" => {
            let confirm = args.get("confirm").and_then(|v| v.as_bool()).unwrap_or(false);
            if !confirm {
                return serde_json::json!({
                    "content": [{ "type": "text", "text": "REJECTED: confirm must be true" }]
                });
            }
            let dur = args.get("duration_secs").and_then(|v| v.as_u64()).unwrap_or(60);
            serde_json::json!({
                "content": [{
                    "type": "text",
                    "text": format!("GROKKING RUN ACTIVATED for {dur}s — BOINC/F@H paused, all GPUs claimed")
                }]
            })
        }
        _ => serde_json::json!({
            "content": [{ "type": "text", "text": format!("unknown tool: {name}") }],
            "isError": true
        }),
    }
}
