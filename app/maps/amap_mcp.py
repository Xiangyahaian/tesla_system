# -*- coding: utf-8 -*-
"""高德地图客户端：兼容官方 MCP 工具语义（maps_geo / maps_direction_driving 等）。

周边 POI（美食/充电站等）**只走 MCP**，连不上就报错，禁止 REST 回落、禁止编造。
导航路径规划仍可用 REST 取折线（MCP 常丢 polyline）。
"""
from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from app import config

# 北京理工大学中关村校区南门（GCJ-02）
# 来源：高德 inputtips「北京理工大学中关村本部校区(南门)」；勿用 maps_geo 模糊检索（会误命中朝阳校区）
BIT_ZHONGGUANCUN_SOUTH_GATE = {
    "name": "北京理工大学中关村校区南门",
    "address": "北京市海淀区中关村南大街5号",
    "lng": 116.316356,
    "lat": 39.957053,
    "location": "116.316356,39.957053",
}

REST_GEO = "https://restapi.amap.com/v3/geocode/geo"
REST_DRIVING = "https://restapi.amap.com/v3/direction/driving"
REST_AROUND = "https://restapi.amap.com/v3/place/around"
REST_TEXT = "https://restapi.amap.com/v3/place/text"
REST_TIPS = "https://restapi.amap.com/v3/assistant/inputtips"
MCP_URL = "https://mcp.amap.com/mcp"


def amap_configured() -> bool:
    return bool(getattr(config, "AMAP_MAPS_API_KEY", "") or "")


