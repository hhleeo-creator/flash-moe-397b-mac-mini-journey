# Performance Benchmarks

All measurements on Mac Mini M4 Pro (64GB), macOS 15, Flash-MoE (commit from 2026-04).

## Generation Speed

### Direct `./infer` Call (raw prompt, no template)

| Configuration | Tokens/sec | TTFT | Notes |
|---|---|---|---|
| External TB5 SN850X, default cache | **5.41** | 2.19s | Phase 7 baseline |
| Internal NVMe, default cache | **3.17** | 5.17s | After migration, cold |
| Internal NVMe, default cache, warm | **3.46** | 1.02s | 2nd run, page cache hot |
| Internal, cache 20000 + predict (short prompt) | 5.14 | 0.98s | 1274 pread errors in background |
| Internal, cache 20000 + predict (Korean long) | 8.76 | 6.17s | ⚠️ But degenerate output — `æĸĩ` repetition |

### Via OpenAI-Compatible Wrapper (port 8771)

| Query | Input Size | Output Size | Total Time | Effective tok/s |
|---|---|---|---|---|
| "Hello, how are you?" | ~15 tokens | ~30 chars | 9.87s | ~3 tok/s |
| 한국어 300자 | ~20 tokens | ~300 Korean chars | 68.71s | ~4.4 tok/s |
| 한의원 블로그 (500 tokens) | ~50 tokens | ~500 Korean chars | ~120s | ~4.2 tok/s |

### Via Telegram Bot (web_agent + tool loop)

| Query Type | Iterations | Total Time | Breakdown |
|---|---|---|---|
| "안녕하세요" (greeting) | 1 | ~3 min | No tool, simple response |
| "대한민국 수도는?" (factual) | 1 | ~5 min | No tool, direct answer |
| "오늘 서울 날씨" (requires search) | 2 | ~10 min | web_search + interpretation |
| "Top 3 watch recommendations" | 2 | ~11 min | web_search + structured answer |
| Long structured request | 2-3 | 15-25 min | Often hits max_tokens limit |

### Via Custom Agent CLI

| Test | Iterations | Total Time |
|---|---|---|
| "Capital of Korea" | 1 (no tool) | 3m 32s |
| "Current president of Korea" (searched) | 2 | 11m 4s |
| "Clinics in Munjeong-dong" (searched) | 2 | 30m (max 4 iter, max_tokens 700) |

## Per-Layer Timing (60 layers, K=4)

```
avg of 420 layers (ms):
  deferred_wait:   0.000
  deferred_cpu:    0.001
  input_norm:      0.000
  cmd1_submit:     0.017
  cmd1_wait:       1.116  ← expert gate compute wait
  spec_route:      0.000
  cpu_attn:        0.011
  cmd2_encode:     0.017
  cmd2_wait:       0.427
  routing_cpu:     0.002
  expert_io:       2.012  ← SSD random read (bottleneck)
  cmd3_encode:     0.028
  total_layer:     3.632
```

**Bottleneck: expert_io (2 ms/layer)** = SSD random reads. This is why MoE streaming is SSD-bound.

## Cache Hit Rates

| Test | Cache Entries | Hits | Misses | Hit Rate |
|---|---|---|---|---|
| Short English (20 tok) | default | — | — | — |
| Short English + cache 20K | 20000 | 3073 | 1967 | 61.0% |
| Short English + malloc 5K | 5000 | 3917 | 1843 | 68.0% |
| Long Korean (200 tok) | 20000 | 49161 | 3399 | **93.5%** |

Longer generation = higher cache hit rate (same experts reused repeatedly).

## Memory Usage

| Component | RAM |
|---|---|
| infer base (weights mmap) | ~11 GB |
| Expert LRU cache (default 2500) | ~17 GB |
| wrapper (Python) | ~200 MB |
| Telegram bot (Python) | ~150 MB |
| **Total Flash-MoE stack** | **~30 GB** |
| OS + other services | ~10 GB |
| **Headroom on 64GB Mac** | **~24 GB** |

## Storage

| Directory | Size | Purpose |
|---|---|---|
| `model_weights.bin` | 5.52 GB | Base weights (attn, embed, norm) |
| `packed_experts/*.bin` | 202.5 GB | 60 layer files, 512 experts each |
| Original 46 shards (backup) | 209 GB | Source safetensors |
| `flash-moe/` repo | ~50 MB | Source code |
| wrapper + agent code | ~1 MB | Our code |
| **Total working set** | **~208 GB** | Internal NVMe |
| **Total with backup** | **~417 GB** | External SSD |

## Key Finding: cache_entries Must Stay at Default

| cache_entries | pread Errors per 10 tokens | Generation via wrapper |
|---|---|---|
| 2500 (default) | **0** | ✓ Works |
| 5000 | 47 | ✗ generated=0 |
| 20000 | 1274 | ✗ generated=0 |

**Lesson**: Flash-MoE's internal cache management breaks above default. No tuning needed.

## Key Finding: Internal vs External SSD

Same model, same code, same day:

| Metric | External TB5 SN850X | Internal M4 Pro NVMe |
|---|---|---|
| tok/s (raw) | 5.41 | 3.17 |
| expert_io (ms) | 1.606 | 2.012 |
| cmd1_wait (ms) | 0.856 | 1.116 |
| Stability | ❌ Detaches | ✓ Solid |

Internal SSD is ~25% slower on MoE random reads, despite higher sequential throughput. Hypothesis: Apple's NVMe optimized for bursty OS workloads, not sustained random access.

**Accept the tradeoff**: -35% speed, +100% stability.
