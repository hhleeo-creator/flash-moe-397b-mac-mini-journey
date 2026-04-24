# Reddit Post Draft: r/LocalLLaMA

**Title**: Running Qwen3.5-397B-A17B-4bit on Mac Mini M4 Pro (64GB) - Full Journey with Benchmarks and Failures

---

## Body

I spent 2 days getting Qwen3.5-397B-A17B-4bit (~208GB) running on a Mac Mini M4 Pro 64GB via [Flash-MoE](https://github.com/danveloper/flash-moe) expert streaming. Wrote down everything including failures. Sharing because there's not much documentation for this specific setup.

**Full repo with code + benchmarks + failure docs**: https://github.com/hhleeo-creator/flash-moe-397b-mac-mini-journey

### TL;DR Results

- **Speed**: 3-5 tok/s generation, 190ms/token prefill
- **RAM**: ~17GB peak (fits comfortably in 64GB)
- **Context**: 32K tokens
- **Stability**: Stable on internal NVMe, unstable on external TB5 enclosure
- **Practical use**: Works for Telegram bot, offline Q&A, batch work. Too slow for real-time chat.

### Key Findings (things the docs don't warn you about)

**1. `--cache-entries` default (2500) is mandatory.**
Tried 20000 for more RAM caching → 1274 pread errors per 10 tokens → generation completely breaks through the wrapper. Tested 5000 → still breaks. Default is the only stable value. Don't tune.

**2. Hermes Agent is incompatible.**
Their default system prompt is 13,859 tokens defining 14 tools. At 190ms/token prefill = **44 minutes prefill per turn**. Had to write my own 140-line agent that uses 356-token system prompt. See `docs/08-hermes-failure.md` in repo.

**3. External TB5 SSD unreliable on macOS.**
WD SN850X in Acasis TB5 enclosure was faster (5.41 tok/s vs 3.17 internal) but detached randomly. Root cause: enclosure has 5-min idle timeout + macOS Sandbox TCC blocks keepalive touch syscalls. Moved to internal SSD, accepted 35% speed penalty for 100% stability.

**4. Time-sensitive queries hallucinate badly.**
Even with Serper web search, "today's news" queries invent 2024 events or make up entirely fake ones matching today's date. Training cutoff dominates. Use Perplexity for current events; this for timeless stuff.

### Full Breakdown in Repo

```
docs/           # Phase-by-phase implementation
benchmarks/     # Hardware comparisons, cache tuning, tok/s measurements
lessons/        # Failure modes, hallucination cases, success patterns
code/           # Agent, wrapper, Telegram bot
```

### Hardware Cost

- Mac Mini M4 Pro 64GB: already owned
- WD SN850X 2TB + Acasis TB5 enclosure: ~$430 (used it, but internal would've been enough)
- Serper API: free tier sufficient
- Total marginal cost: $0 (for me) or $430 if buying external storage

### What This Replaces

For my use case (Korean medicine clinic operator running personal tools):

- ❌ Does NOT replace Claude/GPT-4 for daily use
- ❌ Does NOT replace Perplexity for news
- ✓ Does replace cloud APIs for private data analysis
- ✓ Does work for Telegram-based personal assistant
- ✓ Does provide learning value re: MoE architecture

### What Would I Do Differently

1. Skip external SSD, use internal from day one
2. Don't tune cache flags, use defaults
3. Write agent from scratch immediately, skip frameworks
4. Set expectations: 3-5 tok/s is the ceiling, plan use cases around it

### Happy to Answer Questions

Especially about:
- Flash-MoE internals (extract/repack, vocab.bin)
- Korean tokenization with byte-level BPE
- OpenAI-compatible wrapper for local models
- Telegram bot with async + thread executor pattern
- When to NOT use local LLMs

Hit me in comments or open issues on the repo.

---

## Hacker News Version (Shorter)

**Title**: Show HN: Running 397B MoE model locally on $1500 Mac Mini (with benchmarks)

**Body**:

I documented 25 hours of work getting Qwen3.5-397B-A17B-4bit running on a Mac Mini M4 Pro 64GB using [Flash-MoE](https://github.com/danveloper/flash-moe) (expert streaming from disk).

Repo: https://github.com/hhleeo-creator/flash-moe-397b-mac-mini-journey

Results: 3-5 tok/s, ~17GB RAM, runs a Telegram bot with web search. Not fast enough for real-time chat but works for batch work and offline queries.

Key findings:
- Cache tuning breaks generation (stick to defaults)
- Popular agent framework (Hermes) incompatible due to 13.8k-token system prompt
- External TB5 SSD unstable on macOS, migrated to internal (slower but stable)
- Time-sensitive queries hallucinate even with web search

Includes full benchmarks, failure cases, and honest evaluation of when this approach is / isn't worth it.

---

## Post-posting checklist

Before posting:
- [ ] Repo README is polished
- [ ] License is clear (MIT)
- [ ] No sensitive info in any committed file
- [ ] Links all work
- [ ] Screenshots added if possible (increases engagement)

Posting tips:
- Post Tuesday-Thursday morning Pacific Time for max engagement
- Reddit: r/LocalLLaMA primary, crosspost to r/apple, r/MachineLearning if well-received
- HN: submit late Monday or Tuesday morning PT
- Respond to comments quickly (first 2 hours determine visibility)

Expected engagement:
- r/LocalLLaMA: 50-200 upvotes if well-timed, 100-500 comments
- HN: 20-100 upvotes, 50-200 comments if it hits front page
- GitHub stars: 10-50 first week, possibly more if viral

Don't expect viral. Expect "useful reference for people searching MoE + Mac Silicon".
