# Performance Notes - UtilityFog 3D Visualization

## Key Performance Considerations

### 3D Rendering Optimizations
- **Instanced Rendering**: Uses THREE.InstancedMesh for node rendering to handle thousands of nodes efficiently
- **Frustum Culling**: Objects outside camera view are automatically culled
- **Level of Detail**: Consider implementing LOD for distant objects
- **Geometry Reuse**: Share geometries across instances to reduce memory footprint

### WebSocket Performance
- **Event Batching**: Batch multiple simulation updates into single render calls
- **Selective Updates**: Only update changed nodes/edges to minimize DOM manipulation
- **Queue Management**: Use event queue to prevent blocking the main thread

### Memory Management
- **Scene Cleanup**: Properly dispose of Three.js geometries and materials
- **Event Listener Cleanup**: Remove WebSocket listeners on component unmount
- **Texture Management**: Reuse textures and dispose of unused ones

### Browser Considerations
- **WebGL Context Limits**: Monitor WebGL context usage
- **Frame Rate**: Target 60fps for smooth interaction
- **Memory Leaks**: Monitor for growing memory usage during long sessions

## Monitoring Tools
- Use browser DevTools Performance tab
- Three.js Inspector extension
- React DevTools Profiler

---

# Bundle budget (CI gate)

## What is measured
`scripts/check-bundle-budget.mjs` inventories the JavaScript and CSS assets
of a **completed Vite production build** under `dist/assets`, and reports
per-kind and total sizes two ways:

- **raw bytes** — the on-disk asset size;
- **gzip bytes** — `node:zlib` `gzipSync` at the fixed configuration
  `{ level: 9 }` (a stable proxy for transfer size; not identical to any
  particular CDN's encoder).

Other extensions (`.map`, images, etc.) are ignored. The checker never
modifies build artifacts, and it **fails closed**: missing `dist`, missing
`dist/assets`, or a build with no JavaScript asset is a failure, not a pass.

## Baseline (measured, not assumed)
Measured on the build seat from the PR #316 build (`vite build`, 2026-07-11):

| Asset | Raw bytes | Gzip bytes |
|---|---|---|
| `index-*.js` (single chunk) | **979,384** | **272,585** |
| `index-*.css` | **912** | **483** |

(The earlier displayed "979.38 kB / 273.21 kB" build-log values are Vite's
decimal-rounded display, not exact bytes; the numbers above are exact.)

## Limits and headroom policy
**Policy: baseline + 25% headroom, rounded UP to the next 16 KiB (16,384 B)
boundary, with 16 KiB as a floor for tiny assets** (so content-hash noise
can never trip a near-zero budget).

| Budget | Limit (bytes) | Headroom vs baseline |
|---|---|---|
| `js_raw` | 1,228,800 (75 × 16 KiB) | ≈ +25.5% |
| `js_gzip` | 344,064 (21 × 16 KiB) | ≈ +26.2% |
| `css_raw` | 16,384 (floor) | large (baseline is 912 B) |
| `css_gzip` | 16,384 (floor) | large (baseline is 483 B) |

The intent is to catch **meaningful regression** (a new heavyweight
dependency, accidental duplication, an unminified artifact) while ignoring
ordinary Vite hash changes and small feature growth.

## What this is NOT
A bundle budget is a **size** gate, not a runtime-performance measurement.
It says nothing about frame rate, latency, memory, or WebSocket behavior.

## Local commands
From `utilityfog_frontend/frontend`:

```
npm run test:budget    # unit tests for the checker (node:test)
npm run build          # produce dist/
npm run check:budget   # evaluate dist/ against the budgets
```

## Interpreting a failure
The checker prints per-asset sizes, per-kind totals against limits, one
stable machine line (`BUNDLE_BUDGET v1 … status=PASS|FAIL`), and a
`bundle budget FAIL: <kind> <actual> bytes exceeds budget <limit> bytes`
line per exceeded budget. Exit codes: `1` = budget exceeded, `2` = missing
build output (fail closed).

First response to a failure is to find what grew (`ls -l dist/assets`,
compare the machine line against this file's baseline), not to raise the
limit.

## Update protocol
Budgets change **only with evidence**: a PR that (a) re-measures and records
the new baseline in this file, (b) names the change that legitimately moved
it (e.g. an approved dependency), and (c) re-derives the limits from the
stated policy. Casually raising limits to silence the gate defeats it.