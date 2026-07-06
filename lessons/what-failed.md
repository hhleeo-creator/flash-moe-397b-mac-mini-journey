# What Failed (And Why)

Every failure in this project, with root cause and lesson. More valuable than the successes, because failures is where others will also get stuck.

## 1. `--cache-entries 20000` → pread errors (1274 per 10 tokens)

### What happened

Tried to maximize Flash-MoE expert cache by increasing from default 2500 to 20000 entries (would use ~140GB RAM, well within 64GB limit... wait).

Actually the malloc_cache option is 17GB. cache_entries 20000 is supposedly ~140GB but Flash-MoE uses a page-cached mmap so it's not literal RAM allocation.

Result:
```
WARNING: expert 63 pread: -1/7077888
WARNING: expert 417 pread: -1/7077888
WARNING: expert 94 pread: -1/7077888
... (1274 total per short run)
```

Direct `./infer` calls: Still generated tokens (with fallback).
Via wrapper: **generated=0 tokens**. Complete failure.

### Root cause (hypothesis)

Flash-MoE's internal buffer management or fd pool breaks somewhere above default cache_entries. We didn't dig deep into source to find exact line, but:

- Tested 5000: 47 pread errors, still generated=0
- Tested 2500 (default): 0 pread errors, works perfectly

Binary search would find breakpoint between 2500-5000.

### What we tried that didn't help

1. `ulimit -n 10240` (from 256) — no effect on pread rate
2. `xattr -cr` to remove extended attributes — no effect
3. File integrity check (MD5) — all files intact
4. `--predict` flag toggle — no effect
5. Internal vs external SSD comparison — same errors on both

### Lesson

**Do not tune `--cache-entries`. Default 2500 is Flash-MoE's tested optimum.** Accept ~5 tok/s and move on.

This cost us 3+ hours of debugging. A clear warning in Flash-MoE's README would have saved this.

---

## 2. Hermes Agent integration → 50+ minutes per turn

### What happened

