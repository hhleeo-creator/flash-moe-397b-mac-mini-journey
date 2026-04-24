# Phase 9.3-9.4: Custom Agent Design (Simple + Web Agent)

**Date**: 2026-04-24 (late morning - early afternoon)
**Duration**: ~2 hours
**Outcome**: 140-line agent that works; web search integration

## Context: why not use a framework

Phase 9.2 investigated [Hermes Agent](https://github.com/NousResearch/hermes-agent). Outcome: 13,859-token default system prompt = 50+ minutes per turn on our local LLM. See `lessons/what-failed.md#2`.

Decision: Write our own minimal agent.

## Design goals

1. **Short system prompt** (<1000 tokens)
2. **Simple tool calling** (basic OpenAI spec)
3. **Debuggable** (all logic visible)
4. **Extensible** (easy to add tools)
5. **Callback support** (for UIs like Telegram)

## simple_agent.py (first version)

### Design

```python
from openai import OpenAI
import subprocess
import json

client = OpenAI(base_url="http://127.0.0.1:8771/v1", api_key="local-dummy")

SYSTEM_PROMPT = """당신은 유용한 한국어 AI 비서입니다.
필요시 bash 명령을 사용해 시스템 작업을 수행할 수 있습니다.
한국어로 명확하게 답변하세요."""

TOOLS = [{
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute bash command",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]
        }
    }
}]

def run_agent(goal, max_iterations=5, max_tokens=500):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": goal}
    ]

    for i in range(max_iterations):
        print(f"\n── Iteration {i+1}/{max_iterations} ──")
        resp = client.chat.completions.create(
            model="qwen3.5-397b-a17b",
            messages=messages,
            tools=TOOLS,
            max_tokens=max_tokens,
            extra_body={"strip_think": True}
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                print(f"🔧 Tool: {tc.function.name}({args})")
                result = execute_tool(tc.function.name, args)
                print(f"📋 Result: {result[:200]}")

                messages.append({
                    "role": "assistant",
                    "tool_calls": [tc.model_dump()]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result
                })
        else:
            print(f"\n✅ Final: {msg.content}")
            return msg.content

    return "[Max iterations]"
```

140 lines with utility functions and CLI argparse.

### First test

```bash
python simple_agent.py "현재 디렉토리의 파일 개수를 세어서 알려주세요"
```

Output:
```
── Iteration 1/5 ──
🔧 Tool: bash({'command': 'ls -1 /Users/migi/.flashmoe/agent | wc -l'})
📋 Result: 1

── Iteration 2/5 ──

✅ Final: 현재 디렉토리(/Users/migi/.flashmoe/agent)의 파일 개수는 1개입니다.
```

5 minutes total, 2 iterations, correct answer.

**Works.**

## Problem: wrapper bug with tool call args

First attempt had issue. Qwen3.5's chat template expects tool call arguments as dict:

```jinja
{%- for item in tool_call.arguments|items %}
```

But OpenAI SDK passes them as JSON string:

```python
tool_calls[0].function.arguments = '{"command": "ls -l"}'
```

Qwen template crashed: `items` filter on string.

### Fix in qwen_template.py

Added normalization:

```python
def _normalize_tool_call_args(tool_calls):
    """Convert OpenAI JSON string args to dict for Qwen template."""
    for tc in tool_calls:
        args = tc.get('function', {}).get('arguments')
        if isinstance(args, str):
            try:
                tc['function']['arguments'] = json.loads(args)
            except json.JSONDecodeError:
                tc['function']['arguments'] = {}
    return tool_calls
```

Applied before template rendering. Fixes iteration 2 that was failing with 500 error.

### Lesson from this

**Protocol mismatches are subtle.** OpenAI SDK and Qwen template both "handle tool calls" but data types differ (string vs dict). Check assumptions at boundaries.

## web_agent.py (extended version)

### Design

Extends simple_agent with:
- Web search tool (Serper)
- URL fetch tool (trafilatura)
- Enhanced callback API for UI integration

### Tool definitions

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Google 웹 검색. 최신 정보나 확실하지 않은 사실을 찾을 때.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "num": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "특정 URL의 본문을 가져옴. 상세 내용이 필요한 페이지에.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 3000}
                },
                "required": ["url"]
            }
        }
    }
]
```

### Callback API

For Telegram bot integration:

```python
def run_agent(goal, max_iterations=5, max_tokens=800,
              verbose=True, on_step=None):
    # ... loop

    if on_step:
        on_step("iteration_start", {"i": i+1, "max": max_iterations})
        # ... tool_call, tool_result, final, error events
```

Telegram bot registers callback to show progress:

```python
def on_step(step_type, data):
    if step_type == "tool_call":
        text = f"🔧 {data['name']}(...)"
    elif step_type == "tool_result":
        text = f"📋 {data['name']} 완료"
    # Update Telegram message
    status_msg.edit_text(text)
