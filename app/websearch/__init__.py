# -*- coding: utf-8 -*-
"""网页搜索：优先走配置的搜索 API，否则回落 Bing / DuckDuckGo HTML。"""
from __future__ import annotations

import html as htmlmod
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from app import config

_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL = 120.0
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _ok(message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"success": True, "message": message, "data": data or {}}


def _fail(message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"success": False, "message": message, "data": data or {}}


def _clean(text: str, limit: int = 280) -> str:
    t = htmlmod.unescape(_TAG_RE.sub(" ", text or ""))
    t = _WS_RE.sub(" ", t).strip()
    if len(t) > limit:
        return t[: limit - 1] + "…"
    return t


def _timeout() -> float:
    return float(getattr(config, "WEB_SEARCH_TIMEOUT_SEC", 8) or 8)


def _http_json(
    url: str,
    *,
    method: str = "GET",
    body: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> Any:
    hdrs = {"User-Agent": _UA, "Accept": "application/json"}
    hdrs.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout if timeout is not None else _timeout()) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw else {}


def _http_text(url: str, *, method: str = "GET", form: Optional[dict] = None) -> str:
    data = urllib.parse.urlencode(form).encode("utf-8") if form else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=_timeout()) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _unwrap_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    try:
        parsed = urlparse(u)
        if "duckduckgo.com" in (parsed.netloc or "") and parsed.path.startswith("/l"):
            qs = parse_qs(parsed.query)
            if qs.get("uddg"):
                return unquote(qs["uddg"][0])
        if "bing.com" in (parsed.netloc or "") and "url=" in parsed.query:
            qs = parse_qs(parsed.query)
            if qs.get("u"):
                return unquote(qs["u"][0])
    except Exception:
        return u
    return u


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _norm_hits(raw: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in raw:
        title = _clean(str(item.get("title") or ""), 80)
        url = _unwrap_url(str(item.get("url") or item.get("href") or item.get("link") or ""))
        snippet = _clean(str(item.get("snippet") or item.get("content") or item.get("body") or item.get("summary") or ""))
        if not title or not url or url in seen:
            continue
        if url.startswith("/"):
            continue
        seen.add(url)
        source = str(item.get("source") or "").strip() or _host(url)
        out.append({"title": title, "url": url, "snippet": snippet, "source": source})
        if len(out) >= count:
            break
    return out


def _dashscope(query: str, count: int) -> Dict[str, Any]:
    """百炼官方联网搜索（已有 BAILIAN_API_KEY 即可），返回 sources + 摘要。"""
    key = (getattr(config, "BAILIAN_API_KEY", "") or "").strip()
    if not key:
        raise RuntimeError("no bailian key")
    model = (getattr(config, "WEB_SEARCH_DASHSCOPE_MODEL", "") or "qwen-flash").strip() or "qwen-flash"
    timeout = float(getattr(config, "WEB_SEARCH_DASHSCOPE_TIMEOUT_SEC", 25) or 25)
    data = _http_json(
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        method="POST",
        body={
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "system",
                        "content": "你是车载助手的联网检索器。根据搜索结果简要回答，数字必须来自检索，不要编造。",
                    },
                    {"role": "user", "content": query},
                ]
            },
            "parameters": {
                "enable_search": True,
                "result_format": "message",
                "search_options": {
                    "forced_search": True,
                    "enable_source": True,
                    "search_strategy": "turbo",
                },
            },
        },
        headers={"Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    if data.get("code") and not data.get("output"):
        raise RuntimeError(str(data.get("message") or data.get("code")))
    out = data.get("output") or {}
    raw_hits = ((out.get("search_info") or {}).get("search_results") or [])
    hits = []
    for r in raw_hits:
        if not isinstance(r, dict):
            continue
        hits.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "snippet": r.get("snippet") or r.get("body") or "",
                "source": r.get("site_name") or r.get("hostname") or "",
            }
        )
    choices = out.get("choices") or []
    answer = ""
    if choices:
        answer = str(((choices[0].get("message") or {}).get("content")) or "").strip()
    elif out.get("text"):
        answer = str(out.get("text") or "").strip()
    return {"results": _norm_hits(hits, count), "answer": answer}