Installed [Hermes Agent](https://github.com/NousResearch/hermes-agent) (100k stars) to use as agent framework on top of local wrapper.

Configured it to point at local OpenAI-compatible endpoint:
```yaml
model:
  default: "qwen3.5-397b-a17b"
inference:
  provider: "custom"
  base_url: "http://127.0.0.1:8771/v1"
  api_key: "local-dummy"
```

Sent a simple query: "Hello! What model are you running on?"

Waited 14 minutes. Still "processing". Killed it.

### Root cause

Dumped infer server logs:
```
[serve] chatcmpl-3 prompt=13859 tokens  ← ← ← problem
[serve] chatcmpl-3 content=62968 chars, max_tokens=2048
```

**Hermes sends a 13,859-token system prompt** defining its 14 default tools (file I/O, shell, browser, code execution, vision, TTS, etc.).

At Flash-MoE's measured 190ms/token prefill speed:
- 13,859 × 190ms = **44 minutes prefill**
- 2,048 tokens generation × 210ms = **7 minutes generation**
- **Total: 50+ minutes per turn**

### Why this happens

Hermes was designed assuming API-class backends:
- Claude/GPT-4: 100+ tok/s prefill
- OpenRouter: similar
- **Local 397B MoE**: 5 tok/s prefill

The 13.8k token prompt is fine when prefill is 2 minutes. It's impossible when prefill is 44 minutes.

### What we tried

1. Tried disabling tools via config — no clear documentation
2. Considered reducing to 3-5 tools — would still be 2-4k tokens
3. Looked for "minimal" mode — doesn't exist cleanly

Abandoned Hermes entirely.

### Lesson

**Big agent frameworks assume fast LLM backends.** Their "overhead is fine" calculation is based on 100+ tok/s prefill. At 5 tok/s, every framework token costs 20x more time.

**For local LLMs, write your own minimal agent loop.** Our replacement (simple_agent.py + web_agent.py) is 140-250 lines and uses 356 token system prompt. 40x less prefill overhead = 40x more usable.

This cost ~2 hours of investigation.

---

## 3. External SSD detach (macOS + Acasis TB5)

### What happened

Phase 7 used external WD SN850X 2TB in Acasis TB5 enclosure. Faster (5.41 tok/s vs 3.17 internal), but detached randomly.

Log from night:
```
[2026-04-23 21:25:25] (Sandbox) System Policy: touch(30430) deny(1)
  file-write* /Volumes/FlashMoE/.keepalive
[2026-04-23 21:25:35] (Sandbox) System Policy: touch(30482) deny(1)
  file-write* /Volumes/FlashMoE/.keepalive
... (repeating every 10 seconds all night)
```

Keepalive LaunchAgent was running but **macOS Sandbox TCC denied the touch syscall**. So:
- Keepalive thought it was working
- External enclosure saw no I/O for 5 minutes
- Acasis JHL9480 controller entered idle, triggered disconnect
- Volume unmounted

### Root cause

Two failures compounding:

1. **Acasis TB5 enclosure has 5-minute idle timeout** — not configurable via software
2. **macOS Sandbox TCC protects external volumes from unsigned scripts** — Terminal/bash not automatically granted write access to mounted external drives

Keepalive scripts that worked fine on Intel Macs/older macOS break on Apple Silicon + latest macOS with tightened sandbox.

### What we tried

1. `pmset -a disksleep 0` — doesn't prevent enclosure-level sleep
2. Touch loop every 10s — denied by Sandbox
3. Read-based keepalive (`ls`, `stat`) — partial success but not reliable
4. LaunchAgent installation — runs but can't write
5. **Migration to internal SSD** — solved it completely

### Lesson

**External SSD for local LLM inference is enclosure-sensitive on macOS.**

If you need external storage:
- Buy or use an enclosure with no aggressive idle timeout
- Or test 48+ hours before committing
- Or grant Full Disk Access to Terminal/script binary
- Or migrate data to internal SSD and use external as backup only

$250 enclosure + $180 SSD = $430 for something best used as backup now. Not wasted (does back up model), but not the role intended.

Internal SSD is 35% slower but 100% stable. For continuous service, stability > speed.

### 2026-07 follow-up: BeeLink Mate Mini EX B

This failure was specific to the original Acasis TB5 enclosure used in Phase 7. Later, the external workflow became stable after moving the WD SN850X to a **BeeLink Mate Mini EX B** enclosure.

The corrected lesson:
- Do not treat "external SSD" as one category.
- The exact enclosure controller and power-management behavior matter.
- For Flash-MoE expert streaming, validate the actual enclosure with long idle periods, restart cycles, and always-on serving.
- In this setup, Acasis TB5 was unstable; BeeLink Mate Mini EX B has been stable in later use.

---

## 4. Korean degenerate loop with larger cache (`æĸĩæĸĩæĸĩ...`)

### What happened

Testing `--cache-entries 20000 --predict` with Korean prompt:

```
한국 음식 3가지 추천해주세요
```

Output:
```
æĸĩ  [gen 181/200] token_id=95905
æĸĩ  [gen 182/200] token_id=95905
æĸĩ  [gen 183/200] token_id=95905
... (same token 20+ times in a row)
```

Same token_id=95905 repeated. Model stuck generating one character.

### Root cause

The pread errors (see failure #1) caused some experts to fail loading. Flash-MoE fell back to other experts. But with 53% expert failure rate, too many fallbacks corrupted the routing computation.

Result: logit distribution degenerated, argmax keeps picking same token.

Also: byte-level BPE (`æĸĩ`) means the underlying UTF-8 bytes for CJK character "文" — model locked into one Korean character's byte sequence.

### What we tried

- Different cache_entries values (same issue above 2500)
- Different prompts (degenerate loop on long Korean prompts specifically)
- Wrapper vs direct call (direct was "better" = failed visibly; wrapper returned generated=0)

### Lesson

**MoE quality is sensitive to expert availability.** When too many experts fail to load, output degenerates even if tool calling framework says "success".

Always check output text content, not just HTTP status or finish_reason.

Related: **Korean and other non-Latin scripts expose this faster** because they need more tokens per character → more expert activations → more chances to hit failures.

---

## 5. max_tokens=800 too small for structured Korean output

### What happened

Telegram bot with max_tokens=800. User asked detailed question:
> 기계식 시계는 항상 태엽감고 관리해야하는게 귀찮아. 정확하고 관리가 필요없는건 어떤종류의 시계지?

Model started well:
- 쿼츠 시계 설명
- 솔라 시계 추천 (시티즌 에코드라이브, 세이코 솔라)
- 키네틱 시계 비교
- 결론: "10년 이상 배터리 교체 없이도 사용 가능한 모델이"

**Cut off mid-sentence.** "모델이" — word incomplete.

### Root cause

Korean has 1.5-2 tokens per character (UTF-8 BPE). max_tokens=800 ≈ 400-530 Korean characters. Good structured response easily exceeds this.

### Fix

Raise max_tokens to 2500 (enough for ~1500 chars / 400 words Korean).
Trade-off: 2-3x longer generation time per query.

### Lesson

**Set max_tokens based on expected output, not a generic default.**

For Korean:
- Short answer: 500
- Detailed response: 1500-2000
- Blog post draft: 2500+
- Long article: 3500+

Each +1000 tokens ≈ +4 minutes generation time on this hardware. Plan accordingly.

---

## 6. Hallucination on time-sensitive queries

### What happened

User asked "오늘자 연예계 뉴스 3개" (today's entertainment news, 3 items).

Bot response (2026-04-24 13:51):
```
"검색 결과와 2024년 5월 23일 기준 주요 뉴스를 바탕으로..."

1. 크래비티 일본 활동 (2024 news)
2. 라이즈 LA 다저스 행사 (2024 event)
3. BTS RM 'MINE' 앨범 (fabricated — doesn't exist)

Additionally: 문빈 비보 (2024 April event)
김호중 암표 의혹 (2024 May issue)
```

All 2024 information presented as 2026-04-24 "today's news".

Second attempt with explicit date:
```
"오늘은 2026년 4월 24일이야. 오늘자 연예계 뉴스 3개 요약 다시해줘"
```

Response: Completely fabricated 3 news items dated 2026-04-24, including:
- Natalie Portman pregnancy (not factual)
- Sandra Bullock husband 3rd anniversary (wrong date + wrong facts — her partner died in 2023, not husband)
- Korean actor 옥택연 "today's wedding" (fabricated — he married in 2025)

### Root cause

Multiple compounding issues:

1. **Training cutoff**: Qwen3.5 data ends ~2024. Model's "current" sense stuck in 2024.
2. **No today date injection**: System prompt didn't specify 2026-04-24
3. **Serper search quality**: For "today's entertainment news", Google returns generic pages, not truly current news
4. **Weak grounding**: When search results are sparse, model fills with training data instead of saying "don't know"
5. **System prompt permissive**: "답변이 확실하면 도구 없이 바로 응답" — model over-interpreted as permission to skip search

### What helps

- Add current date to system prompt dynamically:
```python
  today = datetime.now().strftime("%Y년 %m월 %d일")
```
- Explicit "reject training data for post-2024 queries"
- Serper `/news` endpoint with `tbs=qdr:d` (last 24 hours filter)
- Force tool use for time-sensitive keywords

### What doesn't help

- Bigger models: Hallucination isn't solved by scale alone
- Lower temperature: Makes hallucinations more confident, not less frequent
- Better prompts: Reduces but doesn't eliminate

### Lesson

**Local LLMs are unreliable for time-sensitive information, even with web search.** Training data from 2024 permeates responses.

Use cases that work:
- Timeless knowledge (history, science, concepts)
- Personal analysis (your own data, no external reference needed)
- Creative tasks (writing, brainstorming)
- Structured questions with clear grounding (e.g. "given this data, what's the trend")

Use cases that don't work:
- News ("what happened today")
- Current status ("who is president", "current stock price")
- Recent events ("who won the match")

For these: use Perplexity, GPT-4 with browsing, or direct web search. Don't trust local LLM output.

---

## 7. Testing trap: fast direct calls vs slow Telegram calls

### What happened

Our initial benchmarking via direct curl was fast:
- "Hello" → 9.87s, 3 tok/s
- Korean 300 chars → 68.71s, 4.4 tok/s

But Telegram bot responses felt slower. User confusion.

### Root cause

Direct curl had:
```json
{
  "messages": [{"role": "user", "content": "안녕"}],
  "max_tokens": 100
}
```

1 iteration, no system prompt, no tools.

Telegram bot uses full `run_agent()`:
- System prompt (~200 tokens)
- Tools defined in prompt (~400 tokens)
- Agent loop (potentially multi-iteration)
- Each iteration: system + tools + accumulated context

Iteration 2 prompt after tool call: **~2500 tokens** (includes search results).

At 190ms/token prefill:
- Direct simple call: ~1 minute
- Agent loop with search: ~10 minutes

### Lesson

**Benchmarks must match real use case.** Our "5 tok/s" was optimistic because it was raw generation without agent overhead.

When measuring local LLM performance:
- Simple prefill (< 100 tokens): generation-limited (high tok/s)
- With system prompt + tools (> 500 tokens): prefill-limited (low apparent tok/s)
- Agent loop with search: prefill-dominated (very low apparent tok/s)

Report both numbers or users will be confused.

---

## 8. Session context loss with Claude Code reboot

### What happened

During peak of debugging the pread error issue, we had Claude Code (terminal AI assistant) running with full context of all previous debugging steps, hypotheses tried, logs analyzed.

Rebooted Mac Mini to try clean start. All Claude Code session context evaporated.

### Impact

Not catastrophic — files preserved, SESSION_LOG.md captured key points. But continuing the same debug session required re-introduction of context.

### Lesson

**Long AI-assisted work should periodically checkpoint to files.**

What we did right:
- SESSION_LOG.md updated throughout
- README.md with operational state
- Commits (when we had git — not yet this time)

What we'd do better:
- Dump conversation context to file periodically: `claude memory save`
- Never rely on "the AI remembers"
- Short episodes with clear entry points

---

## Meta-lesson: Failure as core content

Every failure above took hours to resolve. Each has a specific lesson.

Reading them:
- You can avoid our mistakes
- You can recognize similar symptoms faster
- You understand why "it's supposed to work" doesn't always work

**Failure documentation is more valuable than success documentation** for technical journeys. Success is generic; failure is specific and educational.

If you use this repo as an AI training corpus or reference: the `lessons/` directory is the most valuable section.
