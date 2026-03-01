use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::sync::Arc;
use tokio::sync::{Mutex, Notify};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QueuedTask {
    pub task_id: String,
    pub priority: u32,
    pub branch_id: String,
    pub task_type: String,
    pub payload: Vec<u8>,
    pub gpu_preference: i32,
    pub queued_at_ms: u64,
}

impl PartialOrd for QueuedTask {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for QueuedTask {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.priority
            .cmp(&other.priority)
            .then_with(|| other.queued_at_ms.cmp(&self.queued_at_ms))
    }
}

pub struct DistributedTaskQueue {
    heap: Mutex<BinaryHeap<QueuedTask>>,
    notify: Notify,
    max_capacity: usize,
}

impl DistributedTaskQueue {
    pub fn new(max_capacity: usize) -> Arc<Self> {
        Arc::new(Self {
            heap: Mutex::new(BinaryHeap::new()),
            notify: Notify::new(),
            max_capacity,
        })
    }

    pub async fn enqueue(&self, task: QueuedTask) -> Result<(), String> {
        let mut heap = self.heap.lock().await;
        if heap.len() >= self.max_capacity {
            return Err(format!("queue full ({} tasks)", self.max_capacity));
        }
        heap.push(task);
        drop(heap);
        self.notify.notify_one();
        Ok(())
    }

    pub async fn dequeue(&self) -> QueuedTask {
        loop {
            {
                let mut heap = self.heap.lock().await;
                if let Some(task) = heap.pop() {
                    return task;
                }
            }
            self.notify.notified().await;
        }
    }

    pub async fn try_dequeue(&self) -> Option<QueuedTask> {
        let mut heap = self.heap.lock().await;
        heap.pop()
    }

    pub async fn len(&self) -> usize {
        self.heap.lock().await.len()
    }

    pub async fn drain_by_gpu_pref(&self, pref: i32) -> Vec<QueuedTask> {
        let mut heap = self.heap.lock().await;
        let mut matched = Vec::new();
        let mut remaining = BinaryHeap::new();
        while let Some(task) = heap.pop() {
            if task.gpu_preference == pref {
                matched.push(task);
            } else {
                remaining.push(task);
            }
        }
        *heap = remaining;
        matched
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_task(id: &str, priority: u32, ts: u64) -> QueuedTask {
        QueuedTask {
            task_id: id.into(),
            priority,
            branch_id: "b0".into(),
            task_type: "fractal_step".into(),
            payload: vec![],
            gpu_preference: 0,
            queued_at_ms: ts,
        }
    }

    #[tokio::test]
    async fn test_priority_ordering() {
        let q = DistributedTaskQueue::new(100);
        q.enqueue(make_task("low", 1, 100)).await.unwrap();
        q.enqueue(make_task("high", 10, 200)).await.unwrap();
        q.enqueue(make_task("mid", 5, 150)).await.unwrap();

        let first = q.dequeue().await;
        assert_eq!(first.task_id, "high");
        let second = q.dequeue().await;
        assert_eq!(second.task_id, "mid");
        let third = q.dequeue().await;
        assert_eq!(third.task_id, "low");
    }

    #[tokio::test]
    async fn test_capacity_limit() {
        let q = DistributedTaskQueue::new(2);
        q.enqueue(make_task("a", 1, 1)).await.unwrap();
        q.enqueue(make_task("b", 1, 2)).await.unwrap();
        let result = q.enqueue(make_task("c", 1, 3)).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_drain_by_gpu_pref() {
        let q = DistributedTaskQueue::new(100);
        let mut t1 = make_task("a", 1, 1);
        t1.gpu_preference = 1;
        let mut t2 = make_task("b", 1, 2);
        t2.gpu_preference = 2;
        let mut t3 = make_task("c", 1, 3);
        t3.gpu_preference = 1;
        q.enqueue(t1).await.unwrap();
        q.enqueue(t2).await.unwrap();
        q.enqueue(t3).await.unwrap();

        let matched = q.drain_by_gpu_pref(1).await;
        assert_eq!(matched.len(), 2);
        assert_eq!(q.len().await, 1);
    }
}
