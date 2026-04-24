# Phase 3: Model Download (224GB Over 2 Batches)

**Date**: 2026-04-23 (morning-afternoon)
**Duration**: ~4-5 hours wall time (mostly waiting)
**Outcome**: 46 shards of `mlx-community/Qwen3.5-397B-A17B-4bit` downloaded

## The target

[`mlx-community/Qwen3.5-397B-A17B-4bit`](https://huggingface.co/mlx-community/Qwen3.5-397B-A17B-4bit) on HuggingFace.

### Why this specific model

- **Qwen3.5**: Qwen is good at Korean (important for our use case)
- **397B parameters**: Large enough to be interesting, small enough to attempt
- **A17B**: Active parameters per token (what actually runs at inference)
- **4-bit**: Quantized, fits on consumer hardware (~208GB)
- **mlx-community**: Apple Silicon-compatible quantization
- **MoE**: Only active experts run → compatible with Flash-MoE streaming

### File breakdown

46 safetensors shards:
- Sizes roughly 4-5GB each
- Total: ~224GB (before conversion to Flash-MoE format)

Metadata:
- `config.json`
- `tokenizer.json`
- `chat_template.jinja`
- `added_tokens.json`
- `tokenizer_config.json`
- `special_tokens_map.json`
- `vocabulary.json`

## Download strategy

### Option considered

**A. Direct from HuggingFace (huggingface-cli)**
```bash
huggingface-cli download mlx-community/Qwen3.5-397B-A17B-4bit
```
- Reliable
- Built-in retries
- Single command
- BUT: slow from Korea (CDN routing, potential throttling)
- Estimated: 8+ hours, might fail partially

**B. hf-mirror.com (chosen)**
```bash
# Mirrors HuggingFace for Chinese/Korean latency
```
- Known Korea-friendly
- Much better download speeds
- Supports aria2c's parallel downloads

**C. Torrent (if available)**
- Not available for this model
- Not tried

Went with B.

### aria2c for parallel downloads

```bash
aria2c \
  -x 16 \                      # 16 connections per server
  -s 16 \                      # split file into 16 chunks
  -k 50M \                     # minimum chunk size 50MB
  -j 4 \                       # 4 parallel downloads
  -i urls.txt \                # URLs from file
  -d /Volumes/FlashMoE/models/mlx-community-Qwen3.5-397B-A17B-4bit/staging \
  --continue=true \            # resume support
  --file-allocation=none \     # faster start
  --summary-interval=10        # progress every 10s
```

**Parameters explained:**
- `-x 16`: Up to 16 TCP connections per server (HuggingFace allows many)
- `-s 16`: Split each file into 16 chunks, download in parallel
- `-k 50M`: Don't split below 50MB (avoids overhead)
- `-j 4`: Download 4 different files in parallel
- `--continue=true`: Resume broken downloads (important for 224GB)

### URL list preparation

Getting URLs:

```bash
# Method 1: If hf-mirror maintains Python interface
HF_ENDPOINT=https://hf-mirror.com python -c "
from huggingface_hub import snapshot_download, HfApi
api = HfApi()
files = api.list_repo_files('mlx-community/Qwen3.5-397B-A17B-4bit')
for f in files:
    print(f'https://hf-mirror.com/mlx-community/Qwen3.5-397B-A17B-4bit/resolve/main/{f}')
" > urls.txt
```

Or manually browse HuggingFace file listing, construct URLs. Had ~50 URLs total (46 shards + metadata files).

## The Actual Download (split into batches due to space)

### Space math

- External SSD: 447GB free
- Model + metadata: 224GB
- Staging area during download: ~224GB extra temporarily (aria2c chunks)
- Post-conversion packed_experts: 202GB

Max disk usage during pipeline:
- Downloading: 224GB (original) + ~20GB (chunks) = 244GB
- Converting: +5GB (extracted weights) = 249GB
- Post-packed: 224GB (original) + 202GB (packed) = **426GB**

Very tight on a 447GB SSD.

### Batch 1: Shards 00-23

```bash
# URL list for first half
head -24 urls.txt > batch1_urls.txt

aria2c -x 16 -s 16 -k 50M -j 4 \
  -i batch1_urls.txt \
  -d /Volumes/FlashMoE/models/mlx-community-Qwen3.5-397B-A17B-4bit/ \
  --continue=true 2>&1 | tee download_batch1.log
```

**Speed observed**: 40-60 MB/s sustained, peaking 80 MB/s

**Time**: ~2 hours for 110GB

**Notes**:
- Connection reliability: excellent (0 aria2c retries)
- CDN: distributed well across connections
- No throttling detected

### Pause point

After Batch 1: 110GB used, 337GB free.
If I ran Batch 2 immediately: would hit space issues.

Could:
- **A**. Start converting Batch 1 to free space (complex, error-prone)
- **B**. Continue download, accept temporary space overflow
- **C**. Move some Batch 1 files to internal SSD temporarily

Chose B. Extra 114GB fit (337GB free - 114GB = 223GB, still OK).

### Batch 2: Shards 24-46

```bash
tail -23 urls.txt > batch2_urls.txt

aria2c -x 16 -s 16 -k 50M -j 4 \
  -i batch2_urls.txt \
  -d /Volumes/FlashMoE/models/mlx-community-Qwen3.5-397B-A17B-4bit/ \
  --continue=true 2>&1 | tee download_batch2.log
```

**Time**: ~2.5 hours for 114GB
**Space**: Down to 223GB free

## Verification

After both batches:

```bash
# Count files
ls /Volumes/FlashMoE/models/mlx-community-Qwen3.5-397B-A17B-4bit/*.safetensors | wc -l
# → 46 (expected)

# Check total size
du -sh /Volumes/FlashMoE/models/mlx-community-Qwen3.5-397B-A17B-4bit/
# → ~224G

# Verify each file downloaded completely (no partial)
for f in /Volumes/FlashMoE/models/.../model-*.safetensors; do
    SIZE=$(stat -f %z "$f")
    if [ "$SIZE" -lt 1000000 ]; then
        echo "SUSPICIOUS: $f is only $SIZE bytes"
    fi
done
```

All 46 files present, sizes reasonable. No partial downloads.

### Checksum verification (optional)

HuggingFace provides SHA hashes in metadata:

```bash
# Read shard info from config
cat config.json | jq '.weights'

# Verify each shard
# (HuggingFace's huggingface-cli can do this)
```

We skipped rigorous verification since aria2c's resume+chunk verification caught obvious issues. Relied on conversion phase to catch any corruption.

## Metadata files

Separate from shards, smaller but essential:

```bash
aria2c -x 4 \
  "https://hf-mirror.com/mlx-community/Qwen3.5-397B-A17B-4bit/resolve/main/config.json" \
  "https://hf-mirror.com/mlx-community/Qwen3.5-397B-A17B-4bit/resolve/main/tokenizer.json" \
  "https://hf-mirror.com/mlx-community/Qwen3.5-397B-A17B-4bit/resolve/main/chat_template.jinja" \
  "https://hf-mirror.com/mlx-community/Qwen3.5-397B-A17B-4bit/resolve/main/special_tokens_map.json" \
  "https://hf-mirror.com/mlx-community/Qwen3.5-397B-A17B-4bit/resolve/main/tokenizer_config.json" \
  -d /Volumes/FlashMoE/models/mlx-community-Qwen3.5-397B-A17B-4bit/
```

All downloaded in <1 minute (all tiny).

## Total time

- Batch 1 download: ~2 hours
- Batch 2 download: ~2.5 hours
- Metadata + verification: 30 minutes
- **Total: 5 hours**

Half a day. But unattended — started download, went and did other work, came back to check.

## Troubleshooting notes

### Resume after interruption

If connection drops:

```bash
# aria2c saves .aria2 control files
# Simply re-run the same command
aria2c -x 16 ... -i batch1_urls.txt --continue=true

# Resumes from where it stopped
```

Tested this once (intentionally killed aria2 mid-download). Perfect resume.

### Slow speeds

If downloads are slow:

```bash
# Try different endpoint
# hf-mirror.com vs mirror.nju.edu.cn vs huggingface.co

# Try fewer connections (might be throttled)
aria2c -x 4 -s 4 ...

# Try time of day (off-peak Asia hours)
```

My speeds were consistent, didn't need to tune.

### Corrupted download

If a file is clearly wrong size:

```bash
# Remove and redownload
rm /Volumes/FlashMoE/.../model-XXX-of-046.safetensors
aria2c "https://hf-mirror.com/..." -d ...
```

aria2c handles this seamlessly.

## Files after Phase 3

```
/Volumes/FlashMoE/models/mlx-community-Qwen3.5-397B-A17B-4bit/
├── config.json
├── tokenizer.json
├── chat_template.jinja
├── special_tokens_map.json
├── tokenizer_config.json
├── added_tokens.json
├── model.safetensors.index.json
├── model-00001-of-00046.safetensors  (~5GB)
├── model-00002-of-00046.safetensors  (~5GB)
├── ... (46 total)
└── model-00046-of-00046.safetensors  (~5GB)

Total: ~224GB
```

## Disk space after Phase 3

```
/Volumes/FlashMoE:
  Used: 224GB
  Free: 223GB
  Total: 447GB
```

Still enough for Phase 6 conversion (will add ~208GB for packed_experts, then delete originals or keep as backup).

## Lessons

1. **Use regional mirrors.** hf-mirror saved ~40% download time vs direct.
2. **Batch downloads when space-constrained.** Let one batch finish before starting next.
3. **aria2c `--continue=true` is essential** for multi-GB downloads.
4. **Verify sizes, not just counts.** A 0-byte file with right name can slip past.
5. **Budget 5+ hours** for 200GB+ model downloads, even with fast internet.

## Next phase

[Phase 3 → docs/03-build.md](03-build.md) — Cloning Flash-MoE and building binaries.
