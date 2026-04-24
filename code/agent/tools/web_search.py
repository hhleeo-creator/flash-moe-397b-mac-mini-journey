"""Serper-based web search + URL body fetch.

stdlib-only (urllib), no extra pip deps.
API key is loaded once into a local variable and never logged or returned
in error messages — HTTP errors are reported by status code only.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from typing import Optional


def _load_serper_key() -> Optional[str]:
    """Read SERPER_API_KEY from ~/.env or ~/.openclaw/.env, else env var.

    Key is returned as a plain string; caller must treat it as a secret
    (no logging, no echo).
    """
    for path in ("~/.env", "~/.openclaw/.env"):
        p = os.path.expanduser(path)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("SERPER_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip("'\"")
                        if val:
                            return val
        except Exception:
            continue
    return os.environ.get("SERPER_API_KEY")


def web_search(query: str, num: int = 5, gl: str = "kr", hl: str = "ko") -> str:
    """Google search via Serper. Returns a LLM-friendly structured text.

    Args:
        query: search query
        num: number of organic results (default 5)
        gl: country code (kr = Korea)
        hl: language code (ko = Korean)
    """
    key = _load_serper_key()
    if not key:
        return "[SERPER_API_KEY not found in ~/.env or ~/.openclaw/.env]"

    body = json.dumps({"q": query, "num": num, "gl": gl, "hl": hl}).encode("utf-8")
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=body,
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return f"[Serper HTTP error {e.code}]"
    except Exception as e:
        return f"[Serper error: {type(e).__name__}]"

    parts: list[str] = []

    ab = data.get("answerBox") or {}
    ans = ab.get("answer") or ab.get("snippet") or ""
    if ans:
        parts.append(f"【직접 답변】\n{ans}")

    kg = data.get("knowledgeGraph") or {}
    if kg.get("title") or kg.get("description"):
        kg_text = f"【지식 그래프】\n{kg.get('title', '')}"
        if kg.get("description"):
            kg_text += f"\n{kg['description']}"
        parts.append(kg_text)

    organic = data.get("organic") or []
    if organic:
        out = ["【검색 결과】"]
        for i, item in enumerate(organic[:num], 1):
            title = item.get("title", "(no title)")
            link = item.get("link", "")
            snippet = item.get("snippet", "")
            out.append(f"{i}. {title}\n   URL: {link}\n   {snippet}")
        parts.append("\n".join(out))

    return "\n\n".join(parts) if parts else "[검색 결과 없음]"


_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", flags=re.DOTALL | re.I)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", flags=re.DOTALL | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def fetch_url(url: str, max_chars: int = 3000) -> str:
    """Fetch a URL and return plain-text body (stripped HTML).

    Best-effort — good for news/articles, may be empty on JS-heavy SPAs.
    """
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return "[invalid url]"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Apple M4 Pro) "
                    "FlashMoE-Agent/0.1"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        charset = "utf-8"
        ctype = resp.headers.get("Content-Type", "") if hasattr(resp, "headers") else ""
        m = re.search(r"charset=([^\s;]+)", ctype, flags=re.I)
        if m:
            charset = m.group(1).strip('"\'')
        html = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        return f"[Fetch HTTP error {e.code}]"
    except Exception as e:
        return f"[Fetch error: {type(e).__name__}]"

    text = _SCRIPT_RE.sub("", html)
    text = _STYLE_RE.sub("", text)
    text = _TAG_RE.sub(" ", text)
    text = unescape(text)
    text = _WS_RE.sub(" ", text).strip()

    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text or "[empty page]"


if __name__ == "__main__":
    key = _load_serper_key()
    print(f"Key loaded: {'yes' if key else 'NO'} (value intentionally not shown)")
    if not key:
        raise SystemExit(1)
    print("\n=== Search self-test: '문정동 한의원' ===")
    print(web_search("문정동 한의원", num=3))