```

### System prompt evolution

Initial:
```
당신은 유용한 한국어 AI 비서입니다.
도구 사용 원칙:
- 최신 정보나 확실치 않은 사실이 필요하면 web_search로 검색
- 답변이 확실하면 도구 없이 바로 응답
```

**Problem detected**: Model over-interpreted "답변이 확실하면 도구 없이" as permission to skip search and hallucinate.

After testing hallucination cases, considered upgraded version:

```python
def get_system_prompt():
    today = datetime.now().strftime("%Y년 %m월 %d일")
    return f"""당신은 한국어 AI 비서입니다.

오늘 날짜: {today}

절대 규칙:
1. 훈련 데이터는 2024년까지만. 2024년 이후 정보는 모름.
2. 현재 시점 정보(뉴스, 날씨, 주가)는 반드시 web_search
3. 검색 결과에 명시적으로 없는 정보는 답변하지 말 것
4. 검색 결과가 부족하면 "검색 결과에서 확인할 수 없습니다" 솔직히 말할 것

환각 방지:
- 구체적인 날짜, 사람 이름, 사건을 검색 없이 지어내지 말 것
- 불확실한 정보는 "확실하지 않다"고 솔직히 말할 것
"""
```

*Note: This improved prompt was designed but not fully deployed within the 2-day timeline. Scheduled for follow-up work.*

## Tool implementation details

### web_search tool

See `code/agent/tools/web_search.py`.

Key features:
- urllib-only (no extra dependencies)
- API key loaded from `~/.env` or `~/.openclaw/.env` at runtime
- Key never logged or exposed in error messages
- Results structured for LLM consumption (title + URL + snippet)

### fetch_url tool

Uses `trafilatura` for article extraction:

```python
import trafilatura

def fetch_url(url, max_chars=3000):
    downloaded = trafilatura.fetch_url(url, no_ssl=True)
    content = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        favor_precision=True
    )
    return content[:max_chars] + ("..." if len(content) > max_chars else "")
```

`trafilatura` handles HTML stripping, ad removal, article extraction better than manual regex.

### bash tool

Simple subprocess wrapper:

```python
def bash(command):
    try:
        result = subprocess.run(
            command, shell=True,
            capture_output=True, text=True, timeout=30
        )
        return (result.stdout or result.stderr)[:2000]
    except subprocess.TimeoutExpired:
        return "[Timeout 30s]"
```

- 30-second timeout prevents runaway commands
- Output limited to 2000 chars (LLM context window)
- Stderr captured if stdout empty

## Testing

### Test 1: Common knowledge (no search expected)

```
python web_agent.py "대한민국의 수도는 어디입니까?"
```

Result: 3m 32s, no tool calls, correct answer. ✓

### Test 2: Time-sensitive (search expected)

```
python web_agent.py "2026년 4월 현재 대한민국 대통령은 누구입니까?"
```

Result: 11 minutes, 1 search call, but **hallucinated** (search returned sparse results, model filled with 2024 data). ⚠

### Test 3: Local business (search expected, high success)

```
python web_agent.py "서울 송파구 문정동 근처 한의원 3곳"
```

Result: 30 minutes (2 iterations), correct results including user's own clinic. ✓

### Test 4: Watch recommendation

```
python web_agent.py "나에게 맞는 정확한 시계 추천 TOP 3"
```

Result: 11 minutes, structured response with solar watch recommendations (Citizen Eco-Drive, Seiko Solar). ✓

## Comparison to Hermes

| Metric | Hermes Agent | simple_agent + web_agent |
|---|---|---|
| System prompt tokens | 13,859 | 356-450 |
| Time per turn (local 397B) | 50+ min | 2-10 min |
| Lines of code (ours) | 100k+ framework | 250 total |
| Tool count | 14 | 3 |
| Customizability | Low (config-only) | High (edit .py directly) |
| Debugging | Hard (deep stack) | Easy (all visible) |

For local LLM deployment, 100x simpler = 100x more usable.

## Extension patterns

### Adding a new tool

1. Define in TOOLS list:
```python
{
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "What it does",
        "parameters": {...}
    }
}
```

2. Add to execute_tool():
```python
if name == "my_tool":
    return my_tool(args["param"])
```

3. Implement the function.

That's it. Add to list, handle in dispatcher, implement. ~30 lines.

### Adding memory/state

Current agents are stateless (each call fresh). To add persistence:

```python
class MemoryAgent:
    def __init__(self):
        self.history = []

    def run(self, goal):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self.history,
            {"role": "user", "content": goal}
        ]
        result = run_loop(messages)
        self.history.append({"role": "user", "content": goal})
        self.history.append({"role": "assistant", "content": result})
        return result
```

Simple in-memory history. For persistence: pickle to disk between calls.

### Adding multi-agent

Orchestrator pattern:

```python
def researcher(goal):
    return run_agent(goal, system="You are a researcher...")

def writer(research):
    return run_agent(f"Write based on: {research}",
                     system="You are a writer...")

def orchestrate(task):
    research = researcher(task)
    draft = writer(research)
    return draft
```

Each specialist has minimal prompt. Combine for complex workflows.

## Files

- `code/agent/simple_agent.py` — basic bash-only agent
- `code/agent/web_agent.py` — with web search + URL fetch
- `code/agent/tools/web_search.py` — Serper integration
- `code/agent/tools/__init__.py` — package marker

## Lessons

1. **Small beats large** for local LLM agents
2. **Protocol mismatches at boundaries** are common (fix, don't fight)
3. **System prompt engineering matters** more than model size for grounding
4. **Callback APIs** decouple core logic from UI
5. **Direct stdlib** preferred over heavy SDKs
