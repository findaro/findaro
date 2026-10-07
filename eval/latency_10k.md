# Search latency at 10k documents

- Date: 2026-10-07 20:22 UTC · arm64 Darwin
- 10000 docs (demo catalog replicated), ingest took 102s incl. embeddings
- 66 eval queries × 5, `Cache-Control: no-cache` (search cache bypassed; query embeddings cached after warm-up)

| concurrency | server p50 | server p95 | client p50 | client p95 | throughput |
|---:|---:|---:|---:|---:|---:|
| 1 (cold embedding) | 54.0 ms | 65.0 ms | 58.0 ms | 68.5 ms | 17 req/s |
| 1 | 6.3 ms | 9.3 ms | 9.4 ms | 12.8 ms | 99 req/s |
| 4 | 7.0 ms | 11.1 ms | 9.9 ms | 14.2 ms | 378 req/s |
| 8 | 8.9 ms | 15.3 ms | 13.1 ms | 22.4 ms | 551 req/s |
