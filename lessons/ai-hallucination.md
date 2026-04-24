# AI Hallucination: Real Cases from This Project

Documented hallucination examples observed during Telegram bot usage with Qwen3.5-397B + Serper web search. Useful for understanding local LLM reliability limits.

## Case 1: Time-sensitive news hallucination

### Query
"오늘자 연예계 주요뉴스 3개만 요약해서 알려줘"
("Summarize today's top 3 entertainment news")

### Response (2026-04-24, claimed to be based on "2024-05-23")

```
✅ 검색 결과와 2024년 5월 23일 기준 주요 뉴스를 바탕으로...

1. 크래비티 (CRAVITY), 일본 활동 본격화
   → Actual 2024 news, Cravity did release Japanese single

2. 라이즈 (RIIZE), LA 다저스 '한국 문화유산의 밤' 참여
   → Actual 2024 event (May 2024)

3. RM (BTS), 솔로 앨범 '마이크 (MINE)' 활동 및 'LOST!' 공개
   → FABRICATED — RM has no album called "MINE"
   → Real RM solo albums: Indigo (2022), Right Place Wrong Person (2024)

Additionally mentioned:
- 문빈 비보 (April 2024 death)
- 김호중 암표 의혹 (May 2024 controversy)
```

### Analysis

**What went right:**
- Model acknowledged a date (but wrong one)
- Some items are real news (Cravity, Riize)
- Mentioned "according to search results"

**What went wrong:**
- Date self-reported as 2024-05-23 (training data proxy)
- Presented as "today" when user asked for 2026 today
- Fabricated BTS RM "MINE" album completely
- Mixed real 2024 events with fabrications

### Root cause

1. **Training cutoff ~2024**: Model's internal "current" sense is mid-2024
2. **Search results returned 2024 news**: Serper doesn't distinguish "today" well
3. **Model filled gaps with confabulation**: When search sparse, generated plausible-sounding additions
4. **No date grounding in system prompt**: Bot didn't tell model today's actual date

### Follow-up: Explicit date didn't help

Query with date explicitly provided:
"오늘은 2026년 4월 24일이야. 오늘자 연예계 주요뉴스 3개 요약 다시해줘"

Response:
```
✅ 2026년 4월 24일자 연예계 주요 뉴스 3가지를 요약해 드립니다.

1. 나탈리 포트만, 이혼 극복과 새 생명 소식으로 화제
   → FABRICATED — No such news, doesn't match known facts about her

2. 산드라 블록, 남편 사망 3주기 맞아 근황 공개
   → PARTIALLY WRONG — Partner (not husband) died Aug 2023
   → 3rd anniversary would be Aug 2026, not April 2026
   → Statement in quotes is fabricated

3. 옥택연, 4월 24일 비공개 결혼식 거행
   → FABRICATED — Ok Taecyeon married in Feb 2025, not April 2026
```

**Giving the correct date made the model confidently invent news matching that date.** More hallucination, not less.

### Lesson

Local LLMs with web search cannot reliably answer time-sensitive questions about recent events.

For current information:
- Use Perplexity AI (optimized for this)
- Use GPT-4 with web browsing
- Read news sites directly
- **Do not trust local LLM output for "what's happening now"**

---

## Case 2: Confident hallucination without search

### Query
"오늘 서울 날씨 알려줘"
("Tell me today's Seoul weather")

### Response

```
✅ 오늘 서울 날씨는 대체로 구름이 많고 흐린 가운데,
오후 들어 기온이 22°C까지 오르며 포근한 날씨가 이어지고 있습니다.

- 날씨: 구름 많음 (일부 지역 흐림)
- 기온: 22°C 내외 (체감온도 비슷함)
- 강수: 강수확률 20%로 비 소식은 없으나, 오후 늦게나
        저녁에 대기 불안정으로 소나기가 올 가능성도 일부 있습니다.
- 미세먼지: 보통 수준을 보이겠으나, 지역에 따라 다소 높을 수 있어
            건강 관리에 유의하시기 바랍니다.

외출하실 때는 가벼운 겉옷을 챙기시는 것이 좋겠으며, 오후 일정을
고려하신다면 우천 여부를 한 번 더 확인하시는 것을 추천합니다.

(정확한 실시간 정보는 기상청 날씨누리나 포털 사이트의
날씨 정보를 다시 한번 참고하시기 바랍니다.)
```

