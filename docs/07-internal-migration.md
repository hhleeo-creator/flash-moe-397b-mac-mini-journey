# Phase 9.0-9.1: External → Internal SSD Migration + pread Debug Marathon

**Date**: 2026-04-24 (morning)
**Duration**: ~4 hours (1 hour migration + 3 hours debugging)
**Outcome**: Solved (default config is optimal)

## Why migrate

Phase 5-8 ran on external Acasis TB5 enclosure with WD SN850X. Fast (5.41 tok/s) but unreliable:

```
[2026-04-23 21:25:25] (Sandbox) System Policy: touch(30430) deny(1)
  file-write* /Volumes/FlashMoE/.keepalive
```

macOS Sandbox denied our keepalive script's touch attempts. Enclosure entered idle after 5 minutes, disconnected.

Overnight detach risk = daily service restart. Unacceptable for Telegram bot use.

Internal NVMe SSD: slower but sandbox-free and always present.

## Migration

### Step 1: Check internal space

```bash
df -h /
```

462GB total, ~350GB free. Plenty.

### Step 2: Copy with verification

```bash
mkdir -p ~/.flashmoe/{flash-moe,model}

# Copy flash-moe repo (5.2GB)
cp -R /Volumes/FlashMoE/flash-moe/. ~/.flashmoe/flash-moe/
# 1.4 seconds

# Copy metadata files
for f in config.json chat_template.jinja tokenizer.json ...; do
  cp /Volumes/FlashMoE/models/mlx-community-Qwen3.5-397B-A17B-4bit/$f \
     ~/.flashmoe/model/Qwen3.5-397B-A17B-4bit/
done

# Copy 202GB packed_experts
cp -R /Volumes/FlashMoE/models/.../packed_experts ~/.flashmoe/model/.../
# 5 minutes 7 seconds — 660 MB/s sustained
```

### Step 3: Update expert_index.json

Flash-MoE's expert_index.json has absolute paths. Update model_path:

```bash
/Users/migi/flashmoe_venv/bin/python <<PYEOF
import json
with open(EXPERT_INDEX, 'r') as f: data = json.load(f)
data['model_path'] = '/Users/migi/.flashmoe/model/Qwen3.5-397B-A17B-4bit'
with open(EXPERT_INDEX, 'w') as f: json.dump(data, f, indent=2)
PYEOF
```

### Step 4: Verify integrity

```bash
# File counts
ls ~/.flashmoe/model/Qwen3.5-397B-A17B-4bit/packed_experts/layer_*.bin | wc -l
# 60 ✓

# All same size
ls -la .../packed_experts/layer_*.bin | awk '{print $5}' | sort -u
# Single value: 3623878656 ✓

# MD5 cross-check (sample)
md5 /Users/migi/.flashmoe/.../layer_00.bin
md5 /Volumes/FlashMoE/.../layer_00.bin
# Both: a0cfe338487b2c398dc39a2e6356874a ✓
```

Migration success. 8 minutes total.

### Step 5: Test

```bash
cd ~/.flashmoe/flash-moe/metal_infer
./infer --model ~/.flashmoe/model/Qwen3.5-397B-A17B-4bit \
  --prompt "Hello" --tokens 20
```

Works. Output: "Hello, my name is Aryan..."

But speed: **3.17 tok/s**. Phase 7 on external was **5.41 tok/s**.

**Internal is 35% slower.** Confused.

## The debugging marathon

### Theory 1: Page cache cold

First run after migration. RAM hadn't loaded experts. Maybe warm-up needed.

Repeated same query 5 times:
- Run 1: 2.11 tok/s
- Run 2: 1.97 tok/s
- Run 3: 1.98 tok/s
- Run 4: 1.98 tok/s
- Run 5: 1.98 tok/s

No warm-up effect. Even slower than initial 3.17.

**Hypothesis rejected.**

### Theory 2: Internal SSD is slower on random reads

Apple's M4 Pro NVMe sequential read is ~7 GB/s. But MoE inference does random 4K reads across 60 layer files. Maybe Apple's storage isn't optimized for this pattern.

To test, tried `--cache-entries 20000`. If we hold more experts in RAM cache, SSD reads reduce, internal should match external.

### Theory 3: Cache tuning

