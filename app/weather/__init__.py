# -*- coding: utf-8 -*-
"""当前位置天气：高德逆地理 → adcode → 实况天气；服务端缓存 10 分钟。"""
from __future__ import annotations

import time
import urllib.parse
from typing import Any, Dict, Optional, Tuple

from app import config
from app.maps.amap_mcp import BIT_ZHONGGUANCUN_SOUTH_GATE, _http_json, amap_configured

REST_REGEO = "https://restapi.amap.com/v3/geocode/regeo"
REST_WEATHER = "https://restapi.amap.com/v3/weather/weatherInfo"

# (cache_key, expires_at, payload)
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_SEC = 10 * 60


def _key() -> str:
    return getattr(config, "AMAP_MAPS_API_KEY", "") or ""


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    hit = _CACHE.get(key)
    if not hit:
        return None
    exp, payload = hit
    if time.time() >= exp:
        _CACHE.pop(key, None)
        return None
    return dict(payload)


def _cache_set(key: str, payload: Dict[str, Any]) -> None:
    _CACHE[key] = (time.time() + CACHE_TTL_SEC, dict(payload))


def resolve_adcode(lng: float, lat: float) -> Dict[str, Any]:
    """逆地理：坐标 → adcode / 城区名。"""
    key = _key()
    if not key:
        raise RuntimeError("未配置 AMAP_MAPS_API_KEY")
    qs = urllib.parse.urlencode(
        {
            "key": key,
            "location": f"{lng:.6f},{lat:.6f}",
            "extensions": "base",
            "radius": 1000,
        }
    )
    data = _http_json(f"{REST_REGEO}?{qs}", timeout=10)
    if str(data.get("status")) != "1":
        raise RuntimeError(data.get("info") or "逆地理失败")
    regeo = data.get("regeocode") or {}
    comp = regeo.get("addressComponent") or {}
    adcode = str(comp.get("adcode") or "").strip()
    if not adcode:
        raise RuntimeError("逆地理未返回 adcode")
    city = comp.get("district") or comp.get("city") or comp.get("province") or ""
    if isinstance(city, list):
        city = city[0] if city else ""
    return {
        "adcode": adcode,
        "city": str(city or "").strip() or "当前位置",
        "formatted": str(regeo.get("formatted_address") or "").strip(),
    }


def fetch_live_weather(adcode: str) -> Dict[str, Any]:
    key = _key()
    if not key:
        raise RuntimeError("未配置 AMAP_MAPS_API_KEY")
    qs = urllib.parse.urlencode(
        {
            "key": key,
            "city": adcode,
            "extensions": "base",
            "output": "JSON",
        }
    )
    data = _http_json(f"{REST_WEATHER}?{qs}", timeout=10)
    if str(data.get("status")) != "1":
        raise RuntimeError(data.get("info") or "天气查询失败")
    lives = data.get("lives") or []
    if not lives or not isinstance(lives[0], dict):
        raise RuntimeError("天气接口无实况数据")
    live = lives[0]
    return {
        "city": str(live.get("city") or "").strip(),
        "adcode": str(live.get("adcode") or adcode).strip(),
        "weather": str(live.get("weather") or "").strip(),
        "temperature": str(live.get("temperature") or "").strip(),
        "humidity": str(live.get("humidity") or "").strip(),
        "winddirection": str(live.get("winddirection") or "").strip(),
        "windpower": str(live.get("windpower") or "").strip(),
        "reporttime": str(live.get("reporttime") or "").strip(),
    }


def weather_for_location(lng: float, lat: float, *, force: bool = False) -> Dict[str, Any]:
    """按坐标取实况天气（带 10 分钟缓存）。"""
    cache_key = f"{lng:.3f},{lat:.3f}"
    if not force:
        cached = _cache_get(cache_key)
        if cached:
            cached["cached"] = True
            return cached

    place = resolve_adcode(lng, lat)
    live = fetch_live_weather(place["adcode"])
    payload = {
        "ok": True,
        "provider": "amap",
        "cached": False,
        "lng": lng,
        "lat": lat,
        "place": place.get("city") or live.get("city") or "当前位置",
        "formatted_address": place.get("formatted") or "",
        "weather": live.get("weather") or "—",
        "temperature": live.get("temperature") or "—",
        "humidity": live.get("humidity") or "",
        "winddirection": live.get("winddirection") or "",
        "windpower": live.get("windpower") or "",
        "reporttime": live.get("reporttime") or "",
        "ttl_sec": CACHE_TTL_SEC,
    }
    wd = payload["winddirection"]
    wp = payload["windpower"]
    if wd and wp:
        payload["wind"] = f"{wd}风 {wp}级"
    elif wd:
        payload["wind"] = f"{wd}风"
    elif wp:
        payload["wind"] = f"{wp}级"
    else:
        payload["wind"] = ""
    # 文案：晴 · 26°
    temp = payload["temperature"]
    payload["summary"] = (
        f"{payload['weather']} · {temp}°"
        if temp not in ("", "—")
        else payload["weather"]
    )
    _cache_set(cache_key, payload)
    return dict(payload)


def weather_for_vehicle(nav: Optional[Dict[str, Any]] = None, *, force: bool = False) -> Dict[str, Any]:
    """从车辆导航定位取天气；无定位时用默认南门。"""
    if not amap_configured():
        return {
            "ok": False,
            "error": "未配置高德 Key",
            "summary": "天气未配置",
            "place": "",
            "weather": "",
            "temperature": "",
        }
    nav = nav or {}
    pos = nav.get("position") or {}
    lng = pos.get("lng")
    lat = pos.get("lat")
    try:
        lng_f = float(lng) if lng is not None else float(BIT_ZHONGGUANCUN_SOUTH_GATE["lng"])
        lat_f = float(lat) if lat is not None else float(BIT_ZHONGGUANCUN_SOUTH_GATE["lat"])
    except (TypeError, ValueError):
        lng_f = float(BIT_ZHONGGUANCUN_SOUTH_GATE["lng"])
        lat_f = float(BIT_ZHONGGUANCUN_SOUTH_GATE["lat"])
    try:
        return weather_for_location(lng_f, lat_f, force=force)
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "summary": "天气暂不可用",
            "place": "",
            "weather": "",
            "temperature": "",
            "lng": lng_f,
            "lat": lat_f,
        }