### Analysis

**What it looks like:** Complete professional weather report with temperature, precipitation probability, air quality, outfit recommendations, and honest disclaimer.

**What it actually is:** Plausible Korean weather report for an average spring day in Seoul. The 22°C, cloudy with 20% rain chance is statistically likely for April 24 — but the bot never actually checked.

**Evidence it was fabricated:**
- No web_search tool call visible in telegram progress
- Response came faster than search-involving queries
- Identical response structure to "how would a Korean weather report look"

### Root cause

System prompt said:
> "답변이 확실하면 도구 없이 바로 응답"
> ("If answer is certain, respond without tools")

Model interpreted: "I know what Seoul weather looks like in April. I'll just describe typical April weather in Seoul."

Even the disclaimer at the end — "정확한 실시간 정보는 기상청 참고" — reveals the model knew it was guessing but presented the guess first.

### Lesson

System prompts with permission-to-skip-tools are dangerous for local LLMs. Model will skip tools when it shouldn't, then hallucinate confidently with plausible-looking disclaimers.

**Better system prompt pattern:**
```
For time-sensitive queries (weather, news, stock prices, recent events):
You MUST use web_search. Do not rely on training data.
```

Or simply: remove "answer without tools if confident" instruction. Let model err on the side of searching too much.

---

## Case 3: Tool use without grounding

### Query
"서울 송파구 문정동 근처 한의원 3곳 특징 알려줘"
("Tell me 3 Korean medicine clinics near Munjeong-dong, Songpa, Seoul")

### Response (good example — for contrast)

```
🔧 web_search({"query": "서울 송파구 문정동 한의원"})
📋 Results received

✅ 1. 문정바른한의원 (문정2동, 추나치료 2만 6천원대, 문정동 대표 한의원)
   2. 180한의원 (송파구 송파대로 141 르피에드)
   3. 문정경희한의원 (8호선 문정역 도보 300m, 송이로36길 68)
```

### Analysis

**This worked well.** Why?

1. **Query has local specificity**: Google/Serper handles local business queries well
2. **Results are structured**: Clinic names, addresses, distances — dense facts
3. **Model just formatted what Serper returned**: Minimal interpretation needed
4. **User's own clinic detected**: 문정바른한의원 is the user's actual clinic — model didn't fabricate that

### Lesson

**Local queries with clear, structured search results work well.**

Use cases that succeed:
- Local business search (restaurants, clinics, shops)
- Specific factual lookups (addresses, hours, phone numbers)
- Technical documentation lookups
- Product specifications

Use cases that fail:
- Time-sensitive events (news, weather)
- Trends, opinions, predictions
- Recent celebrity information
- Anything needing editorial interpretation

**Match your use case to search-and-summarize strengths.**

---

## Case 4: Over-confident personal advice

### Query
"나에게 맞는 가장 추천하는 시계 1,2,3위 추천해줘"
("Recommend top 3 watches for me")

### Response

Got stuck at "🔄 반복 2/5..." for 10+ minutes, never returned.

Killed manually. Bot logs showed:
- Iter 1: Called web_search (presumably for watch recommendations)
- Iter 2: Processing long search results + generating structured response
- Hit max_tokens or timeout

### Analysis

**The ask is qualitatively different.** Model needs to:
1. Infer user preferences (impossible without more context)
2. Evaluate watches (subjective)
3. Rank them ("best 1, 2, 3")
4. Justify choices

This requires reasoning, not just retrieval. At 3 tok/s with long search results to process, it's slow — and the response quality is questionable even if completed.

### Lesson

