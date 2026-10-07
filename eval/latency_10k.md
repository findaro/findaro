# Search latency at 10k documents

- Date: 2026-10-07 21:38 UTC · arm64 Darwin
- 10000 docs (demo catalog replicated), ingest took 96s incl. embeddings
- 66 eval queries × 5, `Cache-Control: no-cache` (search cache bypassed; query embeddings cached after warm-up)

| concurrency | server p50 | server p95 | client p50 | client p95 | throughput |
|---:|---:|---:|---:|---:|---:|
| 1 (cold embedding) | 55.1 ms | 65.7 ms | 59.2 ms | 69.2 ms | 14 req/s |
| 1 | 8.7 ms | 12.9 ms | 11.3 ms | 15.7 ms | 82 req/s |
| 4 | 10.2 ms | 16.1 ms | 12.8 ms | 19.5 ms | 285 req/s |
| 8 | 12.5 ms | 21.9 ms | 15.9 ms | 26.4 ms | 452 req/s |