def _tavily(query: str, count: int) -> List[Dict[str, Any]]:
    key = (getattr(config, "TAVILY_API_KEY", "") or "").strip()
    if not key:
        raise RuntimeError("no tavily key")
    data = _http_json(
        "https://api.tavily.com/search",
        method="POST",
        body={"api_key": key, "query": query, "max_results": count, "search_depth": "basic", "include_answer": False},
    )
    hits = []
    for r in data.get("results") or []:
        hits.append({"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content")})
    return _norm_hits(hits, count)


def _bocha(query: str, count: int) -> List[Dict[str, Any]]:
    key = (getattr(config, "BOCHA_API_KEY", "") or "").strip()
    if not key:
        raise RuntimeError("no bocha key")
    data = _http_json(
        "https://api.bochaai.com/v1/web-search",
        method="POST",
        body={"query": query, "count": count, "summary": True},
        headers={"Authorization": f"Bearer {key}"},
    )
    web = ((data.get("data") or {}).get("webPages") or {}).get("value") or data.get("webPages") or []
    if isinstance(web, dict):
        web = web.get("value") or []
    hits = []
    for r in web:
        hits.append(
            {
                "title": r.get("name") or r.get("title"),
                "url": r.get("url") or r.get("displayUrl"),
                "snippet": r.get("snippet") or r.get("summary"),
            }
        )
    return _norm_hits(hits, count)


def _brave(query: str, count: int) -> List[Dict[str, Any]]:
    key = (getattr(config, "BRAVE_SEARCH_API_KEY", "") or "").strip()
    if not key:
        raise RuntimeError("no brave key")
    qs = urllib.parse.urlencode({"q": query, "count": count, "search_lang": "zh-hans", "country": "CN"})
    data = _http_json(
        f"https://api.search.brave.com/res/v1/web/search?{qs}",
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
    )
    hits = []
    for r in (data.get("web") or {}).get("results") or []:
        hits.append({"title": r.get("title"), "url": r.get("url"), "snippet": r.get("description")})
    return _norm_hits(hits, count)


def _html_query(query: str) -> str:
    """Bing HTML 对句首「今天/今日」容易理解成日历，去掉后再搜。"""
    q = (query or "").strip()
    stripped = re.sub(r"^(今天|今日)\s*", "", q).strip()
    if stripped and len(stripped) >= 4:
        return stripped
    return q


def _bing_html(query: str, count: int) -> List[Dict[str, Any]]:
    qs = urllib.parse.urlencode({"q": _html_query(query), "setlang": "zh-hans", "cc": "CN"})
    page = _http_text(f"https://cn.bing.com/search?{qs}")
    hits: List[Dict[str, Any]] = []
    # 现行 cn.bing.com 为 <li class="b_algo"...><h2 class=""><a href=...>
    for m in re.finditer(
        r'<li class="b_algo"[\s\S]*?<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>[\s\S]*?(?:<p class="b_lineclamp[^"]*"[^>]*>([\s\S]*?)</p>|<p[^>]*>([\s\S]*?)</p>)?',
        page,
        re.I,
    ):
        hits.append({"url": m.group(1), "title": m.group(2), "snippet": m.group(3) or m.group(4) or ""})
        if len(hits) >= count + 2:
            break
    if not hits:
        for m in re.finditer(
            r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>([\s\S]*?)</a>',
            page,
            re.I,
        ):
            hits.append({"url": m.group(1), "title": m.group(2), "snippet": ""})
            if len(hits) >= count + 2:
                break
    return _norm_hits(hits, count)


