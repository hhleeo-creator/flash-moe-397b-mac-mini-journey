#!/usr/bin/env python3
"""Flash-MoE 397B + Serper Web Search + URL fetch agent.

Designed to be importable from a Telegram bot or any other front-end:
    from web_agent import run_agent
    answer = run_agent("질문", on_step=my_callback)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Allow `from tools.web_search import ...` when run as a script
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from openai import OpenAI  # noqa: E402

from tools.web_search import fetch_url, web_search  # noqa: E402

WRAPPER_URL = "http://127.0.0.1:8771/v1"
MODEL = "qwen3.5-397b-a17b"

_client = OpenAI(base_url=WRAPPER_URL, api_key="local-dummy")

SYSTEM_PROMPT = (
    "당신은 유용한 한국어 AI 비서입니다.\n\n"
    "도구 사용 원칙:\n"
    "- 최신 정보나 확실치 않은 사실이 필요하면 web_search로 검색\n"
    "- 검색 결과 중 특정 페이지 상세 내용이 필요하면 fetch_url로 원문 확인\n"
    "- 답변이 확실하면 도구 없이 바로 응답\n"
    "- 불필요한 도구 호출 지양\n\n"
    "답변은 명확하고 자연스러운 한국어로."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Google 웹 검색. 최신 정보, 통계, 사실 확인에 사용.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색어"},
                    "num": {"type": "integer", "description": "결과 개수", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "웹페이지 본문 추출. 검색 결과 중 상세 내용 필요한 URL에 사용.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "가져올 URL"},
                    "max_chars": {"type": "integer", "description": "최대 글자 수", "default": 3000},
                },
                "required": ["url"],
            },
        },
    },
]


def _execute_tool(name: str, args: dict) -> str:
    try:
        if name == "web_search":
            return web_search(args.get("query", ""), int(args.get("num", 5)))
        if name == "fetch_url":
            return fetch_url(args.get("url", ""), int(args.get("max_chars", 3000)))
        return f"[Unknown tool: {name}]"
    except Exception as e:
        return f"[Tool {name} failed: {type(e).__name__}]"


def run_agent(
    goal: str,
    max_iterations: int = 5,
    max_tokens: int = 800,
    verbose: bool = True,
    on_step=None,
) -> str:
    """Run the agent loop until a final answer or max_iterations reached.

    on_step(event_type, data): optional callback for UI/Telegram.
        event_type ∈ {"iteration_start","tool_call","tool_result","final",
                     "max_iterations","error"}
    """
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": goal},
    ]

    for i in range(1, max_iterations + 1):
        if verbose:
            print(f"\n── iteration {i}/{max_iterations} ──", flush=True)
        if on_step:
            on_step("iteration_start", {"i": i, "max": max_iterations})

        try:
            resp = _client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                max_tokens=max_tokens,
                extra_body={"strip_think": True},
            )
        except Exception as e:
            err = f"[LLM error: {type(e).__name__}]"
            if verbose:
                print(err, flush=True)
            if on_step:
                on_step("error", {"msg": err})
            return err

        msg = resp.choices[0].message
        finish = resp.choices[0].finish_reason
        if verbose:
            print(f"[finish={finish}]", flush=True)

        if msg.tool_calls:
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
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if verbose:
                    args_short = json.dumps(args, ensure_ascii=False)[:200]
                    print(f"🔧 {tc.function.name}({args_short})", flush=True)
                if on_step:
                    on_step("tool_call", {"name": tc.function.name, "args": args})

                result = _execute_tool(tc.function.name, args)

                if verbose:
                    preview = result[:200].replace("\n", " ")
                    print(f"📋 {preview}", flush=True)
                if on_step:
                    on_step("tool_result", {"name": tc.function.name, "preview": result[:400]})

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )
            continue

        # No tool calls → final answer
        answer = (msg.content or "").strip() or "[빈 응답]"
        if verbose:
            print("\n✅ 최종 답변:\n" + answer, flush=True)
        if on_step:
            on_step("final", {"answer": answer})
        return answer

    if verbose:
        print("\n⚠️ 최대 반복 도달", flush=True)
    if on_step:
        on_step("max_iterations", {})
    return "[최대 반복 도달]"


def main() -> int:
    p = argparse.ArgumentParser(description="Flash-MoE 397B + Serper web agent")
    p.add_argument("goal", nargs="*", help="질문")
    p.add_argument("--max-iter", type=int, default=5)
    p.add_argument("--max-tokens", type=int, default=800)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()
    goal = " ".join(args.goal) if args.goal else input("질문: ")
    run_agent(
        goal,
        max_iterations=args.max_iter,
        max_tokens=args.max_tokens,
        verbose=not args.quiet,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
