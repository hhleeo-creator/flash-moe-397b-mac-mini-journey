# Phase 3-4: Flash-MoE Build + Script Analysis

**Date**: 2026-04-23 (morning)
**Duration**: ~3 hours (30 min build + 2.5 hours scripts/gap-fill)
**Outcome**: Flash-MoE binaries compiled, tokenizer conversion plan ready

## Phase 3: Cloning and Building Flash-MoE

### Repository

```bash
cd /Volumes/FlashMoE/
git clone https://github.com/danveloper/flash-moe.git
cd flash-moe
```

### Structure overview

```
flash-moe/
├── metal_infer/         # Main C/Metal inference code
│   ├── Makefile
│   ├── infer.c          # Main entry
│   ├── metal/           # Metal compute shaders
│   └── ...
├── scripts/             # Python conversion tools
│   ├── extract_weights.py
│   ├── repack_experts.py
│   └── ...
└── docs/                # Flash-MoE's own documentation
```

No Python runtime dependency for inference (`metal_infer/`). Python only for one-time model conversion.

### Prerequisites check

```bash
# Xcode Command Line Tools (required for Metal)
xcode-select --install
# If already installed: "command line tools are already installed"

# Clang
clang --version
# Apple clang version 16.0+

# Metal support
xcrun metal --version
# metal-3.x
```

macOS 15 on Apple Silicon has all needed. No extra installs.

### Build

```bash
cd metal_infer
make
```

Build output:
```
clang -c -O3 -Wall ... infer.c -o build/infer.o
clang -c -O3 -Wall ... expert_io.c -o build/expert_io.o
xcrun metal -c metal/moe_kernel.metal -o metal/moe_kernel.air
xcrun metallib metal/moe_kernel.air -o metal/moe_kernel.metallib
clang ... build/*.o -o infer -framework Metal -framework Foundation
```

**Time**: ~2 minutes on M4 Pro.

**Output**:
- `infer` — main binary, ~500KB
- `metal/moe_kernel.metallib` — Metal shader library

### First test (before having model)

```bash
./infer --help
```

Help output confirms:
- `--serve PORT` for HTTP server
- `--cache-entries N` for LRU cache size
- `--predict` for expert prefetching
- `--timing` for per-layer breakdown
- etc.

Matches docs. Build succeeded.

## Phase 4: Script Analysis

Now to understand the conversion pipeline.

### Flash-MoE's scripts

```bash
ls scripts/
# extract_weights.py
# repack_experts.py
# vocab_tools.py
# ...
```

### extract_weights.py

**Purpose**: Separate non-expert weights from expert weights.

Non-expert weights (in `model_weights.bin`):
- Attention Q/K/V/O projections
- Layer norms
- Embedding table
- LM head

Expert weights (repacked separately):
- Per-layer MoE gate projections
- Per-layer MoE up projections
- Per-layer MoE down projections

This split is because:
- Non-expert weights always loaded in RAM
- Expert weights streamed from SSD per-token

### repack_experts.py

**Purpose**: Reorganize expert weights into per-layer files optimized for random access.

Input: 46 safetensors shards with interleaved expert weights
Output: 60 `.bin` files (one per layer), each with all 512 experts

Each layer file:
```
Layer 0 file structure:
├── Expert 0 (gate + up + down projections)
├── Expert 1 (gate + up + down projections)
├── ...
└── Expert 511 (gate + up + down projections)

Total per expert: ~7 MB
Total per layer: 7 MB × 512 = ~3.6 GB
Total 60 layers: 60 × 3.6 GB = 216 GB (our measured 202 GB close)
```

**Why this layout**:
- mmap the whole file
- Random seek within file is fast
- Each expert at predictable offset
- No header lookups at inference time

### Key insight: Layout matters

Flash-MoE's runtime reads experts by file offset:
```c
// Simplified pseudocode
expert_offset = expert_size × expert_id;
pread(layer_fd, buffer, expert_size, expert_offset);
```

So repack must produce exactly this layout. Not a "convert format" script — it's "lay out bytes at specific positions."

## Phase 4.5: The Tokenizer Gap

### What Flash-MoE provides

`vocab_tools.py` handles many tokenizer formats. But not Qwen3.5's specific needs.

### What Qwen3.5 requires

Qwen uses byte-level BPE (like GPT-2/OpenAI). Flash-MoE's default vocab loader expected:
- Token ID → bytes mapping
- Specific binary format

Qwen's `tokenizer.json` had:
- Token ID → Unicode-mapped bytes (GPT-2 style)
- Needs unmapping before being useful

### Writing a custom converter

