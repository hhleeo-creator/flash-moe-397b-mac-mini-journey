#!/usr/bin/env python3
"""Telegram bot wrapping Flash-MoE 397B + web_agent.

- user_id whitelist (master only)
- progress updates during long-running generation
- web_agent.run_agent() integration via on_step callback
- token + allowed_user_id loaded from ~/.flashmoe/telegram/.env (never logged)
"""
from __future__ import annotations

import asyncio
import logging
import sys
import urllib.request
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Locate the web_agent module
AGENT_DIR = Path.home() / ".flashmoe" / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
from web_agent import run_agent  # noqa: E402

# --- Config load (secrets never printed) ---
ENV_PATH = Path.home() / ".flashmoe" / "telegram" / ".env"
TOKEN: str | None = None
ALLOWED_USER_ID: int | None = None

if ENV_PATH.is_file():
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'\"")
        if k == "TELEGRAM_BOT_TOKEN":
            TOKEN = v
        elif k == "TELEGRAM_ALLOWED_USER_ID":
            try:
                ALLOWED_USER_ID = int(v)
            except ValueError:
                pass

if not TOKEN or ALLOWED_USER_ID is None:
    raise SystemExit(
        f"Missing TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_USER_ID in {ENV_PATH}"
    )

# --- Logging (no secrets) ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)
log = logging.getLogger("flashmoe-bot")


def _authorized(update: Update) -> bool:
    return bool(update.effective_user) and update.effective_user.id == ALLOWED_USER_ID


# --- Commands ---

async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        log.warning("unauthorized /start from user_id=%s", update.effective_user.id if update.effective_user else "?")
        if update.message:
            await update.message.reply_text("접근 권한이 없습니다.")
        return
    await update.message.reply_text(
        "🤖 Flash-MoE 397B Agent\n\n"
        "질문을 보내주세요. 필요 시 Google 검색(Serper)을 사용해 답합니다.\n\n"
        "/help  도움말\n"
        "/status  서버 상태\n\n"
        "⚠️ 복잡한 질문은 2–10분 걸릴 수 있습니다."
    )


async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "사용법:\n"
        "• 일반 메시지 → 에이전트가 필요 시 검색 후 답변\n"
        "• 답변은 한국어로 반환\n\n"
        "모델: Qwen3.5-397B-A17B (local Flash-MoE)\n"
        "검색: Serper (Google)"
    )


def _server_status() -> str:
    lines = ["📊 서버 상태"]
    for name, url in [
        ("infer (8000)", "http://127.0.0.1:8000/health"),
        ("wrapper (8771)", "http://127.0.0.1:8771/health"),
    ]:
        try:
            urllib.request.urlopen(url, timeout=3).read()
            lines.append(f"✅ {name}: OK")
        except Exception:
            lines.append(f"❌ {name}: DOWN")
    return "\n".join(lines)


async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _server_status)
    await update.message.reply_text(text)


# --- Main message handler ---

async def handle_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        log.warning("unauthorized message from user_id=%s", update.effective_user.id if update.effective_user else "?")
        return

    goal = (update.message.text or "").strip()
    if not goal:
        return
    log.info("query from %s: %s", update.effective_user.id, goal[:80])

    status_msg = await update.message.reply_text("🤔 생각 중... (몇 분 소요)")
    loop = asyncio.get_event_loop()
    last_text = {"v": ""}

    def _edit(text: str):
        if text == last_text["v"]:
            return
        last_text["v"] = text
        try:
            asyncio.run_coroutine_threadsafe(
                status_msg.edit_text(text[:3800]),
                loop,
            )
        except Exception:
            pass  # rate-limited or bot hiccup; drop

    def on_step(event: str, data: dict):
        if event == "iteration_start":
            _edit(f"🔄 반복 {data.get('i')}/{data.get('max')}…")
        elif event == "tool_call":
            name = data.get("name", "?")
            preview = str(data.get("args", {}))[:80]
            _edit(f"🔧 {name}({preview})")
        elif event == "tool_result":
            _edit(f"📋 {data.get('name', '?')} 결과 받음")
        elif event == "error":
            _edit(f"⚠️ {data.get('msg', 'error')[:200]}")
        elif event == "max_iterations":
            _edit("⚠️ 최대 반복 도달")
        # "final" is handled by message-reply below

    try:
        answer = await loop.run_in_executor(
            None,
            lambda: run_agent(
                goal,
                max_iterations=5,
                max_tokens=800,
                verbose=False,
                on_step=on_step,
            ),
        )
    except Exception as e:
        log.exception("agent failed")
        answer = f"❌ 에이전트 에러: {type(e).__name__}"

    answer = (answer or "[빈 응답]").strip()

    # Send final answer (chunk if > 4000 chars)
    CHUNK = 3900
    if len(answer) <= CHUNK:
        await update.message.reply_text(f"✅ {answer}")
    else:
        for i in range(0, len(answer), CHUNK):
            prefix = "✅ " if i == 0 else "… "
            await update.message.reply_text(prefix + answer[i:i + CHUNK])

    try:
        await status_msg.delete()
    except Exception:
        pass


async def on_error(_update, context):
    log.error("telegram error: %s", context.error)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(on_error)

    log.info("starting bot (allowed user_id=%s)", ALLOWED_USER_ID)
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
