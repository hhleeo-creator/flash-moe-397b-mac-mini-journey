# Complete Journey Overview

## Timeline

- **Day 1 (2026-04-23)**: Phases 1-8. Build foundation, first inference, OpenAI-compatible wrapper
- **Day 2 (2026-04-24)**: Phase 9. Internal SSD migration, agent, Telegram bot

Total active work: ~25 hours over 2 days.

## Phase Summary

### Day 1

**Phase 1-2: Environment + SSD Setup** (2-3 hours)
- macOS 15 on Mac Mini M4 Pro 64GB
- WD Black SN850X 2TB NVMe in Acasis TB5 enclosure
- Benchmarked ~6 GB/s sustained read via TB5
- APFS formatting, mount configuration

**Phase 3: Flash-MoE Build** (30 minutes)
- Cloned github.com/danveloper/flash-moe
- Built `metal_infer` binary (pure C + Metal)
- No standard ML dependencies (no PyTorch, no MLX runtime)

**Phase 4: Scripts Analysis + Gap Fill** (2-3 hours)
- Analyzed extract/repack/vocab scripts
- Wrote custom `vocab.bin` generator for Qwen3.5 tokenizer (BPE + byte-level)
- Handled `bytes_to_unicode` mapping, `uint32/uint16 LE` packing

**Phase 5: Model Download** (4-5 hours, split in 2 batches)
- Model size: 224GB across 46 safetensors shards
- Used `aria2c` with hf-mirror.com (Korea-friendly)
- Batch 1: shards 00-23 (~110GB)
- Batch 2: shards 24-46 (~114GB)
- Had to move files from internal staging to external mid-download

**Phase 6: Conversion** (83 seconds! — way under projection)
- Expected: 1+ hour. Actual: 2.1s extract + 81.5s repack.
- Sustained 2.5-2.8 GB/s throughput on TB5 NVMe
- Output: `model_weights.bin` (5.52GB) + `packed_experts/` (202.5GB, 60 layer files)
- All 60 layers verified via checksum

**Phase 7: First Inference** (1 hour)
- Smoke test: **5.41 tok/s**, per-layer 3.009ms, expert_io 1.606ms
- First output: "Hello, my name is Aryan, and I am a 10th-grade student..."
- 60/60 packed layer files successfully mmap'd
- K=4 active experts per token

**Phase 8: OpenAI-Compatible Wrapper** (30 minutes — expected 8+ hours)
- FastAPI + uvicorn wrapper on port 8771
- Qwen chat template (Jinja) rendering
- Byte-level BPE decode for Korean output
- Tool-call XML → OpenAI JSON conversion
- Think-block stripping (`<think>...</think>` removal)
- SSE streaming passthrough
- **45/45 tests passed**, real Korean ad copy verified

### Day 2

**Phase 9.0: External → Internal Migration** (8 minutes!)
- `cp -R` at 660 MB/s sustained (APFS optimization)
- 202GB packed_experts copied in 5 min 7s
- MD5 verification: all layers match
- Motivated by: Acasis TB5 idle detach issues (keepalive + sandbox TCC conflicts)

**Phase 9.1: pread Debug Marathon** (3 hours)
- Internal showed 3.17 tok/s vs external 5.41 tok/s (expected opposite)
- Tried `--cache-entries 20000` → 1274 pread errors, generated=0 via wrapper
- Tried `ulimit -n 10240` → no effect on pread rate
- Tried `--predict` → no effect
- Debugged xattr, ulimit, file integrity (all fine)
- **Root cause**: Flash-MoE cache_entries default (2500) is a hard optimum. Larger values trigger internal buffer issues.
- Resolution: Stick with defaults, accept 35% speed reduction for stability

**Phase 9.2: Hermes Agent Attempt** (2 hours, wasted)
- Installed Hermes Agent (100k GitHub stars)
- Configured to point at local wrapper
- Chat query hung at "iteration 2" for 14+ minutes
- Debug revealed: Hermes sends 13,859-token system prompt (14 tools × descriptions)
- At Flash-MoE's 190ms/token prefill → ~44 minutes prefill + 7 min generation = **50+ minutes per turn**
- Framework incompatible with local LLM throughput
- **Abandoned** — kept installed but unused

**Phase 9.3: Custom Agent** (45 minutes)
- Wrote `simple_agent.py` (140 lines) from scratch
- Minimal system prompt (356 tokens, vs Hermes 13,859)
- bash tool for command execution
- **2.5 minutes/turn** — 20x faster than Hermes
- First successful test: "current directory file count" → 2 iterations, 5 minutes

**Phase 9.4: Web Search Integration** (1 hour)
- Discovered existing SERPER_API_KEY in ~/.openclaw/.env (166 uses in history)
- Wrote `tools/web_search.py` (pure urllib, no deps)
- Wrote `web_agent.py` extending simple_agent with web_search + fetch_url tools
- Serper `/search` endpoint with `gl=kr`, `hl=ko`
- Tests:
  - Basic knowledge (capital of Korea): tool not used, 3.5 min ✓
  - Recent events (president): tool used, but hallucinated from sparse results ⚠️
  - Local business (clinics in Songpa): tool used, accurately returned real results including user's own clinic ✓

**Phase 9.5: Telegram Bot** (30 minutes)
- python-telegram-bot library
- user_id whitelist (single authorized user)
- Progress callbacks: "🔧 Tool call", "📋 Result", "✅ Final"
- Long message chunking (Telegram 4096 char limit)
- Graceful error handling (bot stays alive)
- Live verification: `/status`, Korean greetings, weather query (10 min response with web search)

**Phase 9.6: Operations Documentation** (30 minutes)
- `start_all.sh` — one-command full stack startup
- `stop_all.sh` — clean shutdown
- `README.md` with operational guide
- `SESSION_LOG.md` with complete 2-day history
- Reboot recovery verified

## Total Cost Summary

### Money
- WD Black SN850X 2TB: ~$180
- Acasis TB5 enclosure (JHL9480): ~$250
- Total hardware: ~$430
- API costs: $0 (uses existing Serper key from prior work)

### Time
- Active development: ~25 hours
- Idle waiting (downloads, processing): ~8 hours
- Total elapsed: 2 days

### What Was Learned
- MoE quantization internals (BF16, U32, expert layout)
- Metal compute shaders for MoE (via Flash-MoE source)
- macOS TB5 + APFS behavior under sustained load
- Local LLM prefill/generation throughput realities
- Limits of "framework thinking" when porting to resource-constrained LLMs

## What I'd Do Differently

1. **Skip Hermes earlier** — 2 hours debugging a framework incompatible by design
2. **Keep defaults** — `--cache-entries 2500` was optimum from start; don't tune
3. **Internal SSD from start** — Avoid Acasis TB5 + macOS Sandbox drama entirely
4. **Measure prefill separately from generation** — Combined tok/s hides bottleneck
5. **Know the limits before starting** — 3-5 tok/s is the practical ceiling; plan use cases accordingly

## Next Steps (Potential)

- Medical transcription pipeline (privacy-bound, non-time-sensitive)
- Batch analysis tasks (overnight runs)
- Hybrid: simple local + cloud for complex
- Upgrade path: wait for M5 Ultra or next-gen model releases
