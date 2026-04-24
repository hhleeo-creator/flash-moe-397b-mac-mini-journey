# Phase 8: OpenAI-Compatible Wrapper

**Date**: 2026-04-23 (evening)
**Duration**: 30 minutes (expected 8 hours)
**Outcome**: 45/45 tests passed

## Why build this

Flash-MoE's native HTTP interface is minimal:
- Simple prompt in, tokens out
- Byte-level BPE output (looks like `Ġhello` before decode)
- Qwen-specific tool call format (`<tool_call>...</tool_call>` XML)
- No support for OpenAI SDKs, LangChain, etc.

To integrate with existing tools, need OpenAI-compatible API.

## Architecture

```
┌─────────────────┐
│  OpenAI SDK     │  ← Python, JS, any OpenAI client
│  or curl        │
└────────┬────────┘
         │ HTTP POST /v1/chat/completions
         │ {model, messages, tools, stream, ...}
         ▼
┌─────────────────┐
│  wrapper :8771  │  ← FastAPI + uvicorn
│  server.py      │
└────────┬────────┘
         │
         ├─ Apply Qwen chat template (Jinja2)
         ├─ Normalize tool_call arguments (JSON→dict)
         ├─ Forward to infer server
         │
         ▼
┌─────────────────┐
│  infer :8000    │  ← Flash-MoE native HTTP
│  ./infer --serve│
└────────┬────────┘
         │
         ├─ Raw token generation (with BPE IDs)
         │
         ▼
┌─────────────────┐
│  wrapper        │
│  (response side)│
└────────┬────────┘
         │
         ├─ Decode byte-level BPE → UTF-8
         ├─ Parse tool call XML → OpenAI JSON
         ├─ Strip <think>...</think> if strip_think=true
         ├─ Stream SSE if requested
         │
         ▼
  OpenAI-format response
```

## Implementation

### Files

```
~/.flashmoe/flash-moe/wrapper/
├── server.py           # FastAPI app (main)
├── bpe_decode.py       # Byte-level BPE → UTF-8
├── qwen_template.py    # Jinja2 chat template
├── tool_parser.py      # XML → OpenAI JSON
├── think_stripper.py   # <think>...</think> removal
├── infer_client.py     # HTTP client for Flash-MoE
├── models.py           # Pydantic schemas (OpenAI spec)
└── tests/              # 45 test cases
```

### Endpoints

- `POST /v1/chat/completions` — OpenAI standard
- `GET /v1/models` — List available models
- `GET /health` — Health check
- `GET /` — Service info

### Qwen chat template

Qwen3.5's tokenizer.json includes a chat_template field (Jinja2). Wrapper renders it:

```python
from jinja2 import Template

with open("chat_template.jinja") as f:
    template = Template(f.read())

rendered = template.render(
    messages=messages,
    tools=tools,
    add_generation_prompt=True
)
```

Output looks like:
```
<|im_start|>system
You are a helpful assistant.
<|im_end|>
<|im_start|>user
Hello
<|im_end|>
<|im_start|>assistant
```

Pass this to Flash-MoE as raw prompt.

### Byte-level BPE decode

Qwen3.5 (and many GPT-derived tokenizers) use byte-level BPE. Output tokens decode to intermediate representation like `Ġhello` (where `Ġ` = space prefix).

```python
def decode_tokens(tokens):
    # Each token ID → bytes
    byte_pieces = [tokenizer_decode(t) for t in tokens]
    # Concatenate
    raw = "".join(byte_pieces)
    # Unicode → original bytes
    bytes_array = bytes([unicode_to_byte(c) for c in raw])
    # Decode UTF-8
    return bytes_array.decode("utf-8", errors="replace")
```

Handles multi-byte characters (Korean, Chinese) correctly.

### Tool call XML parsing

Qwen3.5 generates:

```xml
<tool_call>
{"name": "web_search", "arguments": {"query": "Seoul weather"}}
</tool_call>
```

Convert to OpenAI format:

```json
{
  "tool_calls": [{
    "id": "call_abc123",
    "type": "function",
    "function": {
      "name": "web_search",
      "arguments": "{\"query\": \"Seoul weather\"}"
    }
  }]
}
```

Note: OpenAI spec requires `arguments` as JSON string, not dict. Adapter handles this.

### Tool call args normalization (bug fix)

Issue: OpenAI SDK sends `arguments` as JSON string, Qwen template expects dict.

Fix in `qwen_template.py`:

```python
def _normalize_tool_call_args(messages):
    for msg in messages:
        if "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                args = tc.get("function", {}).get("arguments")
                if isinstance(args, str):
                    tc["function"]["arguments"] = json.loads(args)
    return messages
```

Before template rendering, convert all tool_call args strings to dicts.

### Strip think blocks

Qwen3.5 sometimes generates:

```
<think>
Let me analyze this carefully...
The user wants...
</think>
Actually, the answer is: Seoul.
```

With `strip_think=true` (Anthropic-specific extension), wrapper removes `<think>...</think>` blocks before returning:

```python
import re

def strip_think(text):
    return re.sub(
        r"<think>.*?</think>\s*",
        "",
        text,
        flags=re.DOTALL
    )
```

### Streaming (SSE)

OpenAI streaming uses Server-Sent Events:

```
data: {"choices": [{"delta": {"content": "Hello"}}]}

data: {"choices": [{"delta": {"content": " world"}}]}

data: [DONE]
```

Wrapper forwards Flash-MoE's streaming tokens as SSE:

```python
async def stream_response(request):
    async for token in infer_client.stream(prompt):
        yield f"data: {json.dumps(format_delta(token))}\n\n"
    yield "data: [DONE]\n\n"
```