def _http_json(url: str, *, timeout: float = 12) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "tesla-cabin/amap"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _mcp_call(tool: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """尝试调用高德托管 MCP（tools/call）。协议细节因版本可能变化，失败返回 None。"""
    try:
        return _mcp_call_strict(tool, arguments)
    except Exception:
        return None


def _mcp_call_strict(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """调用高德 MCP；失败直接抛错，不做 REST 回落。"""
    key = getattr(config, "AMAP_MAPS_API_KEY", "") or ""
    if not key:
        raise RuntimeError("未配置高德 Key，地图 MCP 无法连接")
    url = f"{MCP_URL}?key={urllib.parse.quote(key)}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"高德 MCP 连接失败：{e}") from e

    text = raw.strip()
    if text.startswith("data:"):
        lines = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        text = lines[-1] if lines else text
    try:
        obj = json.loads(text)
    except Exception as e:
        raise RuntimeError(f"高德 MCP 返回无法解析：{e}") from e

    if isinstance(obj, dict) and obj.get("error"):
        err = obj.get("error")
        raise RuntimeError(f"高德 MCP 错误：{err}")

    result = obj.get("result") or obj
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list) and content:
        piece = content[0]
        if isinstance(piece, dict) and piece.get("type") == "text":
            body = piece.get("text") or ""
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    return parsed
                return {"data": parsed}
            except Exception:
                return {"text": body}
        if isinstance(piece, dict) and piece.get("type") == "text" and piece.get("text"):
            raise RuntimeError(f"高德 MCP 返回异常文本：{str(piece.get('text'))[:120]}")
    if isinstance(result, dict):
        return result
    raise RuntimeError("高德 MCP 未返回有效结果")


def maps_geo(address: str, city: str = "北京") -> Dict[str, Any]:
    """MCP maps_geo：地理编码。"""
    address = (address or "").strip()
    if not address:
        raise RuntimeError("地址为空")

    mcp = _mcp_call("maps_geo", {"address": address, "city": city})
    if mcp and (mcp.get("location") or mcp.get("geocodes")):
        if mcp.get("location"):
            return mcp
        geo0 = (mcp.get("geocodes") or [None])[0] or {}
        if geo0.get("location"):
            return {
                "location": geo0["location"],
                "name": geo0.get("formatted_address") or address,
                "address": geo0.get("formatted_address") or address,
            }

    key = getattr(config, "AMAP_MAPS_API_KEY", "") or ""
    if not key:
        # 无 key 时：南门可识别，其它地址失败
        if "理工" in address and ("南门" in address or "中关村" in address):
            return dict(BIT_ZHONGGUANCUN_SOUTH_GATE)
        raise RuntimeError("未配置 AMAP_MAPS_API_KEY，无法地理编码")

    qs = urllib.parse.urlencode(
        {"key": key, "address": address, "city": city, "source": "ts_mcp"}
    )
    data = _http_json(f"{REST_GEO}?{qs}")
    if str(data.get("status")) != "1":
        raise RuntimeError(f"地理编码失败: {data.get('info') or data.get('infocode')}")
    geos = data.get("geocodes") or []
    if not geos:
        raise RuntimeError(f"未找到地点: {address}")
    g0 = geos[0]
    return {
        "location": g0.get("location"),
        "name": g0.get("formatted_address") or address,
        "address": g0.get("formatted_address") or address,
        "level": g0.get("level"),
    }


def _rest_place_text(keywords: str, city: str = "北京", offset: int = 8) -> List[Dict[str, Any]]:
    """REST 关键词搜 POI（带 location）。导航目的地解析用；周边推荐仍只走 MCP。"""
    key = getattr(config, "AMAP_MAPS_API_KEY", "") or ""
    if not key:
        return []
    qs = urllib.parse.urlencode(
        {
            "key": key,
            "keywords": keywords,
            "city": city,
            "citylimit": "true",
            "offset": max(1, min(25, int(offset))),
            "extensions": "base",
            "source": "ts_nav",
        }
    )
    try:
        data = _http_json(f"{REST_TEXT}?{qs}")
    except Exception:
        return []
    if str(data.get("status")) != "1":
        return []
    out: List[Dict[str, Any]] = []
    for p in data.get("pois") or []:
        if not isinstance(p, dict):
            continue
        loc = (p.get("location") or "").strip()
        name = (p.get("name") or "").strip()
        if not loc or "," not in loc or not name:
            continue
        out.append(
            {
                "name": name,
                "address": p.get("address") or "",
                "location": loc,
                "type": p.get("type") or "",
            }
        )
    return out


def search_places(
    keywords: str,
    *,
    city: str = "北京",
    lng: Optional[float] = None,
    lat: Optional[float] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """输入提示 / 地点搜索：优先 inputtips，失败回落 place/text。"""
    q = (keywords or "").strip()
    if not q:
        return []
    key = getattr(config, "AMAP_MAPS_API_KEY", "") or ""
    if not key:
        return []
    limit = max(1, min(12, int(limit)))
    tips_params: Dict[str, Any] = {
        "key": key,
        "keywords": q,
        "city": city,
        "citylimit": "true",
        "datatype": "all",
    }
    if lng is not None and lat is not None:
        tips_params["location"] = f"{float(lng):.6f},{float(lat):.6f}"
    out: List[Dict[str, Any]] = []
    try:
        data = _http_json(f"{REST_TIPS}?{urllib.parse.urlencode(tips_params)}", timeout=8)
        if str(data.get("status")) == "1":
            for tip in data.get("tips") or []:
                if not isinstance(tip, dict):
                    continue
                name = str(tip.get("name") or "").strip()
                loc = tip.get("location")
                if isinstance(loc, list):
                    loc = ""
                loc = str(loc or "").strip()
                if not name or not loc or "," not in loc:
                    continue
                district = tip.get("district") or ""
                addr = tip.get("address") or ""
                if isinstance(addr, list):
                    addr = addr[0] if addr else ""
                address = " · ".join(x for x in (str(district).strip(), str(addr).strip()) if x)
                out.append(
                    {
                        "name": name,
                        "address": address,
                        "location": loc,
                        "type": tip.get("typecode") or "",
                        "source": "inputtips",
                    }
                )
    except Exception:
        out = []
    if len(out) < 3:
        for p in _rest_place_text(q, city=city, offset=limit):
            if any(x.get("location") == p.get("location") for x in out):
                continue
            out.append({**p, "source": "place_text"})
            if len(out) >= limit:
                break
    return _dedupe_pois(out)[:limit]


def _pick_best_poi(keywords: str, pois: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not pois:
        return None
    kw = (keywords or "").strip()
    # 精确/前缀优先，再包含
    for p in pois:
        if p.get("name") == kw:
            return p
    for p in pois:
        name = str(p.get("name") or "")
        if name.startswith(kw) or kw.startswith(name):
            return p
    for p in pois:
        if kw and kw in str(p.get("name") or ""):
            return p
    return pois[0]


def _dedupe_pois(pois: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for p in pois:
        name = str(p.get("name") or "").strip()
        loc = str(p.get("location") or "").strip()
        key = name or loc
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _geo_too_coarse(geo: Dict[str, Any]) -> bool:
    """城市/区县级编码对导航太粗，不能当目的地。"""
    level = str(geo.get("level") or "")
    name = str(geo.get("name") or geo.get("address") or "")
    if any(x in level for x in ("省", "市", "区县", "乡镇")):
        return True
    if name in {"北京", "北京市"} or (name.endswith("市") and len(name) <= 4):
        return True
    return False


class PlaceAmbiguousError(Exception):
    """目的地简称对应多处 POI，需要用户选择。"""

    def __init__(self, query: str, candidates: List[Dict[str, Any]]):
        self.query = query
        self.candidates = candidates
        super().__init__(f"目的地「{query}」有多处匹配")


def _normalize_place_query(name: str) -> str:
    """纠正常见口误，便于检索。"""
    q = (name or "").strip()
    q = q.replace("冰壶管", "冰壶馆").replace("冰球管", "冰球馆")
    q = q.replace("游泳管", "游泳馆").replace("图书管", "图书馆")
    return q


def _poi_relevance_score(query: str, poi: Dict[str, Any]) -> float:
    """目的地与 POI 的相关度；用于多结果时丢掉牛肉面这类无关项。"""
    q = _normalize_place_query(query)
    name = str(poi.get("name") or "")
    addr = str(poi.get("address") or "")
    blob = f"{name} {addr}"
    if not q or not name:
        return -1.0
    score = 0.0
    if name == q:
        score += 200
    if q in name:
        score += 100
    if q in blob:
        score += 40
    # 二字片段重合
    for i in range(max(0, len(q) - 1)):
        bg = q[i : i + 2]
        if not bg.strip():
            continue
        if bg in name:
            score += 12
        elif bg in addr:
            score += 4
    # 场馆类查询：打压餐饮店
    if re.search(r"(馆|场|中心|大厦|广场|园|寺|站|机场)", q) and re.search(
        r"(面|粉|饭|火锅|烧烤|餐饮|餐厅|饭店|咖啡|奶茶|小吃|超市|便利)", name
    ):
        score -= 80
    # 名称几乎不沾边
    shared = sum(1 for ch in set(q) if ch in name and "\u4e00" <= ch <= "\u9fff")
    if shared <= 1 and q not in name:
        score -= 30
    return score


def _filter_relevant_pois(query: str, pois: List[Dict[str, Any]], limit: int = 4) -> List[Dict[str, Any]]:
    """按相关度筛候选；筛完只剩 1 个则视为可直接用。"""
    if not pois:
        return []
    scored = [(_poi_relevance_score(query, p), p) for p in pois if isinstance(p, dict)]
    scored.sort(key=lambda x: -x[0])
    kept = [p for s, p in scored if s >= 20][:limit]
    if not kept:
        kept = [p for s, p in scored if s >= 8][:limit]
    if not kept:
        # 仍无可靠项：最多保留分数最高的 2 个，避免乱塞餐饮
        kept = [p for s, p in scored if s > 0][: min(2, limit)]
    return kept


def lookup_destination(name: str, city: str = "北京", limit: int = 4) -> Dict[str, Any]:
    """解析导航目的地：唯一则 ok；多处则 ambiguous（交给 Agent 反问）。"""
    name = _normalize_place_query(name)
    if not name:
        return {"status": "not_found", "query": name, "candidates": []}

    pois = _filter_relevant_pois(name, _dedupe_pois(_rest_place_text(name, city=city, offset=10)), limit=max(limit, 6))
    exact = [p for p in pois if p.get("name") == name]
    if exact:
        return {"status": "ok", "place": exact[0], "candidates": exact[:1], "query": name}

    containing = [p for p in pois if name in str(p.get("name") or "")]
    if len(containing) >= 2:
        return {
            "status": "ambiguous",
            "candidates": containing[:limit],
            "query": name,
        }
    if len(containing) == 1:
        return {"status": "ok", "place": containing[0], "candidates": containing, "query": name}

    if len(pois) >= 2:
        return {"status": "ambiguous", "candidates": pois[:limit], "query": name}
    if len(pois) == 1:
        return {"status": "ok", "place": pois[0], "candidates": pois, "query": name}

    # 地理编码：仅接受足够具体的结果
    try:
        geo = maps_geo(name, city=city)
        loc = (geo.get("location") or "").strip()
        if loc and "," in loc and not _geo_too_coarse(geo):
            place = {
                "location": loc,
                "name": geo.get("name") or name,
                "address": geo.get("address") or geo.get("name") or name,
            }
            return {"status": "ok", "place": place, "candidates": [place], "query": name}
    except Exception:
        pass

    # MCP 候选名再检索
    try:
        mcp = maps_text_search(name, city=city, offset=6)
        expanded: List[Dict[str, Any]] = []
        for p in mcp.get("pois") or []:
            cand = (p.get("name") or "").strip()
            if not cand:
                continue
            cpois = _rest_place_text(cand, city=city, offset=2)
            if cpois:
                expanded.extend(cpois)
            elif p.get("location"):
                expanded.append(
                    {"name": cand, "address": p.get("address") or "", "location": p["location"]}
                )
        expanded = _filter_relevant_pois(name, _dedupe_pois(expanded), limit=max(limit, 6))
        containing = [p for p in expanded if name in str(p.get("name") or "")]
        pool = containing or expanded
        if len(pool) >= 2 and not any(p.get("name") == name for p in pool):
            return {"status": "ambiguous", "candidates": pool[:limit], "query": name}
        if len(pool) == 1:
            return {"status": "ok", "place": pool[0], "candidates": pool, "query": name}
        if pool:
            return {"status": "ambiguous", "candidates": pool[:limit], "query": name}
    except Exception:
        pass

    return {"status": "not_found", "query": name, "candidates": []}


def resolve_place(name: str, city: str = "北京") -> Dict[str, Any]:
    """解析到唯一目的地；多处匹配时抛 PlaceAmbiguousError。"""
    hit = lookup_destination(name, city=city)
    if hit.get("status") == "ok" and hit.get("place"):
        p = hit["place"]
        return {
            "location": p.get("location"),
            "name": p.get("name") or name,
            "address": p.get("address") or p.get("name") or name,
            "source": "lookup",
        }
    if hit.get("status") == "ambiguous":
        raise PlaceAmbiguousError(name, hit.get("candidates") or [])
    raise RuntimeError(f"找不到地点「{name}」")


def decode_polyline(poly: str) -> List[List[float]]:
    """高德 polyline: 'lng,lat;lng,lat' → [[lng,lat], ...]"""
    pts: List[List[float]] = []
    for part in (poly or "").split(";"):
        part = part.strip()
        if not part or "," not in part:
            continue
        a, b = part.split(",", 1)
        try:
            pts.append([float(a), float(b)])
        except ValueError:
            continue
    return pts


def maps_around_search(
    location: str,
    keywords: str,
    *,
    radius: int = 3000,
    types: str = "",
    offset: int = 8,
) -> Dict[str, Any]:
    """周边检索：仅高德 MCP maps_around_search，失败即报错，不回落 REST、不编造。"""
    keywords = (keywords or "").strip() or "生活服务"
    location = (location or "").strip()
    if not location or "," not in location:
        raise RuntimeError("缺少定位坐标，无法搜索周边")

    mcp = _mcp_call_strict(
        "maps_around_search",
        {
            "location": location,
            "keywords": keywords,
            "radius": str(radius),
        },
    )
    pois: List[Dict[str, Any]] = []
    raw = mcp.get("pois") or mcp.get("data") or []
    if isinstance(raw, list):
        for p in raw[:offset]:
            if not isinstance(p, dict):
                continue
            name = (p.get("name") or "").strip()
            if not name:
                continue
            pois.append(
                {
                    "name": name,
                    "address": p.get("address") or p.get("pname") or "",
                    "location": p.get("location") or "",
                    "type": p.get("type") or "",
                    "distance": p.get("distance") or p.get("distance_m") or "",
                    "tel": p.get("tel") or "",
                }
            )

    return {
        "keywords": keywords,
        "location": location,
        "radius_m": radius,
        "count": len(pois),
        "pois": pois,
        "provider": "amap",
        "source": "amap_mcp",
        "tool": "maps_around_search",
    }


def maps_text_search(keywords: str, city: str = "北京", offset: int = 8) -> Dict[str, Any]:
    """关键词搜地点：仅高德 MCP，失败即报错，不回落 REST。"""
    keywords = (keywords or "").strip()
    if not keywords:
        raise RuntimeError("搜索关键词为空")
    mcp = _mcp_call_strict("maps_text_search", {"keywords": keywords, "city": city})
    pois: List[Dict[str, Any]] = []
    raw = mcp.get("pois") or mcp.get("data") or []
    if isinstance(raw, list):
        for p in raw[:offset]:
            if not isinstance(p, dict):
                continue
            name = (p.get("name") or "").strip()
            if not name:
                continue
            pois.append(
                {
                    "name": name,
                    "address": p.get("address") or "",
                    "location": p.get("location") or "",
                    "type": p.get("type") or "",
                    "tel": p.get("tel") or "",
                }
            )
    return {
        "keywords": keywords,
        "city": city,
        "count": len(pois),
        "pois": pois,
        "provider": "amap",
        "source": "amap_mcp",
        "tool": "maps_text_search",
    }


def maps_direction_driving(origin: str, destination: str) -> Dict[str, Any]:
    """MCP maps_direction_driving + REST extensions=all 以拿到折线。"""
    key = getattr(config, "AMAP_MAPS_API_KEY", "") or ""
    if not key:
        raise RuntimeError("未配置 AMAP_MAPS_API_KEY，无法路径规划")

    # 先拿带 polyline 的 REST（座舱地图必需）；MCP 官方实现会丢掉折线
    qs = urllib.parse.urlencode(
        {
            "key": key,
            "origin": origin,
            "destination": destination,
            "extensions": "all",
            "strategy": 0,
            "source": "ts_mcp",
        }
    )
    data = _http_json(f"{REST_DRIVING}?{qs}")
    if str(data.get("status")) != "1":
        # 再试 MCP（至少拿距离/时长）
        mcp = _mcp_call(
            "maps_direction_driving",
            {"origin": origin, "destination": destination},
        )
        if not mcp:
            raise RuntimeError(f"驾车规划失败: {data.get('info') or data.get('infocode')}")
        return mcp

    route = data.get("route") or {}
    paths = route.get("paths") or []
    if not paths:
        raise RuntimeError("未规划出驾车路线")
    path0 = paths[0]
    steps_out = []
    polyline: List[List[float]] = []
    for step in path0.get("steps") or []:
        pts = decode_polyline(step.get("polyline") or "")
        polyline.extend(pts)
        steps_out.append(
            {
                "instruction": step.get("instruction") or "",
                "road": step.get("road") or "",
                "distance": float(step.get("distance") or 0),
                "duration": float(step.get("duration") or 0),
                "orientation": step.get("orientation") or "",
            }
        )
    # 去重点
    cleaned: List[List[float]] = []
    for p in polyline:
        if not cleaned or (abs(cleaned[-1][0] - p[0]) > 1e-7 or abs(cleaned[-1][1] - p[1]) > 1e-7):
            cleaned.append(p)

    return {
        "route": {
            "origin": route.get("origin") or origin,
            "destination": route.get("destination") or destination,
            "paths": [
                {
                    "distance": float(path0.get("distance") or 0),
                    "duration": float(path0.get("duration") or 0),
                    "steps": steps_out,
                    "polyline": cleaned,
                }
            ],
        },
        "source": "amap_rest+mcp_compat",
    }


def haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def polyline_length_m(pts: List[List[float]]) -> float:
    total = 0.0
    for i in range(1, len(pts)):
        total += haversine_m(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])
    return total


def advance_along_polyline(
    pts: List[List[float]],
    dist_m: float,
) -> Tuple[List[float], float, float]:
    """沿折线前进 dist_m，返回 (lng,lat)、已走路程、剩余路程。"""
    if not pts:
        return [BIT_ZHONGGUANCUN_SOUTH_GATE["lng"], BIT_ZHONGGUANCUN_SOUTH_GATE["lat"]], 0.0, 0.0
    if len(pts) == 1:
        return pts[0], 0.0, 0.0
    total = polyline_length_m(pts)
    target = max(0.0, min(total, dist_m))
    walked = 0.0
    for i in range(1, len(pts)):
        seg = haversine_m(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])
        if walked + seg >= target:
            remain_seg = target - walked
            ratio = 0.0 if seg < 1e-6 else remain_seg / seg
            lng = pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * ratio
            lat = pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * ratio
            return [lng, lat], target, max(0.0, total - target)
        walked += seg
    return pts[-1], total, 0.0


def plan_drive_from_coords(
    origin_loc: str,
    destination: str,
    *,
    origin_name: str = "当前位置",
) -> Dict[str, Any]:
    """从给定 GCJ-02 坐标起点规划到目的地。"""
    d = resolve_place(destination)
    dest_loc = d.get("location")
    if not dest_loc:
        raise RuntimeError(f"无法解析目的地: {destination}")
    origin_loc = (origin_loc or "").strip()
    if "," not in origin_loc:
        raise RuntimeError("起点坐标无效")

    route = maps_direction_driving(origin_loc, dest_loc)
    path0 = ((route.get("route") or {}).get("paths") or [{}])[0]
    distance = float(path0.get("distance") or 0)
    duration = float(path0.get("duration") or 0)
    polyline = path0.get("polyline") or []
    if not polyline:
        olng, olat = [float(x) for x in origin_loc.split(",")]
        dlng, dlat = [float(x) for x in dest_loc.split(",")]
        polyline = [[olng, olat], [dlng, dlat]]
        if distance <= 0:
            distance = polyline_length_m(polyline)
        if duration <= 0:
            duration = max(60.0, distance / 10.0)

    eta_min = max(1, int(round(duration / 60.0)))
    olng, olat = [float(x) for x in origin_loc.split(",")]
    return {
        "origin": {
            "name": origin_name,
            "location": origin_loc,
            "lng": olng,
            "lat": olat,
        },
        "destination": {
            "name": d.get("name") or destination,
            "location": dest_loc,
            "lng": float(dest_loc.split(",")[0]),
            "lat": float(dest_loc.split(",")[1]),
        },
        "distance_m": distance,
        "duration_sec": duration,
        "eta_min": eta_min,
        "steps": path0.get("steps") or [],
        "polyline": polyline,
        "progress_m": 0.0,
        "remaining_m": distance,
        "position": {"lng": olng, "lat": olat, "name": origin_name},
        "traffic": "畅通",
        "provider": "amap",
    }


def move_by_heading(lng: float, lat: float, heading_deg: float, dist_m: float) -> List[float]:
    """航向 0°=北、90°=东；按距离推进 GCJ-02 近似坐标。"""
    rad = math.radians(heading_deg)
    dlat = (dist_m * math.cos(rad)) / 111320.0
    cos_lat = math.cos(math.radians(lat)) or 1e-6
    dlng = (dist_m * math.sin(rad)) / (111320.0 * cos_lat)
    return [lng + dlng, lat + dlat]


def heading_from_segment(a: List[float], b: List[float]) -> float:
    """由折线段得到航向角（度，北为 0）。"""
    dlng = b[0] - a[0]
    dlat = b[1] - a[1]
    return (math.degrees(math.atan2(dlng, dlat)) + 360.0) % 360.0


def advance_along_polyline_with_heading(
    pts: List[List[float]],
    dist_m: float,
) -> Tuple[List[float], float, float, float]:
    """沿线推进，额外返回航向。"""
    pos, walked, remain = advance_along_polyline(pts, dist_m)
    heading = 90.0
    if len(pts) >= 2:
        # 找当前所在段
        target = walked
        acc = 0.0
        for i in range(1, len(pts)):
            seg = haversine_m(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])
            if acc + seg >= target - 1e-6 or i == len(pts) - 1:
                heading = heading_from_segment(pts[i - 1], pts[i])
                break
            acc += seg
    return pos, walked, remain, heading


SOUTH_GATE_ALIASES = {
    BIT_ZHONGGUANCUN_SOUTH_GATE["name"],
    "北京理工大学南门",
    "北理工南门",
    "理工大学南门",
    "北京理工大学中关村本部校区南门",
    "北京理工大学中关村本部校区(南门)",
}


def plan_drive(destination: str, origin_name: Optional[str] = None) -> Dict[str, Any]:
    """从南门（或指定起点）规划到目的地。"""
    origin_label = origin_name or BIT_ZHONGGUANCUN_SOUTH_GATE["name"]
    # 默认南门：直接用精确坐标，避免 geo 把「中关村校区南门」解析到朝阳校区公交站
    if not origin_name or origin_name.strip() in SOUTH_GATE_ALIASES:
        o = dict(BIT_ZHONGGUANCUN_SOUTH_GATE)
    else:
        o = resolve_place(origin_name)

    d = resolve_place(destination)
    origin_loc = o.get("location") or BIT_ZHONGGUANCUN_SOUTH_GATE["location"]
    dest_loc = d.get("location")
    if not dest_loc:
        raise RuntimeError(f"无法解析目的地: {destination}")

    route = maps_direction_driving(origin_loc, dest_loc)
    path0 = ((route.get("route") or {}).get("paths") or [{}])[0]
    distance = float(path0.get("distance") or 0)
    duration = float(path0.get("duration") or 0)
    polyline = path0.get("polyline") or []
    if not polyline and origin_loc and dest_loc:
        # MCP 无折线时至少连起终点
        olng, olat = [float(x) for x in origin_loc.split(",")]
        dlng, dlat = [float(x) for x in dest_loc.split(",")]
        polyline = [[olng, olat], [dlng, dlat]]
        if distance <= 0:
            distance = polyline_length_m(polyline)
        if duration <= 0:
            duration = max(60.0, distance / 10.0)

    eta_min = max(1, int(round(duration / 60.0)))
    return {
        "origin": {
            "name": o.get("name") or origin_label,
            "location": origin_loc,
            "lng": float(origin_loc.split(",")[0]),
            "lat": float(origin_loc.split(",")[1]),
        },
        "destination": {
            "name": d.get("name") or destination,
            "location": dest_loc,
            "lng": float(dest_loc.split(",")[0]),
            "lat": float(dest_loc.split(",")[1]),
        },
        "distance_m": distance,
        "duration_sec": duration,
        "eta_min": eta_min,
        "steps": path0.get("steps") or [],
        "polyline": polyline,
        "progress_m": 0.0,
        "remaining_m": distance,
        "position": {
            "lng": float(origin_loc.split(",")[0]),
            "lat": float(origin_loc.split(",")[1]),
            "name": o.get("name") or origin_label,
        },
        "traffic": "畅通",
        "provider": "amap",
    }
