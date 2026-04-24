# What Worked (And Why)

The patterns, tools, and decisions that made this project succeed. The counterpoint to `what-failed.md`.

## 1. Using a pre-quantized MLX model

### What we used

`mlx-community/Qwen3.5-397B-A17B-4bit` from HuggingFace.

### Why it worked

- Already quantized (4-bit) by MLX community
- Specifically packaged for Apple Silicon
- Compatible with Flash-MoE's expected format after conversion
- Active maintenance (updates when new models drop)
- Avoids running quantization ourselves (which takes days and 256GB+ RAM)

### Alternative paths that would have failed

- Full precision Qwen3.5-397B: 794GB, won't fit on any consumer hardware
- BF16: 397GB, doesn't fit either
- Running GPTQ/AWQ on Apple Silicon: poor support, unstable
- Building from scratch: weeks of work for worse results

### Lesson

**Pre-quantized community models save 90% of setup time.** For new models, wait 1-2 weeks after release for MLX/GGUF ports by community before attempting yourself.

---

## 2. Flash-MoE for expert streaming

### Why Flash-MoE

[Dan Woods's Flash-MoE](https://github.com/danveloper/flash-moe) is:
- Pure C + Metal (no Python runtime overhead)
- Designed specifically for MoE streaming from disk
- Only runtime capable of running 397B on 64GB RAM
- Efficient fd management, page cache integration

### What it does differently

Normal frameworks (transformers, MLX, llama.cpp) load full weights into RAM:
- Need 100+ GB RAM for 4-bit 397B
- Impossible on consumer hardware

Flash-MoE streams individual experts per-token:
- Only active experts loaded (K=4 per token)
- ~17GB peak RAM
- Fits on 64GB with room for OS/services

### Trade-offs

Pro:
- Enables impossible-otherwise inference
- Simple architecture (no Python overhead)
- Predictable memory behavior

Con:
- Slow (SSD bottleneck)
- Limited tooling (no advanced sampling features)
- Sparse documentation

### Lesson

**For memory-constrained MoE inference, Flash-MoE is currently the only viable option.** Accept the trade-offs or use smaller models.

---

## 3. hf-mirror.com for downloads

### Problem

Downloading 224GB from HuggingFace from Korea is:
- Slow (CDN less optimized)
- Prone to rate limiting
- Sometimes fails mid-download

### Solution

`hf-mirror.com` — Chinese mirror with Korean-friendly latency. Used `aria2c` for parallel chunked downloads.

```bash
aria2c -x 16 -s 16 \
  -i urls.txt \
  -d ./downloads
```

Result:
- Batch 1: 110GB in ~2 hours
- Batch 2: 114GB in ~2.5 hours
- Zero retries needed

### Alternative paths

- Direct huggingface.co: 8+ hours, frequent timeouts
- huggingface-cli: similar issues
- Torrent (if available): not available for this model

### Lesson

**Regional mirrors are the difference between "finish in 4 hours" and "maybe finish today, maybe tomorrow".** For Korea, hf-mirror.com worked great. For Europe, try eu-mirror alternatives.

---

## 4. Extract + Repack conversion

### What happened

Phase 6: Converting 46 safetensors shards (224GB) into Flash-MoE format.

Expected time: 1-2 hours based on docs.

Actual time: **83 seconds**.

- Extract: 2.1 seconds (non-expert weights → model_weights.bin, 5.52GB)
- Repack: 81.5 seconds (experts → packed_experts/, 202.5GB, 60 layer files)

Sustained write rate: 2.5-2.8 GB/s on TB5 NVMe.

### Why so fast

- External TB5 SSD had ~4 GB/s sustained write
- Flash-MoE's repack is basically memcpy + simple reformatting
- No quantization during this stage (already quantized in source)
- APFS has efficient large-file writing

### Verification

All 60 layer files:
- Same size: 3,623,878,656 bytes each
- MD5 checksums matched expected values (from Flash-MoE's verification suite)
- 100% success on first try

### Lesson

**Don't trust time estimates in ML documentation.** Actual performance depends on hardware. Time a small test first (1-2 shards) to extrapolate.

Also: **modern SSDs are really fast**. The bottleneck for this project was always CPU/memory, not storage bandwidth.

---

## 5. Writing custom vocab.bin

### The gap

Flash-MoE's documented pipeline assumed certain tokenizer formats. Qwen3.5's tokenizer (byte-level BPE with specific mappings) didn't fit the default conversion.

### What we built

Custom Python script that:
1. Reads `tokenizer.json` (HuggingFace format)
2. Applies `bytes_to_unicode` mapping (OpenAI GPT-2 style)
3. Packs tokens as `uint32 LE` (token ID) + `uint16 LE` (length) prefix
4. Concatenates UTF-8 bytes

Result: `vocab.bin` (7.8 MB, 248,077 tokens).

### Why this mattered

- Without this, Flash-MoE can't decode tokens → output is garbage
- With this, Korean/English/Chinese all work correctly
- One-time cost: ~1 hour of work

### What we learned

- **Tokenizer internals are deeply model-specific**
- Byte-level BPE needs special handling for multi-byte characters
- Output format packing is error-prone (endianness, alignment)

### Lesson

**For new models, tokenizer compatibility is the hidden cost.** Budget time for this even if docs suggest it's automatic.

---

## 6. OpenAI-compatible wrapper

### Why we built it

Flash-MoE's native HTTP interface is minimal (just `/v1/chat/completions` with basic parsing). To integrate with:
- OpenAI SDK (Python, JS)
- Third-party agent frameworks
- Future tools expecting standard API

...we needed OpenAI protocol compatibility.

### What it does

~500 lines of Python (FastAPI + uvicorn):

1. **Receives** OpenAI-format requests
2. **Renders** Qwen chat template (Jinja2) into raw prompt
3. **Forwards** to Flash-MoE's HTTP endpoint
4. **Decodes** byte-level BPE output into UTF-8 text
5. **Parses** Qwen tool-call XML → OpenAI tool_calls JSON
6. **Strips** `<think>...</think>` blocks if requested
7. **Streams** Server-Sent Events (SSE) responses

### Result

- 45/45 integration tests passed
- Works with `openai` Python SDK out of the box
- Works with `curl`
- Works with Telegram bot's OpenAI client

Without this wrapper, every downstream consumer would need to handle Qwen specifics.

### Key design decision

Separate `wrapper` from `infer` — keeps Flash-MoE's internal logic clean, wrapper can evolve independently.

```
[OpenAI client] → [wrapper :8771] → [Flash-MoE :8000]
       ↑                ↑                    ↑
  standard proto   translation          raw tokens
```

### Lesson

**Protocol standardization matters.** 500 lines of wrapper made this model usable by 1000s of existing tools.

If you're building ML services: always expose OpenAI-compatible endpoint, even if your internal format is different.

---

## 7. Minimal custom agent (simple_agent.py)

### Why not use existing framework

Tried Hermes Agent (see `what-failed.md`). 13,859-token system prompt. 50+ min per turn. Unusable.

### What we built

140 lines of Python:

```python
def run_agent(goal, max_iterations=5, max_tokens=500):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},  # 356 tokens
        {"role": "user", "content": goal}
    ]

    for i in range(max_iterations):
        resp = client.chat.completions.create(
            model="qwen3.5-397b-a17b",
            messages=messages,
            tools=TOOLS,
            max_tokens=max_tokens,
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            # Execute, append result, continue loop
            ...
        else:
            return msg.content

    return "[Max iterations]"
```

That's it. System prompt + message loop + tool execution.

### Why it worked

- **Small prompt** (356 tokens vs 13,859) = 40x faster prefill
- **Predictable behavior** (no framework magic)
- **Easy to debug** (all logic visible)
- **Easy to modify** (add/remove tools in minutes)
- **Matches local LLM constraints**

### Results

First successful test:
- Goal: "현재 디렉토리의 파일 개수" (count files in current dir)
- Iteration 1: Tool call `bash("ls -1 | wc -l")`, result: "1"
- Iteration 2: Final answer: "현재 디렉토리의 파일 개수는 1개입니다"
- Total: 5 minutes, 2 iterations

Clean, simple, works.

### Lesson

**For local LLMs, write your own agent loop.** Big frameworks optimize for fast cloud backends. Your constraints are different.

Write 100-200 lines that:
1. Use short system prompts
2. Limit iterations strictly (2-5 max)
3. Constrain max_tokens per step
4. Execute tools transparently
5. Log progress for observability

This is enough. Don't over-engineer.

---

## 8. Serper for web search integration

### Why Serper

Already had `SERPER_API_KEY` from earlier OpenClaw work (166 uses in shell history). Zero new API cost.

Alternatives considered:
- DuckDuckGo: free but lower quality (user complained)
- Google Custom Search: more setup (needs search engine ID)
- Tavily: LLM-specific, 1000/month free but needs new account
- Bing: less Korean coverage

Serper:
- Google results via API
- Already authenticated
- 2500/month free (more than enough)
- Simple REST API (just HTTPS POST)

### Implementation

```python
def web_search(query, num=5, gl="kr", hl="ko"):
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=json.dumps({"q": query, "num": num, "gl": gl, "hl": hl}).encode(),
        headers={"X-API-KEY": load_key(), "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())
```

No extra dependencies — `urllib` from stdlib is enough.

### Result

- Korean local business queries: excellent (see Phase 9.4 Test 3)
- Factual lookups: good
- Time-sensitive queries: limited (see hallucination docs)

### Lesson

**Use existing credentials when possible.** Saves signup friction + consolidates costs + tested in prior work.

Also: **simple HTTP calls beat SDK dependencies.** 20 lines of urllib > importing 50MB SDK.

---

## 9. Telegram bot with user_id whitelist

### Why Telegram

Evaluated alternatives:
- Web UI: need to build, secure, host
- Discord bot: setup complex, fewer Korean users
- SMS: costs per message
- **Telegram**: free, secure, works globally, easy API

### Authorization pattern

```python
ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID"))

def is_authorized(update):
    return update.effective_user.id == ALLOWED_USER_ID

async def handle_message(update, context):
    if not is_authorized(update):
        return  # silent ignore
    # ... proceed with query
```

Simple, effective, no password management.

### Why this works

- Single-user personal assistant
- No need for multi-user auth
- No accounts to manage
- Telegram handles transport security
- Secret in `.env` (not in repo)

### Async execution

Telegram bot polling must not block on long LLM calls:

```python
loop = asyncio.get_event_loop()
answer = await loop.run_in_executor(
    None,  # default thread pool
    lambda: run_agent(goal)  # blocking
)
```

LLM runs in thread, bot stays responsive to other updates (if there were any).

### Progress updates

Long responses (10+ minutes) need visual feedback:

```python
def on_step(step_type, data):
    if step_type == "tool_call":
        text = f"🔧 도구: {data['name']}(...)"
    elif step_type == "tool_result":
        text = f"📋 도구 실행 완료"
    # Edit existing message instead of spamming
    asyncio.run_coroutine_threadsafe(
        status_msg.edit_text(text), loop
    )
```

User sees bot is working, not stuck.

### Lesson

**Personal bots don't need complex auth.** User_id check is enough for single-user systems. Secure the token in .env, set restrictive file permissions (600).

---

## 10. tmux for persistent services

### Why tmux

Need:
- Multiple background services (infer, wrapper, bot)
- Survive terminal disconnect
- Easy to inspect logs live
- Restart-friendly

Alternatives:
- systemd: macOS doesn't use it
- launchd: complex plist files, harder to iterate
- nohup: no easy inspection
- Docker: overkill for this

tmux:
- Single command creates detached session
- Easy to attach for debugging
- Sessions persist through terminal close
- Native on macOS

### Patterns used

```bash
# Start detached
tmux new-session -d -s infer_serve \
  "ulimit -n 10240; ./infer --serve 8000 2>&1 | tee log"

# Inspect
tmux attach -t infer_serve

# Exit inspection but keep running
Ctrl+B, D

# List sessions
tmux ls

# Kill
tmux kill-session -t infer_serve
```

### Result

3 services run independently:
- `infer_serve` (Flash-MoE)
- `wrapper` (FastAPI)
- `telegram_bot` (python-telegram-bot)

Can restart one without others. Can inspect logs live. Simple.

### Lesson

**For local dev services, tmux is the sweet spot.** Persistent enough for production-like use, light enough that you can iterate fast. LaunchAgent for truly persistent services, tmux for development + personal tools.

---

## 11. Script-based startup/shutdown

### What we built

`start_all.sh`:

```bash
#!/bin/bash
# Clean, then start, then verify

for session in infer_serve wrapper telegram_bot; do
  tmux kill-session -t "$session" 2>/dev/null
done

tmux new-session -d -s infer_serve "..."
sleep 10
curl -sf http://localhost:8000/health

tmux new-session -d -s wrapper "..."
sleep 5
curl -sf http://localhost:8771/health

tmux new-session -d -s telegram_bot "..."

echo "Ready"
```

One command: `bash ~/.flashmoe/bin/start_all.sh`

### Verified on reboot

After Mac Mini reboot:
- Run start_all.sh
- All three services up in ~30 seconds
- Telegram bot responsive within 1 minute
- No manual intervention needed

### Why this matters

Without this script:
- Post-reboot recovery: 5-10 manual commands
- Risk of forgetting steps
- Inconsistent results

With this script:
- 1 command
- Idempotent (safe to run multiple times)
- Self-verifying (health checks)
- Documented (script IS the docs)

### Lesson

**Automate any service that runs for > 1 day.** You WILL forget the exact commands. Script saves future-you from past-you's memory.

---

## 12. Modular file organization

### Structure

```
~/.flashmoe/
├── bin/        # Scripts
├── flash-moe/  # Upstream code (don't modify)
├── model/      # Large assets
├── agent/      # Our custom code
│   ├── simple_agent.py
│   ├── web_agent.py
│   └── tools/
├── telegram/   # Bot + secrets (.env)
├── README.md
└── SESSION_LOG.md
```

### Why this worked

- **Clear separation**: our code vs upstream
- **Easy backup**: archive `~/.flashmoe/` excluding `model/` (which is easy to re-download)
- **Easy migration**: move to new machine, restore, update paths
- **Secrets isolated**: only `telegram/.env` needs protection
- **Self-documenting**: structure shows what's there

### Avoided patterns

- Everything in `~/`: messy, conflicts with other tools
- Hidden under `/usr/local/`: harder to inspect
- Multiple GitHub repos: harder to version together
- Mixed with OpenClaw (`~/.openclaw/`): confusing ownership

### Lesson

**One directory per project.** Under home, visible (not hidden), clear sub-structure. Future-you will thank present-you.

---

## Patterns across successes

What do these successes have in common?

1. **Simplicity over framework magic** — custom 140-line agent beat 100k-star Hermes
2. **Use existing credentials** — Serper key, no new signups
3. **Stdlib over dependencies** — urllib, not requests; no extra pip install for basic needs
4. **One-shot automation** — start_all.sh, not manual steps
5. **Clear module boundaries** — wrapper separate from infer, agent separate from bot
6. **Verify before trusting** — MD5 checks on migration, health checks in startup
7. **Match local LLM constraints** — short prompts, few iterations, realistic max_tokens

These patterns transfer to any local LLM project. Write them down, apply them next time.