Works with OpenAI SDK's `stream=True` parameter.

## Testing

### Test structure

45 tests across 3 files:

**tests/test_basic.py** (12 tests)
- Chat completion basic
- System prompt handling
- Multi-turn conversation
- Max tokens limit
- Temperature variation
- Stop tokens

**tests/test_tools.py** (11 tests)
- Single tool call
- Tool result roundtrip
- Multiple tools in one turn
- No tool call case
- Malformed arguments handling

**tests/test_streaming_sdk.py** (22 tests)
- Stream flag honored
- SSE format correct
- Token-by-token delivery
- OpenAI SDK compatibility
- Abort handling

### Korean text test

Real Korean ad copy generation:

```python
resp = client.chat.completions.create(
    model="qwen3.5-397b-a17b",
    messages=[
        {"role": "system", "content": "당신은 한의원 마케팅 전문가입니다."},
        {"role": "user", "content": "목 어깨 허리 통증 한의원 광고 문구 3개 만들어주세요."}
    ]
)
```

Result: 3 natural Korean ad copies, grammatically correct, stylistically appropriate. **Verified by Korean native speaker.**

### All tests passed

```
tests/test_basic.py: 12/12 PASS
tests/test_tools.py: 11/11 PASS
tests/test_streaming_sdk.py: 22/22 PASS
Total: 45/45 PASS (100%)
```

## Why it was fast

Budget: 8 hours. Actual: 30 minutes.

Reasons:
1. **Clear spec** (OpenAI API is well-documented)
2. **Focused scope** (only chat completions, not fine-tuning etc.)
3. **Leveraged libraries** (FastAPI, Jinja2, openai SDK for tests)
4. **Incremental** (built endpoint → tested → added next feature)
5. **Already knew Qwen format** (from Phase 4 tokenizer work)

## Design lessons

### Why separate wrapper from infer?

Option A: Modify Flash-MoE's C code to output OpenAI format.
Option B: Put wrapper in Python, leave Flash-MoE alone.

Chose B:
- Flash-MoE is C, wrapper can be Python (faster iteration)
- Separation of concerns (inference vs API spec)
- Can update wrapper without rebuilding C
- Can swap to different OpenAI-compat client later
- Flash-MoE stays pure

### Why FastAPI (not Flask)?

- Native async support (needed for streaming)
- Automatic OpenAPI docs
- Pydantic integration (schema validation)
- Production-ready
- Fast

Flask would've worked but with more boilerplate.

### Why Jinja2 for chat template?

- Qwen's template is already Jinja2 format
- Rendering is complex (loops, conditionals for tools)
- Writing our own parser = waste of time
- Jinja2 is rock solid

### Why uvicorn?

- Fast ASGI server
- Works with FastAPI out of the box
- Easy integration with tmux (single command)

## Operational

### Running

```bash
cd /Users/migi/.flashmoe/flash-moe/wrapper
/Users/migi/flashmoe_venv/bin/python -m uvicorn server:app \
  --port 8771 --host 0.0.0.0
```

Binds all interfaces (0.0.0.0) for LAN access. Use 127.0.0.1 for localhost only.

### Testing it works

```bash
# Basic chat
curl -X POST http://localhost:8771/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5-397b-a17b","messages":[{"role":"user","content":"안녕"}],"max_tokens":100}'

# With OpenAI SDK
python -c "
from openai import OpenAI
c = OpenAI(base_url='http://127.0.0.1:8771/v1', api_key='x')
r = c.chat.completions.create(
    model='qwen3.5-397b-a17b',
    messages=[{'role':'user','content':'안녕'}]
)
print(r.choices[0].message.content)
"
```

### Logs

```bash
tail -f /Users/migi/flashmoe_logs/wrapper.log
```

Shows:
- Incoming requests
- Forwarded prompts (debug mode)
- Response times
- Errors

### Performance overhead

Wrapper adds ~50-100ms per request:
- Template rendering: ~20ms
- HTTP forwarding: ~20ms
- Response processing: ~30ms

Negligible compared to Flash-MoE's seconds of generation.

## Limitations

### What's supported
- ✓ Chat completions (streaming and not)
- ✓ Tool calling (function calling)
- ✓ Multi-turn conversations
- ✓ System prompts
- ✓ max_tokens, temperature, top_p
- ✓ stop tokens
- ✓ strip_think (our extension)

### What's NOT supported
- ✗ Embeddings endpoint
- ✗ Fine-tuning
- ✗ Audio/Whisper
- ✗ Image generation
- ✗ Function parallel execution (OpenAI's newer feature)
- ✗ Vision (text-only)

Qwen3.5-397B text-only means most OpenAI modalities not applicable anyway.

## For future enhancement

- [ ] Add `/v1/embeddings` (if Qwen supports embedding extraction)
- [ ] Rate limiting (multi-user protection)
- [ ] API key authentication (currently "local-dummy" accepts anything)
- [ ] Prometheus metrics export
- [ ] Request caching for repeated queries
- [ ] Parallel tool call support

## Files

- `code/wrapper/server.py` — Main FastAPI app (not in repo yet, original lives in `~/.flashmoe/flash-moe/wrapper/`)

## Lessons

1. **OpenAI API is a lingua franca** — implementing it unlocks all tools
2. **FastAPI + Python for API wrappers** — fast to iterate
3. **Separate wrapper from compute** — different languages for different concerns
4. **Test with real SDK** — not just curl — catches subtle compatibility issues
5. **30 minutes or 8 hours?** — clear spec + good libraries = order of magnitude faster
