"""GPU Accelerator for CA Engine using CuPy."""
import numpy as np
import os

try:
    cuda_path = os.path.join(os.environ.get("ProgramFiles", "C:/Program Files"), "NVIDIA GPU Computing Toolkit", "CUDA", "v13.2")
    if os.path.exists(cuda_path):
        os.environ.setdefault("CUDA_PATH", cuda_path)
        bin_path = os.path.join(cuda_path, "bin")
        if bin_path not in os.environ.get("PATH", ""):
            os.environ["PATH"] = os.environ.get("PATH", "") + ";" + bin_path
    # CUDA 13.2 has buggy fp8/fp6/fp4 headers that break CUB JIT compilation.
    # Disable CUB accelerators so CuPy uses its own reduction kernels instead.
    os.environ.setdefault("CUPY_ACCELERATORS", "")
    import cupy as cp
    GPU_AVAILABLE = True
    GPU_NAME = cp.cuda.runtime.getDeviceProperties(0)["name"].decode()
    GPU_VRAM = cp.cuda.runtime.getDeviceProperties(0)["totalGlobalMem"] / (1024**3)
    print(f"GPU Accelerator: {GPU_NAME} ({GPU_VRAM:.1f} GB) ONLINE")
except (ImportError, Exception) as e:
    GPU_AVAILABLE = False; cp = None
    print(f"GPU Accelerator: Unavailable ({e}). Using CPU.")

gpu = cp if GPU_AVAILABLE else np

def is_gpu_available(): return GPU_AVAILABLE
def to_gpu(a):
    if GPU_AVAILABLE and isinstance(a, np.ndarray): return cp.asarray(a)
    return a
def to_cpu(a):
    if GPU_AVAILABLE and hasattr(a, "get"): return a.get()
    return a
def sync():
    if GPU_AVAILABLE: cp.cuda.Stream.null.synchronize()

def count_neighbors_gpu(state):
    xp = gpu; s = to_gpu(state)
    counts = {}
    for sv in range(5):
        mask = (s == sv).astype(xp.int16)
        total = xp.zeros_like(mask)
        for dz in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0 and dz == 0: continue
                    shifted = xp.roll(xp.roll(xp.roll(mask, dx, 2), dy, 1), dz, 0)
                    total += shifted
        counts[sv] = total
    sync()
    return counts

def benchmark(size=128, iters=10):
    import time
    print(f"Benchmark {size}^3 ({size**3:,} voxels)")
    s = np.random.randint(0, 5, (size,size,size), dtype=np.uint8)
    t0 = time.time()
    for _ in range(iters):
        m = (s==2).astype(np.int16)
        for d in(-1,1): np.roll(m,d,0)+np.roll(m,d,1)+np.roll(m,d,2)
    tc = time.time()-t0; print(f"  CPU: {tc:.3f}s")
    if GPU_AVAILABLE:
        sc = cp.asarray(s)
        cp.roll(sc,1,0); cp.cuda.Stream.null.synchronize()
        t0 = time.time()
        for _ in range(iters):
            m = (sc==2).astype(cp.int16)
            for d in(-1,1): cp.roll(m,d,0)+cp.roll(m,d,1)+cp.roll(m,d,2)
            cp.cuda.Stream.null.synchronize()
        tg = time.time()-t0; print(f"  GPU: {tg:.3f}s  Speedup: {tc/tg:.1f}x")

if __name__ == "__main__":
    benchmark(64); benchmark(128)