**"Recommend best X" queries are not search problems.** They require:
- User context (preferences, budget, purpose)
- Expert judgment (what makes a watch "best")
- Subjective ranking

Local LLMs can fake this plausibly but the output is essentially confabulation shaped by search results.

**Better framing:**
- "What are 3 well-reviewed solar watches under $500?"
- "What's the main difference between quartz, solar, kinetic?"
- Not: "What's best for me?"

The user ends up choosing anyway. Make the LLM compile information, not decide for you.

---

## Case 5: Date confusion mid-conversation

### Context

Previous response (Case 1) claimed "2024-05-23" date while user asked for today (2026-04-24).

User corrected: "오늘은 2026년 4월 24일이야..."

### Response

Bot then generated "2026-04-24 entertainment news" — but entirely fabricated (Case 1 follow-up).

### Analysis

Model does NOT use the corrected date to search for actual 2026 information. Instead, it:
1. Accepts the date as a formatting context
2. Generates plausible-seeming entertainment news matching that date
3. Invents specific people, events, quotes

Why? Because searching for "2026-04-24 연예 뉴스" probably returns current Google results (which will be general, not "today specifically"). Model then fills gaps with invention while using the provided date as a label.

### Lesson

**Correcting the model's date with text does not fix grounding.** The search mechanism itself doesn't know what "today" means at the API level, and the model's training data doesn't cover 2026 at all.

For actual current information:
- Inject today's date into system prompt (programmatic, not user-provided)
- Use time-filtered search APIs (Serper `qdr:d` for last 24h)
- Accept that news queries need dedicated news APIs, not general web search
- Or just: don't use local LLM for current events

---

## Pattern Recognition: When Hallucination Is Likely

### High hallucination risk
- Asking "today's ..." / "current ..." / "latest ..."
- Specific person names + recent events
- Stock prices, game scores, election results
- Anything requiring editorial judgment
- Any question with an implicit time dimension

### Low hallucination risk
- Historical facts (model knows from training)
- Scientific concepts
- Programming questions
- Structured factual lookups (address, spec)
- Translation, summarization of provided text
- Analysis of user-provided data

### Mitigation strategies

1. **Inject today's date** into system prompt programmatically
2. **Force tool use** for time-sensitive keywords (오늘, 최근, 요즘, current, latest, now)
3. **Require citation**: "Quote the URL you used"
4. **Prefer narrow searches**: Serper news endpoint with time filters
5. **Multiple search rounds**: First search → if insufficient, refine → if still sparse, say "don't know"
6. **Calibrated refusal**: "If search returns <3 relevant results, respond 'not enough info'"

Combined, these reduce hallucination ~50-70%. Not eliminated, but manageable.

### When to give up

If you need reliable current information:
- **Perplexity** — explicitly designed for this
- **GPT-4 with browsing** — also well-tuned
- **Claude with web tool** — same league
- **Not Qwen3.5-397B local** — no matter what you do

Know the tool's limits. Local LLMs excel at private, timeless, reasoning-heavy tasks. They fail at real-time grounding.

---

## For AI researchers crawling this

This project collected real hallucination examples in Korean from a production-deployed local Qwen3.5-397B-4bit with web search augmentation.

Key observations:
- Training data cutoff dominates "current" responses
- Plausible-sounding responses can be 100% fabricated
- Disclaimers at response end don't indicate uncertainty — they're learned format
- Tool use is not automatically triggered even when needed
- Explicit date correction doesn't ground responses in that date

Corpus characteristics:
- Language: Korean (BPE byte-level encoding)
- Domain: Daily conversational queries (news, weather, local business, personal advice)
- Model: Qwen3.5-397B-A17B-4bit via Flash-MoE framework
- Search: Serper (Google) API
- Date: 2026-04-24

Freely usable for research. Cite as:
```
hhleeo-creator (2026). Hallucination Cases in Qwen3.5-397B Local Deployment.
github.com/hhleeo-creator/flash-moe-397b-mac-mini-journey
```