```bash
./infer --model ~/.flashmoe/model/... \
  --prompt "Hello" --tokens 20 \
  --cache-entries 20000 --malloc-cache 5000
```

Result:
- **6.28 tok/s** (faster!)
- But logs showed:
```
  WARNING: expert 63 pread: -1/7077888
  WARNING: expert 417 pread: -1/7077888
  ... (1274 total)
```

53% of expert reads failing. But output was "complete".

### Theory 4: Wrapper retest

Maybe direct `./infer` handles errors gracefully but wrapper exposes them.

```bash
curl http://localhost:8771/v1/chat/completions -d '{...}'
```

Result: `generated=0 tokens`. Empty response. Bot broken.

**Large cache breaks wrapper completely.**

### Theory 5: ulimit

Hypothesis: 60 layer files × 2 fds (cold/warm tiered IO) = 120+ fds. macOS default ulimit -n is 256. Close to limit.

```bash
ulimit -n 10240  # 40x increase
./infer --cache-entries 20000 ...
```

Result: Still 1274 pread errors. **No effect.**

Not the fd limit.

### Theory 6: xattr

macOS adds `com.apple.provenance` to copied files. Maybe breaks mmap.

```bash
xattr -l ~/.flashmoe/model/.../layer_00.bin
# com.apple.provenance:
```

External also had same xattr (checked). **Not the difference.**

### Theory 7: File integrity

Maybe cp corrupted something.

```bash
md5 /Users/migi/.flashmoe/model/.../layer_00.bin
md5 /Volumes/FlashMoE/models/.../layer_00.bin
# a0cfe338487b2c398dc39a2e6356874a
# a0cfe338487b2c398dc39a2e6356874a
```

Identical. **Not corruption.**

### Theory 8: External also has errors

Ran same `--cache-entries 20000` on external SSD:

```bash
./infer --model /Volumes/FlashMoE/models/... \
  --cache-entries 20000
# 1274 pread errors (same count!)
```

**Not internal-specific.** The errors happen regardless of SSD. Cache size is the culprit.

### Eureka: Default config test

```bash
./infer --model ~/.flashmoe/model/... \
  --serve 8000
# no --cache-entries, default (2500)

curl http://localhost:8771/v1/chat/completions -d '{...}'
```

Result:
```json
{"choices":[{"message":{"content":"\n\nHello! How can I help you today?"}}]}
```

**Works!** 0 pread errors. Normal output.

## The resolution

The answer was embarrassingly simple: **don't tune the cache**.

```bash
./infer --serve 8000  # that's it
```

All our tuning attempts (20000, 5000, with predict, without predict) broke the generation pipeline.

Default cache_entries=2500 is the only configuration that:
1. Produces 0 pread errors
2. Works through the wrapper
3. Gives correct output

Speed: 3-5 tok/s (vs external 5.41). Accept the 35% loss for stability.

## What we learned

### About Flash-MoE
- Cache management has bugs above default values
- Errors are silent when running direct (outputs look ok)
- Errors cause generation=0 when routed through wrapper

### About Mac SSDs
- Internal NVMe is ~25% slower than SN850X external on MoE random reads
- Speed hypothesis was right, but cache tuning isn't the solution

### About debugging
- Don't change multiple variables at once (we did cache+predict together)
- Always verify output, not just speed
- Wrapper is stricter than direct call (good for catching issues)
- Default configs exist for a reason

### About time investment
- Migration: 8 minutes (efficient!)
- Debug marathon: 3 hours (inefficient, but educational)
- Could have been 30 minutes if we tried default first

## If reproducing this

Skip the cache tuning entirely:

```bash
# Internal SSD, default cache
./infer --model ~/.flashmoe/model/Qwen3.5-397B-A17B-4bit \
  --serve 8000 \
  2>&1 | tee infer.log
```

Expected: ~3-5 tok/s generation, 0 errors, stable operation.

If you want maximum speed:
- Use best SSD you have (external TB5 NVMe faster)
- Accept the detach risk (or solve keepalive properly)
- Don't tune cache

## Related files

- `benchmarks/cache-tuning-results.md` — Full test data
- `lessons/what-failed.md#1` — Summary of this failure mode
- `docs/06-wrapper.md` — Wrapper setup
- `code/scripts/start_all.sh` — Current operational config
