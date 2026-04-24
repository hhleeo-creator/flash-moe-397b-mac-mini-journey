#!/usr/bin/env python3
"""Minimal tool-calling agent for Flash-MoE 397B via local wrapper.

Design choices:
  - Short system prompt (~40 tokens) — Flash-MoE prefill is 190 ms/token.
  - Single `bash` tool — avoids 100+ tool specs bloating context.
  - `strip_think=True` — drops reasoning from UI, but Qwen still plans internally.
  - `max_tokens=400` default — keeps each turn under ~90 seconds of generation.
  - `max_iterations=2` default — tool + final answer.
  - subprocess timeout 30 s, output capped at 2000 chars.

Usage:
  simple_agent.py "현재 디렉토리 파일 개수를 세어줘"
  simple_agent.py --max-iter 3 --max-tokens 600 "..."
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from openai import OpenAI

WRAPPER_URL = "http://127.0.0.1:8771/v1"
MODEL_ID = "qwen3.5-397b-a17b"

SYSTEM_PROMPT = (
    "당신은 마스터의 Mac에서 동작하는 유용한 AI 비서입니다. "
    "필요할 때 bash 도구로 명령을 실행할 수 있습니다. "
    "답변은 한국어로 간결하게 해주세요."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a bash command and return stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "bash command",
                    }
                },
                "required": ["command"],
            },
        },
    }
]


def run_bash(command: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        out = f"[timeout {timeout}s]"
    except Exception as e:
        out = f"[error: {type(e).__name__}: {e}]"
    if len(out) > 2000:
        out = out[:2000] + "\n...[truncated]"
    return out.strip() or "[empty]"


def run_agent(
    goal: str, max_iterations: int = 2, max_tokens: int = 400
) -> str | None:
    client = OpenAI(base_url=WRAPPER_URL, api_key="local-dummy")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": goal},
    ]

    for i in range(1, max_iterations + 1):
        print(f"\n── iteration {i}/{max_iterations} ──", flush=True)
        t0 = time.time()
        resp = client.chat.completions.create(
            model=MODEL_ID,
            messages=messages,
            tools=TOOLS,
            max_tokens=max_tokens,
            extra_body={"strip_think": True},
        )
        dur = time.time() - t0
        msg = resp.choices[0].message
        finish = resp.choices[0].finish_reason
        print(f"[{dur:.1f}s, finish={finish}]", flush=True)

        if msg.tool_calls:
            # Persist the assistant turn with tool_calls intact
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                cmd = args.get("command", "")
                print(f"🔧 {tc.function.name}({cmd!r})", flush=True)
                result = run_bash(cmd)
                preview = result[:400].replace("\n", " ")
                print(f"📋 {preview}", flush=True)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )
            continue

        # No tool calls — final answer
        content = msg.content or ""
        print("\n✅ 답변:\n" + content.strip(), flush=True)
        return content

    print("\n⚠️ max_iterations reached without final answer", flush=True)
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="Flash-MoE 397B 전용 minimal agent")
    p.add_argument("goal", nargs="+", help="목표/질문")
    p.add_argument("--max-iter", type=int, default=2)
    p.add_argument("--max-tokens", type=int, default=400)
    args = p.parse_args()
    goal = " ".join(args.goal)
    run_agent(goal, max_iterations=args.max_iter, max_tokens=args.max_tokens)
    return 0


if __name__ == "__main__":
    sys.exit(main())
