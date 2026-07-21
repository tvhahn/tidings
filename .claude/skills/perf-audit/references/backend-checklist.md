# Backend checklist — category → per-stack instrument

Project-agnostic categories; the **overlay selects which instrument column applies** (this
repo: FastAPI + DynamoDB/SQLite). Numeric bars live in [`thresholds.md`](./thresholds.md).

**Weighting first:** before auditing anything here, check the overlay's measured
frontend/backend split. If the API is already fast (TTFB a small fraction of the felt
latency), record that once in the report and keep backend findings in the Later tier —
Souders' Golden Rule, verified locally rather than assumed.

## Latency method (stack-independent)

- Measure endpoints with ≥20 repeated requests (curl loop or middleware timing); report
  **p50/p95/p99 + max — never the mean**.
- Time the same endpoint cold and warm (cache layers, connection reuse) and say which you
  measured.
- `Server-Timing` response headers are the durable instrument for attributing backend phases
  from the browser trace — recommend as future instrumentation if absent, don't block on it.

## Categories

### 1. Profiling (find the hot path before naming a fix)

| | FastAPI / Python | Node |
|---|---|---|
| Sampling profile | `py-spy dump --pid` / `py-spy record -o profile.svg` (run via the project's runner, e.g. `uv run`) | `0x`, `node --cpu-prof`, `perf` + FlameGraph |
| Deterministic | `cProfile` around a handler | `--prof` |

Understand every frame >~1% of the profile; Amdahl-bound each candidate fix.

### 2. Event-loop / blocking I/O

| | FastAPI / Python | Node |
|---|---|---|
| Signal | `async def` route calling sync I/O (`boto3`, `requests`, file/DB drivers) directly — blocks the event loop for *all* requests | event-loop delay p99 >50 ms; `monitorEventLoopDelay` |
| Detect | grep `async def` handlers for sync clients not wrapped in `run_in_executor` / `asyncio.to_thread`; def-vs-async-def choice per route | flame graph wide app frames; `*Sync` core APIs on the request path |
| Fix | thread-offload the sync call, or make the route `def` (FastAPI runs it in the threadpool) | worker pool; async variants |

Note: an overlay preserve-list may say blocking I/O is already thread-offloaded — verify one
example rather than re-auditing all of it, and don't re-fix.

### 3. Query plans & indexing

| | SQLite (local/demo path) | DynamoDB | Postgres (generic column) |
|---|---|---|---|
| Instrument | `EXPLAIN QUERY PLAN` on the hot statements | no EXPLAIN — audit **access patterns**: Query (partition-scoped) vs Scan; GSI fit; item size | `EXPLAIN (ANALYZE, BUFFERS)` |
| Red flags | `SCAN table` where an index exists to serve the filter/sort; missing covering index on hot list queries | any `Scan` on a hot path; reads returning full items where a **projection** would do; unbounded `Query` pages | Seq Scan on big tables; estimate vs actual >10×; external-merge Disk sort |
| Fix | targeted index (mind column order) | partition-scoped Query, ProjectionExpression on list endpoints, page limits | index / covering index / keyset pagination |

### 4. N+1 and redundant reads

- Count storage calls per request (log or instrument the storage layer). Query count that
  scales with rows on screen = N+1.
- Same-key reads repeated *within one user action across endpoints* (fan-out of identical
  monthly queries) are the service-layer variant — fix with a short-TTL memo or a shared
  fetch, invalidated on mutation.

### 5. Parallelism

- Sequential `await`s of independent I/O → `asyncio.gather` (Python) / `Promise.all` (Node).
- Bound wide fan-outs with a `Semaphore` so parallelism doesn't become a thundering herd.

### 6. Transport & caching

- Compression on JSON responses (GZip/Brotli) — check `Content-Encoding`.
- `Cache-Control` policy: immutable for fingerprinted assets; `stale-while-revalidate` for
  tolerant aggregates; `ETag` for cheap 304s.
- Payload shape: pagination caps, field projections — the cheapest bytes are unsent ones.

### 7. Resilience (report-only unless the symptom is timeouts)

- Outbound calls without timeouts; retries without jitter/caps; unbounded request bodies.
- These are correctness/availability findings — tag `Info` unless they showed up in the trace.

## Output discipline

Every backend finding names: the endpoint, the measured distribution (or `potential impact`
if static-only), the storage calls it makes, and the single instrument that would verify the
fix. No EXPLAIN screenshots without the question they answer.