def _ddg_html(query: str, count: int) -> List[Dict[str, Any]]:
    page = _http_text("https://html.duckduckgo.com/html/", method="POST", form={"q": query, "kl": "cn-zh"})
    hits: List[Dict[str, Any]] = []
    for m in re.finditer(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>[\s\S]*?<a[^>]*class="result__snippet"[^>]*>([\s\S]*?)</a>',
        page,
        re.I,
    ):
        hits.append({"url": m.group(1), "title": m.group(2), "snippet": m.group(3)})
        if len(hits) >= count + 2:
            break
    if not hits:
        for m in re.finditer(
            r'<a rel="nofollow" class="result-link" href="([^"]+)"[^>]*>([\s\S]*?)</a>[\s\S]*?<td class="result-snippet">([\s\S]*?)</td>',
            page,
            re.I,
        ):
            hits.append({"url": m.group(1), "title": m.group(2), "snippet": m.group(3)})
            if len(hits) >= count + 2:
                break
    return _norm_hits(hits, count)


def _providers() -> List[Tuple[str, Any]]:
    pref = str(getattr(config, "WEB_SEARCH_PROVIDER", "auto") or "auto").strip().lower()
    all_p = [
        ("dashscope", _dashscope),
        ("tavily", _tavily),
        ("bocha", _bocha),
        ("brave", _brave),
        ("bing", _bing_html),
        ("duckduckgo", _ddg_html),
    ]
    if pref and pref != "auto":
        named = [p for p in all_p if p[0] == pref]
        rest = [p for p in all_p if p[0] != pref]
        return named + rest
    # auto：专用搜索 API > 已有百炼联网 > HTML 垫底
    ordered: List[Tuple[str, Any]] = []
    if getattr(config, "TAVILY_API_KEY", ""):
        ordered.append(("tavily", _tavily))
    if getattr(config, "BOCHA_API_KEY", ""):
        ordered.append(("bocha", _bocha))
    if getattr(config, "BRAVE_SEARCH_API_KEY", ""):
        ordered.append(("brave", _brave))
    if getattr(config, "BAILIAN_API_KEY", ""):
        ordered.append(("dashscope", _dashscope))
    ordered.extend([("bing", _bing_html), ("duckduckgo", _ddg_html)])
    return ordered


def web_search(query: str, count: int = 5) -> Dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return _fail("请告诉我要搜什么。")
    n = max(1, min(int(count or 5), 8))
    cache_key = f"{q}::{n}"
    hit = _CACHE.get(cache_key)
    if hit and time.time() < hit[0]:
        payload = dict(hit[1])
        payload["cached"] = True
        return _ok(payload.get("message") or "搜索完成", payload)

    errors: List[str] = []
    used = ""
    results: List[Dict[str, Any]] = []
    answer = ""
    for name, fn in _providers():
        try:
            raw = fn(q, n)
            extra = ""
            if isinstance(raw, dict):
                extra = str(raw.get("answer") or "").strip()
                results = list(raw.get("results") or [])
            else:
                results = list(raw or [])
            if results or extra:
                used = name
                answer = extra
                if not results and extra:
                    results = [
                        {
                            "title": "检索摘要",
                            "url": "",
                            "snippet": extra[:280],
                            "source": name,
                        }
                    ]
                break
            errors.append(f"{name}: 空结果")
        except Exception as e:
            errors.append(f"{name}: {e}")
            continue

    if not results:
        return _fail(
            f"网上这会儿搜不到「{q}」。换个关键词再试，或稍后再问。",
            {"query": q, "errors": errors},
        )

    payload = {
        "query": q,
        "provider": used,
        "count": len(results),
        "results": results,
    }
    if answer:
        payload["answer"] = answer
    msg = f"网页检索完成，共 {len(results)} 条（{used}）。"
    payload["message"] = msg
    _CACHE[cache_key] = (time.time() + _CACHE_TTL, dict(payload))
    return _ok(msg, payload)
