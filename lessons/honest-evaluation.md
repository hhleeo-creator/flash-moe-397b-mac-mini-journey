# Honest Evaluation: Is This Worth It?

Written after 25 hours of work and several weeks of real use.

## The Bottom Line

**For most people: no.**

Cloud APIs (GPT-4o-mini, Claude Haiku, Gemini Flash) will:
- Be 10-100x faster
- Cost less than $20/month for normal use
- Not require SSD babysitting
- Not hallucinate as aggressively on recent events

**For some people: yes.**

- Medical/legal professionals handling data that can't leave premises
- Developers learning MoE internals hands-on
- Enthusiasts treating it as hobbyist infrastructure
- Anyone in regions with unreliable/expensive API access

## What I Actually Use This For

After building it, realistic uses:

| Use Case | Verdict |
|---|---|
| Quick questions | ❌ Too slow (3 min for "안녕") |
| Real-time chat | ❌ Impossible |
| Code generation | ❌ Cursor/Claude Code is 10x faster |
| News summarization | ❌ Hallucinates time-sensitive info |
| Technical writing | ⚠️ Works but GPT-4 is smoother |
| Korean translation | ⚠️ Good quality, slow |
| Private medical notes | ✓ **The actual value** |
| Learning MoE architecture | ✓ Hands-on understanding |
| Overnight batch tasks | ✓ Run while sleeping |
| Bragging rights | ✓ "I run 397B locally" |

## The Privacy Angle Is Real

This is where local 397B genuinely has no substitute.

As a Korean medicine clinic operator, I handle:
- Patient interview transcripts
- Symptom descriptions with personal context
- Treatment records

Cloud APIs technically allow this but legally ambiguous under Korean medical privacy law. Local processing is:
- Definitively compliant
- No audit trail on external systems
- No data retention concerns

This alone justifies the hardware for practitioners in similar regulated fields.

## The Hallucination Problem Is Also Real

Tested during development:

Query: "Top 3 entertainment news today"
Response: Confidently invented 3 news items, dated them "today", mixed 2024 information with fabricated events.

Query: "Current President of Korea"
Response: Hallucinated an incorrect answer when search results were sparse.

Qwen3.5-397B has the raw intelligence of a GPT-4-class model but lacks the grounding/honesty training of commercial models. **It will confabulate rather than admit ignorance.**

Prompt engineering helps. Retrieval grounding helps. But it never reaches the reliability of production LLMs.

## Speed Math

Realistic throughput calculations for Telegram bot:

| Content Length | Best Case | Typical |
|---|---|---|
| 100 Korean chars | 25 sec | 45 sec |
| 500 Korean chars | 2 min | 3-4 min |
| 1500 Korean chars (blog draft) | 6 min | 10-15 min |
| 3000 Korean chars (long article) | 12 min | 25-30 min |

These are **total times including prefill**. First generation is much slower because of 190ms/token prefill.

If you need:
- Under 10 seconds: Use cloud API
- Under 1 minute: Use cloud API (usually)
- 1-5 minutes: Either works
- 5+ minutes acceptable: Local viable
- Overnight batches: Local wins (no rate limits)

## What "Agent" Means in Practice

Marketing term "AI agent" usually implies:
- Acts autonomously
- Completes tasks while you sleep/work
- Makes real-time decisions

Reality at 3-5 tok/s:
- Each "thought" takes 30 seconds
- 5-iteration agent loop = 15+ minutes
- Any real-time interaction: painful
- Useful for: slow, deliberate, high-value tasks only

## Hardware Was the Easiest Part

Despite being the big expense, hardware worked fine:
- Mac Mini M4 Pro: no issues
- 64GB RAM: comfortable margin
- Internal SSD: reliable, adequate speed

What caused pain:
- External SSD detachment (macOS Sandbox + TB5 enclosure)
- Flash-MoE's quirky cache behavior (never tune)
- Framework incompatibility (Hermes Agent)
- Hallucination even with web search
- Debugging unfamiliar Metal shader paths

**80% of time was software, not hardware.**

## Should You Do This?

### Yes if:
- [ ] You have genuine privacy requirements (medical, legal, financial)
- [ ] You want to deeply understand MoE architecture
- [ ] You have $500+ to spend on SSD + enclosure
- [ ] You tolerate 3-5 tok/s as "fast enough"
- [ ] You're willing to lose 25+ hours to setup
- [ ] You have 64GB+ RAM and fast SSD

### No if:
- [ ] You want a ChatGPT alternative for daily use
- [ ] You need real-time conversation
- [ ] Your use case is non-sensitive (just use Claude/GPT)
- [ ] You're unwilling to debug obscure errors
- [ ] Hardware budget is tight (Claude API is cheaper)

### Maybe if:
- [ ] You're curious and have time to experiment
- [ ] You want to prepare for future models (knowledge transfers)
- [ ] You enjoy hobbyist infrastructure projects

## The Real Winner Here

Not this specific setup. The real winner is **knowing the technology**.

Six months from now:
- Better models (Qwen 4? Llama 5? DeepSeek R3?)
- Better hardware (M5 Ultra?)
- Better frameworks (MLX 2.0?)

The experience of debugging Flash-MoE, understanding MoE quantization, building custom agents — that transfers. This specific 397B setup may be obsolete by 2027.

**Treat the investment as education, not infrastructure.** That framing makes every hour worth it.

## Final Thought

I'd do it again. Not because of practical utility — Claude and GPT serve me better daily. But because I now understand, in my hands, what it takes to run a frontier-scale model on consumer hardware. That's worth something, even if I can't quantify what.

If you're considering this project with the same mindset: welcome. The water's deep but the view is worth it.
