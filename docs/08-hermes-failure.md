# Phase 9.2: Hermes Agent Incompatibility (The 14-Minute Hang)

**Date**: 2026-04-24 (around 10:00-12:00)
**Duration**: ~2 hours investigation + debugging
**Outcome**: Abandoned Hermes, rebuilt custom agent from scratch

## Setup expectation

After successfully building the Flash-MoE + OpenAI wrapper stack (Phase 8), we wanted a production-ready agent framework. [Hermes Agent](https://github.com/NousResearch/hermes-agent) from NousResearch looked ideal:

- **112k+ GitHub stars** — clearly popular
- **MIT licensed** — free to use
- **TUI interface** — good for Terminal-first workflows
- **OpenAI-compatible** — should plug into our wrapper directly
- **Active development** — maintained, regular updates

The plan: point Hermes at our local wrapper, get a polished agent interface in 30 minutes.

## Installation (worked smoothly)

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash -s -- --skip-setup
```

Installed to `~/.hermes/` in about 3 minutes. Added binary to `~/.local/bin/hermes`. No errors.

## Configuration (easy)

Edited `~/.hermes/config.yaml`:

```yaml
model:
  default: "qwen3.5-397b-a17b"

inference:
  provider: "custom"
  api_key: "local-dummy"
  base_url: "http://127.0.0.1:8771/v1"
```

Pointed at our wrapper. Simple.

## First query: The Hang

```bash
hermes chat -q "Hello! In one short sentence, what model are you running on?"
```

Expected: 10-30 second response (short query).
Observed: Still running after 5 minutes. Then 10 minutes. Then 14 minutes.

Killed the process.

## Debugging

### First suspicion: wrapper not responding

Checked wrapper logs:
```
INFO: POST /v1/chat/completions HTTP/1.1 200 OK
```

Wrapper IS responding. So what's taking so long?

### Checked infer logs

```bash
tail -100 /Users/migi/flashmoe_logs/infer_serve.log
```

Key lines:
```
[serve] chatcmpl-1 prompt=24 tokens     (ok, this was a probe)
[serve] chatcmpl-2 prompt=25 tokens     (another probe)
[serve] chatcmpl-3 content=62968 chars, max_tokens=2048
[serve] chatcmpl-3 prompt=13859 tokens  ← ← ← THE PROBLEM
```

**Hermes sent a 13,859-token prompt for a simple "Hello" query.**

What?

### Dissecting Hermes's prompt

The prompt included 14 tool definitions with full JSON schemas:

```
- Bash: Execute shell commands
- FileRead: Read files
- FileWrite: Write files
- FileEdit: Edit files with patches
- Grep: Search file contents
- WebFetch: Fetch web content
- WebSearch: Search the web
- Glob: Find files by pattern
- NotebookRead: Read Jupyter notebooks
- NotebookEdit: Edit Jupyter notebooks
- Task: Delegate to sub-agents
- TodoWrite: Manage task lists
- ExitPlanMode: Exit planning mode
- VisionRead: Process images
```

Plus detailed system prompt describing:
- Agent behavior guidelines
- Tool use patterns
- Error handling
- Context management
- Response formatting
- Safety considerations

Total: 62,968 characters = ~13,859 tokens.

## The Math of Doom

At Flash-MoE's measured prefill rate on Mac Mini M4 Pro:

**Prefill rate**: ~190 ms per token

**For 13,859 tokens**:
- 13,859 × 190ms = **2,633 seconds**
- = **43 minutes 53 seconds**

**Plus generation** (max_tokens=2048):
- 2,048 × ~210ms = **430 seconds = 7 minutes**

**Total per turn**: **50+ minutes**

And that's just the FIRST turn. Multi-turn conversations would exponentially worsen.

## Why this happens

Hermes was designed for cloud-class LLM backends:

| Backend | Prefill Speed | 13.8k tokens prefill time |
|---|---|---|
| OpenRouter Claude | ~500 tok/s | **28 seconds** |
| GPT-4 API | ~200 tok/s | **69 seconds** |
| Claude API | ~400 tok/s | **35 seconds** |
| **Flash-MoE Qwen 397B** | **~5 tok/s** | **44 MINUTES** |

On cloud: 14 tools + detailed prompt = 30 seconds overhead. Acceptable.
On local: same = **90x slower** = unusable.

**Hermes made a perfectly reasonable design decision for its target audience. We were not the target audience.**

## Things we considered

### Reduce tool count

Could we disable 10 of the 14 tools, keeping only essentials?

Investigation:
- No clear config option to disable tools
- Tools defined in Rust code, not editable config
- Would need to fork and recompile

Even with 4 tools: ~3,000 token system prompt = 9.5 minutes prefill. Still too slow.

### Modify the system prompt

Hermes's prompt is defense-in-depth: "when faced with X, do Y; when faced with Z, consider W". Lots of conditional guidance.

Could we strip it down?

Investigation:
- System prompt partially generated at runtime based on tools
- Hard-coded safety guidance mixed with flexibility text
- Removing pieces risks breaking tool selection logic

Decided: not worth the effort. Different design paradigm.

### Accept the slowness

"50 minutes per turn is still better than nothing."

Problem: First turn after a user-corrected clarification = another 50 minutes. And another. Real conversation = 3-5 hours of waiting.

For a personal assistant, this breaks the use case entirely.

## The Pivot

After 2 hours trying to make Hermes work, decided:

**Write custom minimal agent from scratch.**

See [`docs/09-custom-agent.md`](09-custom-agent.md) for that story. Short version:

- 140 lines of Python
- 356-token system prompt
- 2.5 min/turn instead of 50+
- **20x faster** than Hermes

Simple code beat 100k-star framework because it was designed for our constraints, not theirs.

## Could Hermes work with faster hardware?

If you have:
- M3 Ultra / M4 Max with 128GB+ RAM
- Better model (70B instead of 397B)
- Or cloud backend (Anthropic/OpenAI API as configured)

...Hermes would likely work great. Its design assumes ~100 tok/s prefill minimum.

Our setup (64GB, 397B MoE streaming from SSD) was simply outside Hermes's operational envelope.

## Final state

Hermes remains installed at `~/.hermes/` (didn't uninstall in case future use case emerges). Config still points at wrapper. But we don't use it.

If cloud APIs ever become the default path, Hermes would be ready. For local 397B: abandoned.

## Time cost

- Research (does Hermes exist, is it right?): 15 min
- Installation: 5 min
- Configuration: 10 min
- First query + wait: 14 min
- Debugging (logs, math, validation): 45 min
- Considering fixes: 30 min
- Decision to pivot: 10 min
- **Total: 2 hours**

Not wasted — understanding why Hermes fails taught us exactly what to build. But a painful detour.

## Lessons

### 1. Check your numbers first

Before installing anything, compute:
- "What prompt size is my framework likely to send?"
- "At my inference speed, how long will that take?"
- "Is that acceptable?"

5 minutes of math would have saved 2 hours.

### 2. Framework != appropriate for all backends

Popular tools solve common problems. Your problem might not be common.

100k stars means many users love it. Doesn't mean YOUR use case is theirs.

### 3. Local LLMs need different patterns

Cloud patterns: lots of context, rich tool definitions, exploratory agents.
Local patterns: minimal context, focused tools, deliberate agents.

Don't port cloud architectures to local. Redesign for local constraints.

### 4. "Tried and true" has context

"Hermes is tried and true for AI agents" — true in context.
The context is: "with cloud-class LLM backends."

Always ask: tried and true for WHAT?

## For future Hermes evaluators

If you're considering Hermes for local LLM backend:

- [ ] What's your prefill speed (tok/s)?
- [ ] What's Hermes's default prompt size for your config?
- [ ] Prefill time = prompt_size / prefill_speed
- [ ] Acceptable if under 1 minute per turn
- [ ] Problematic if over 5 minutes per turn

If your math says ">5 minutes", don't use Hermes. Write your own minimal agent.

---

**Related**:
- [09-custom-agent.md](09-custom-agent.md) — What we built instead
- [lessons/what-failed.md](../lessons/what-failed.md#2) — Brief summary of this failure