```python
# scripts/vocab_to_bin.py (our custom addition)

import json
import struct

def bytes_to_unicode():
    """GPT-2 style byte→unicode mapping."""
    # Returns dict mapping 0-255 bytes to special Unicode chars
    bs = list(range(ord("!"), ord("~") + 1)) + \
         list(range(ord("¡"), ord("¬") + 1)) + \
         list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, (chr(c) for c in cs)))

def unicode_to_bytes():
    return {v: k for k, v in bytes_to_unicode().items()}

def convert_qwen_tokenizer(tokenizer_json_path, output_bin_path):
    """Convert Qwen's tokenizer.json to Flash-MoE vocab.bin."""
    with open(tokenizer_json_path) as f:
        data = json.load(f)

    vocab = data['model']['vocab']  # dict: token_str → token_id
    added = data.get('added_tokens', [])

    # Sort by token_id
    all_tokens = [(tid, tstr) for tstr, tid in vocab.items()]
    all_tokens.extend([(t['id'], t['content']) for t in added])
    all_tokens.sort()

    u2b = unicode_to_bytes()

    with open(output_bin_path, 'wb') as f:
        for token_id, token_str in all_tokens:
            # Convert unicode-mapped token to raw bytes
            try:
                raw_bytes = bytes(u2b[c] for c in token_str)
            except KeyError:
                # Added tokens like <|im_start|> use UTF-8 directly
                raw_bytes = token_str.encode('utf-8')

            # Pack: uint32 LE token_id + uint16 LE length + bytes
            f.write(struct.pack('<IH', token_id, len(raw_bytes)))
            f.write(raw_bytes)
```

Run:
```bash
python scripts/vocab_to_bin.py \
  /Volumes/FlashMoE/models/mlx-community-Qwen3.5-397B-A17B-4bit/tokenizer.json \
  /Volumes/FlashMoE/models/mlx-community-Qwen3.5-397B-A17B-4bit/vocab.bin
```

**Output**: `vocab.bin` (7.8 MB, 248,077 tokens)

### Verification

Decoded some tokens back to verify:

```python
# Test: token ID 9419 should be "Hello"
with open('vocab.bin', 'rb') as f:
    while True:
        header = f.read(6)
        if not header:
            break
        token_id, length = struct.unpack('<IH', header)
        token_bytes = f.read(length)
        if token_id == 9419:
            print(f"Token {token_id}: {token_bytes!r}")  # b' Hello'
            break
```

Output:
```
Token 9419: b' Hello'  # correct!
Token 35975: b' 안녕'   # Korean also correct
```

Working.

## Why this gap existed

Flash-MoE is a general MoE runtime. It was tested with certain model formats but not every tokenizer in the wild. Qwen3.5-specific vocab.bin generation wasn't in the default scripts.

This is the nature of early-stage ML infrastructure — supports 80% of cases, requires DIY for remaining 20%.

## Alternative paths considered

**Option 1: Modify Flash-MoE to read tokenizer.json directly**
- Would require C JSON parser
- Runtime tokenizer slower
- Not worth the complexity

**Option 2: Use HuggingFace tokenizers Rust crate**
- Adds large dependency
- Overkill for our needs
- Not needed

**Option 3: Write Python converter (chosen)**
- One-time cost
- Simple Python
- Output matches Flash-MoE's binary format
- Done in ~1 hour

Went with Option 3.

## File structure after Phase 4

```
/Volumes/FlashMoE/flash-moe/
├── metal_infer/
│   ├── infer              # built binary, 500KB
│   └── metal/moe_kernel.metallib  # compiled shaders
├── scripts/
│   ├── extract_weights.py    # from upstream
│   ├── repack_experts.py     # from upstream
│   └── vocab_to_bin.py       # our custom addition
└── ...
```

## Time budget

- Clone + build: 15 min
- Initial test: 5 min
- Reading Flash-MoE scripts: 45 min
- Understanding MoE layout: 30 min
- Writing vocab_to_bin.py: 45 min
- Testing + verification: 30 min
- **Total: ~3 hours**

Majority of time was reading and understanding, not coding. ML infrastructure requires careful study of existing systems.

## Lessons

1. **Read the full pipeline before writing code.** We understood extract + repack before writing vocab tool.

2. **ML tokenizer formats are fragmented.** Every model family has quirks. Don't assume compatibility.

3. **Write minimum viable converters.** Our vocab_to_bin.py is ~50 lines. Could be more elegant but works perfectly.

4. **Verify early.** Testing token 9419 = " Hello" before proceeding saved debugging later.

5. **GPT-2 style byte-level BPE is common.** Qwen, OpenAI, LLaMA all use variants. Learn it once.

## Next phase

[Phase 5 → docs/04-conversion.md](04-conversion.md) — Running extract + repack on the actual 224GB model.
