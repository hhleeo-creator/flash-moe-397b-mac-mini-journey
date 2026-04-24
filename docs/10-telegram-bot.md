# Phase 9.5: Telegram Bot Integration

**Date**: 2026-04-24 (afternoon)
**Duration**: ~45 minutes
**Outcome**: Working personal assistant via Telegram

## Why Telegram

Chose Telegram over alternatives:

| Option | Verdict |
|---|---|
| Web UI | Need to build, host, secure. Weeks of work. |
| Discord bot | Setup complex, fewer Korean users, more noise |
| SMS (Twilio etc.) | Paid per message, limited formatting |
| **Telegram** | Free, global, simple API, good Korean support |
| iMessage | Locked to Apple, no bot API |
| WhatsApp | API requires business verification, more friction |

Telegram won on: free, simple, good Korean support, 5-minute bot creation via @BotFather.

## Bot creation (one-time, manual)

1. Open Telegram, chat with `@BotFather`
2. `/newbot`
3. Bot name: "My Flash-MoE Assistant" (display name)
4. Username: must end with `_bot` (e.g., `QWEN397_AG_bot`)
5. Receive token (keep secret, looks like `12345:ABC...`)

Get user_id:
1. Chat with `@userinfobot`
2. `/start`
3. Note your user ID (number like `8380114442`)

## Security: `.env` file

```bash
# /Users/migi/.flashmoe/telegram/.env (perm 600)
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_ALLOWED_USER_ID=your_user_id
```

```bash
chmod 600 /Users/migi/.flashmoe/telegram/.env
```

**Never commit this file to git.** Add `telegram/.env` to `.gitignore`.

## Implementation

### Dependencies

```bash
pip install python-telegram-bot
```

Version: `python-telegram-bot >= 21.x` (async API).

### Core structure

```python
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

# Load credentials
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID"))

def is_authorized(update):
    return (update.effective_user and
            update.effective_user.id == ALLOWED_USER_ID)
```

### Handler pattern

```python
async def cmd_start(update, context):
    if not is_authorized(update):
        await update.message.reply_text("접근 권한이 없습니다.")
        return
    await update.message.reply_text(
        "🤖 Flash-MoE 397B Agent\n"
        "질문을 보내주세요."
    )

async def cmd_status(update, context):
    if not is_authorized(update):
        return
    # Check infer and wrapper health
    status = []
    try:
        urllib.request.urlopen("http://localhost:8000/health", timeout=3)
        status.append("✅ infer: OK")
    except:
        status.append("❌ infer: DOWN")
    # ... same for wrapper
    await update.message.reply_text("\n".join(status))

async def handle_message(update, context):
    if not is_authorized(update):
        return  # silent ignore

    goal = update.message.text
    status_msg = await update.message.reply_text("🤔 생각 중...")

    # Run agent in thread
    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(
        None,
        lambda: run_agent(goal, on_step=make_callback(status_msg, loop))
    )

    # Send result (chunk if > 4000 chars)
    if len(answer) <= 4000:
        await update.message.reply_text(f"✅ {answer}")
    else:
        for i in range(0, len(answer), 4000):
            chunk = answer[i:i+4000]
            prefix = "✅ " if i == 0 else "(계속) "
            await update.message.reply_text(f"{prefix}{chunk}")
```

### Progress updates (callback)

Without progress updates, user sees "🤔 생각 중..." for 10+ minutes with no indication of progress.

```python
def make_callback(status_msg, loop):
    state = {"last_text": ""}

    def on_step(step_type, data):
        if step_type == "iteration_start":
            text = f"🔄 반복 {data['i']}/{data['max']}..."
        elif step_type == "tool_call":
            name = data.get("name", "?")
            args = data.get("args", {})
            text = f"🔧 도구: {name}({str(args)[:100]})"
        elif step_type == "tool_result":
            text = f"📋 도구 실행 완료: {data.get('name', '?')}"
        else:
            return  # final answer handled separately

        # Avoid duplicate updates (Telegram rate limit)
        if text != state["last_text"]:
            state["last_text"] = text
            try:
                asyncio.run_coroutine_threadsafe(
                    status_msg.edit_text(text), loop
                )
            except:
                pass  # rate limit, ignore

    return on_step
```

### Main loop

```python
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True  # ignore queued old messages on restart
    )
```

## Design decisions

### Why async + thread executor

Telegram bot MUST be responsive to new messages. But `run_agent()` is blocking (HTTP calls, waits minutes for LLM).

Solution: run agent in thread, bot polling stays async:

```python
loop = asyncio.get_event_loop()
answer = await loop.run_in_executor(None, blocking_function)
```

Thread pool handles blocking call. Async loop continues polling.

Without this: bot freezes for 10 minutes per query, can't respond to anything else.

### Why drop_pending_updates

On restart, Telegram's update queue might have old messages (sent while bot was down). Default: process them all.

Problem: if bot was down for hours and 20 messages queued, bot processes them in sequence (200+ minutes total).

Fix: `drop_pending_updates=True` skips queued messages on startup. Only new messages processed.

### Why edit_text instead of send_text

For progress:
- `send_text` creates new message each time (spammy, 20+ messages per query)
- `edit_text` updates existing "status" message (clean, 1 message)

