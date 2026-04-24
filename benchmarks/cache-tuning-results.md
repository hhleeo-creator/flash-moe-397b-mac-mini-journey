# Cache Tuning: The Default Is Optimal

Detailed investigation of Flash-MoE's `--cache-entries` parameter. **Conclusion upfront: Do not tune this. Default (2500) is the only stable configuration.**

## Why we investigated

After migrating from external TB5 SSD (5.41 tok/s) to internal NVMe (3.17 tok/s), we suspected the internal was slower on MoE random reads. Hypothesis: larger expert cache in RAM would compensate by reducing SSD reads.

Mac Mini M4 Pro has 64GB RAM, so in theory we could hold many more experts resident.

## The tests

### Test 1: Default config (baseline)

```bash
./infer --model /Users/migi/.flashmoe/model/Qwen3.5-397B-A17B-4bit \
  --prompt "Hello, my name is" --tokens 20
```

Result:
- **5.41 tok/s** (external SSD) / **3.17 tok/s** (internal)
- 0 pread errors
- Normal English output

### Test 2: --cache-entries 20000

```bash
./infer --model /Users/migi/.flashmoe/model/Qwen3.5-397B-A17B-4bit \
  --prompt "Hello, my name is" --tokens 20 \
  --cache-entries 20000 \
  --malloc-cache 5000
```

Result:
- **6.28 tok/s** (appears faster!)
- **1274 pread errors** (in logs)
- Output: completed but with errors
- Expert cache hit rate: 68%

Wait, faster with errors? The pread failures fall back to other experts silently. Output still produced but model behavior degraded.

### Test 3: --cache-entries 20000 + --predict

```bash
./infer --model /Users/migi/.flashmoe/model/Qwen3.5-397B-A17B-4bit \
  --prompt "Hello world" --tokens 20 \
  --cache-entries 20000 --predict
```

Result:
- **5.14 tok/s**
- Same pread error count (1274)
- Hit rate: 61%
- Output: normal English

### Test 4: Long Korean with --cache-entries 20000 + --predict

```bash
./infer --model /Users/migi/.flashmoe/model/Qwen3.5-397B-A17B-4bit \
  --prompt "한국 음식 3가지 추천해주세요" --tokens 200 \
  --cache-entries 20000 --predict
```

Result:
- **8.76 tok/s** (high!)
- Hit rate: **93.5%** (excellent)
- pread errors: Still hundreds
- **Output: Degenerate loop** — same token "æĸĩ" repeated 20+ times

The speed and hit rate looked amazing but output was garbage.

### Test 5: Via wrapper, --cache-entries 20000

```bash
# Start infer with large cache
./infer --serve 8000 --cache-entries 20000 --predict

# Query via wrapper
curl -X POST http://localhost:8771/v1/chat/completions \
  -d '{"messages":[{"role":"user","content":"Hello"}],"max_tokens":100}'
```

Result:
- **generated=0 tokens**
- Empty content response
- finish_reason: "stop"
- pread errors continue

Complete failure when routed through wrapper.

### Test 6: --cache-entries 5000 via wrapper

```bash
./infer --serve 8000 --cache-entries 5000
```

Result:
- **generated=0 tokens** (same failure)
- 47 pread errors per query
- Still broken

### Test 7: Back to default via wrapper

```bash
./infer --serve 8000  # no cache-entries override
```

Result:
- **Normal generation**
- 0 pread errors
- Korean quality excellent (detailed explanation of Korean foods)
- ~4-5 tok/s

## Data summary

| cache_entries | Direct tok/s | Via wrapper | pread errors | Output quality |
|---|---|---|---|---|
| 2500 (default) | 3.17-5.41 | ✓ works | **0** | Excellent |
| 5000 | — | ✗ generated=0 | 47 | Degraded |
| 20000 | 5.14-8.76 | ✗ generated=0 | 1274 | Degenerate |
| 20000 + predict | Similar | ✗ generated=0 | ~1274 | Degenerate |

## The paradox

Large cache looked faster but produced wrong results. Small cache was slower but correct.

Why?

**Hypothesis 1**: Flash-MoE's internal expert indexing breaks above certain cache size. Possibly off-by-one in buffer allocation or fd management.

**Hypothesis 2**: Larger caches cause contention in some internal structure (possibly the in-flight pread queue).

**Hypothesis 3**: `--predict` flag combined with large cache has race conditions in prefetch.

We did not dig into Flash-MoE source to find the exact bug. Time-constrained; "use default" was sufficient for our goals.

## What "fast" meant in failed configs

Remember: tok/s measures token **emission** rate, not correctness. A model outputting random garbage at 10 tok/s is faster than a model outputting correct text at 5 tok/s — and totally useless.

**Always verify output content, not just speed.**

## What we tried to debug

1. **File integrity check**: MD5 of all layer files — all match between internal and external. Data not corrupted.

2. **Extended attributes**: Found `com.apple.provenance` xattr on copied files. Tested with and without — no effect on pread errors.

3. **File descriptor limit**: Default macOS ulimit -n 256. Raised to 10240. **No effect on pread rate**. This wasn't the fd exhaustion issue we initially suspected.

4. **External vs internal SSD**: Same pread error count. Not SSD-specific.

5. **--predict on/off**: Error count identical. Not predict-specific.

6. **Different prompts**: Same error rate. Not input-specific.

## Final configuration

```bash
./infer --model PATH \
  --serve 8000 \
  2>&1 | tee log
```

- NO `--cache-entries` flag (let default apply)
- NO `--predict` flag
- `ulimit -n 10240` beneficial (doesn't hurt, may help in some corner cases)

This gives:
- ~3-5 tok/s generation
- 0 pread errors
- Correct output (English and Korean)
- Reliable via wrapper

## Lesson for Flash-MoE users

**Ignore the performance tuning flags.** They expose internal bugs. Use defaults.

If you need more speed on Mac Silicon + Flash-MoE + Qwen3.5-397B:
- Don't tune cache_entries
- Use fastest SSD you have
- Wait for MLX native implementation
- Or use a smaller model (70B models are 2-3x faster with better ecosystem)

## For Flash-MoE maintainers

If Dan Woods or contributors see this: the --cache-entries parameter exhibits deterministic failure at values above ~2500-5000 on Mac Mini M4 Pro + Qwen3.5-397B-A17B-4bit setup. Repro:

```
./infer --model <qwen3.5-397b-4bit> \
  --prompt "Hello" --tokens 20 \
  --cache-entries 20000

Result: ~1274 pread: -1/7077888 errors visible,
        output may degenerate or produce wrong tokens.
```

Expected: no errors or clear documentation of cache sizing limits.

Not filing an issue (yet) because it's possible this is specific to our setup. Reporting here as documentation.