Telegram allows editing messages within 48 hours.

### Why silent ignore for unauthorized

When unknown user messages bot:
- Option A: Reply "not authorized"
- Option B: Silently ignore

Chose B:
- No confirmation bot exists (less attack surface)
- No load from scripted abuse
- Log for audit if needed

Trade-off: real user accidentally using wrong account gets no feedback. Acceptable for personal bot.

## Running the bot

### Development (foreground)

```bash
/Users/migi/flashmoe_venv/bin/python /Users/migi/.flashmoe/telegram/bot.py
```

See logs live. Ctrl+C to stop.

### Production (tmux)

```bash
bash /Users/migi/.flashmoe/bin/start_bot.sh
```

Starts in detached tmux session `telegram_bot`.

Inspect:
```bash
tmux attach -t telegram_bot
# Ctrl+B, D to detach without killing
```

### Integrated with full stack

```bash
bash /Users/migi/.flashmoe/bin/start_all.sh
```

Starts infer + wrapper + bot together.

## Testing results

### Session 1 (2026-04-24 11:43 - 12:01)

Queries:
1. `/status` → Instant response, "✅ OK"
2. "안녕하세요" → 3 min, "안녕하세요! 무엇을 도와드릴까요?"
3. "대한민국 수도는?" → 5 min, "서울입니다."
4. "오늘 서울 날씨 알려줘" → 10 min, full weather report with web search

**All worked.** Korean natural, responses useful.

### Session 2 (2026-04-24 afternoon)

Watch recommendation query:
- "나에게 맞는 정확한 시계 1,2,3위 추천" → 11 min, structured top 3 with brand suggestions

Also tested hallucination cases (see `lessons/ai-hallucination.md`):
- News query failed (training data leaked)
- Weather query succeeded but didn't actually use search

## Failure modes observed

### 1. Response cutoff at max_tokens

```
...10 년 이상 배터리 교체 없이도 사용 가능한 모델이
```

Sentence incomplete. Korean at 800 max_tokens ≈ 400-530 chars. Structured responses easily exceed.

**Fix**: raise max_tokens in web_agent (not done in this session, scheduled).

### 2. "반복 2/5" stuck

One query hung at iteration 2 for 14+ minutes. Likely:
- Long prefill (accumulated context + search results)
- Or infra in flight (previous request not finished)

**Diagnosis**: check `tail /Users/migi/flashmoe_logs/infer_serve.log` for active generation.

**If stuck**: restart bot (`tmux kill-session -t telegram_bot` → `start_bot.sh`).

### 3. Tool result too long

Some URL fetches returned 5000+ chars. Embedded in next prefill = 2000+ additional tokens = 6+ minutes extra.

**Mitigation**: web_search.py limits fetch_url to 3000 chars by default.

## Message formatting tips

### Markdown

Telegram supports Markdown V2 but has escaping quirks. Safer: plain text.

Used:
- `✅` for final answer
- `🔧` for tool call
- `📋` for tool result
- `🔄` for iteration
- `🤔` for "thinking"

Emoji communicates visual state without markdown complexity.

### Length

Telegram max message: 4096 chars.

Chunking:
```python
for i in range(0, len(answer), 4000):
    chunk = answer[i:i+4000]
    prefix = "✅ " if i == 0 else "(계속) "
    await update.message.reply_text(f"{prefix}{chunk}")
```

4000 (not 4096) leaves room for prefix + safety margin.

## Operational notes

### Viewing recent queries

```bash
tail -f /Users/migi/flashmoe_logs/telegram_bot.log
```

Each query logged as:
```
2026-04-24 12:01:23 - INFO - query from 8380114442: 오늘 서울 날씨 알려줘
```

### Checking if bot is alive

```bash
# Process check
pgrep -f telegram/bot.py

# Or via tmux
tmux ls | grep telegram

# Or via Telegram API
source /Users/migi/.flashmoe/telegram/.env
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"
```

### Restarting after code changes

```bash
tmux kill-session -t telegram_bot
bash /Users/migi/.flashmoe/bin/start_bot.sh
```

~5 seconds. Bot back up.

## Security review

- ✅ Token in .env, permissions 600
- ✅ user_id whitelist (silent ignore others)
- ✅ No token in logs
- ✅ No user data forwarded to external APIs (except Serper for searches)
- ✅ drop_pending_updates prevents stale command replay
- ⚠️ No rate limiting (not needed for single user)
- ⚠️ No encryption of stored conversation (Telegram handles transport; local messages in chat log)

For personal use with one authorized user, this is sufficient. For multi-user or sensitive deployments, add:
- Conversation history encryption
- Rate limiting
- Token rotation schedule
- Audit logging

## Lessons

1. **Telegram beats custom UI** for personal bot use cases
2. **Async + thread executor** essential for slow LLM backends
3. **Progress updates via edit_text** essential for UX on 10+ min responses
4. **user_id whitelist** is enough auth for single-user
5. **drop_pending_updates** prevents restart issues
6. **Emoji > Markdown** for status indicators
7. **Always test with real Telegram client** — local unit tests miss real issues (message formatting, rate limits, etc.)
