# -*- coding: utf-8 -*-
"""Stub Gateway：统一读写 canonical state，修复旧版 schema 漂移。"""
from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.gateway.apps_catalog import (
    ALLOWED_APP_NAMES,
    catalog_for_prompt,
    list_apps,
    normalize_app_name,
    resolve_or_suggest,
)
from app.gateway.base import VehicleGateway
from app.gateway.state_schema import initial_vehicle_state, touch
from app.models import ALL_ZONES, FRONT_ZONES, REAR_ZONES, WINDOW_POSITIONS

ZONE_NAMES = {
    "front_left": "主驾",
    "front_right": "副驾",
    "rear_left": "左后",
    "rear_right": "右后",
    "rear_middle": "后排中间",
    "sunroof": "天窗",
}

MUSIC_LIBRARY = [
    {"artist": "王菲", "title": "红豆", "album": "唱游"},
    {"artist": "王菲", "title": "流年", "album": "王菲"},
    {"artist": "王菲", "title": "执迷不悔", "album": "执迷不悔"},
    {"artist": "王菲", "title": "矜持", "album": "天空"},
    {"artist": "周杰伦", "title": "晴天", "album": "叶惠美"},
    {"artist": "周杰伦", "title": "七里香", "album": "七里香"},
    {"artist": "周杰伦", "title": "稻香", "album": "魔杰座"},
    {"artist": "周杰伦", "title": "青花瓷", "album": "我很忙"},
    {"artist": "陈奕迅", "title": "浮夸", "album": "U87"},
    {"artist": "陈奕迅", "title": "十年", "album": "黑白灰"},
    {"artist": "陈奕迅", "title": "富士山下", "album": "What's Going On...?"},
    {"artist": "陈奕迅", "title": "K歌之王", "album": "打得火热"},
    {"artist": "邓紫棋", "title": "泡沫", "album": "Xposed"},
    {"artist": "邓紫棋", "title": "光年之外", "album": "光年之外"},
    {"artist": "邓紫棋", "title": "句号", "album": "摩天动物园"},
    {"artist": "邓紫棋", "title": "来自天堂的魔鬼", "album": "新的心跳"},
    {"artist": "林俊杰", "title": "江南", "album": "第二天堂"},
    {"artist": "林俊杰", "title": "可惜没如果", "album": "新地球"},
    {"artist": "林俊杰", "title": "修炼爱情", "album": "因你而在"},
    {"artist": "林俊杰", "title": "不为谁而作的歌", "album": "和自己对话"},
]

RADIO_STATIONS = [
    {"band": "FM", "frequency": "91.5", "station_name": "中国之声", "category": "新闻"},
    {"band": "FM", "frequency": "106.1", "station_name": "音乐之声", "category": "音乐"},
    {"band": "FM", "frequency": "103.9", "station_name": "北京交通广播", "category": "交通"},
    {"band": "FM", "frequency": "87.6", "station_name": "北京音乐广播", "category": "音乐"},
    {"band": "FM", "frequency": "101.7", "station_name": "上海音乐广播", "category": "音乐"},
    {"band": "FM", "frequency": "105.7", "station_name": "上海交通广播", "category": "交通"},
    {"band": "FM", "frequency": "94.7", "station_name": "经典947", "category": "古典"},
    {"band": "FM", "frequency": "105.2", "station_name": "广东音乐之声", "category": "音乐"},
    {"band": "AM", "frequency": "639", "station_name": "中国之声AM", "category": "新闻"},
    {"band": "FM", "frequency": "102.6", "station_name": "重庆音乐广播", "category": "音乐"},
]

def _ok(message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"success": True, "message": message, "data": data or {}}


def _fail(message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"success": False, "message": message, "data": data or {}}


def _normalize_zones(zones: Optional[List[str]], default: Optional[List[str]] = None) -> List[str]:
    if not zones:
        return list(default or ["front_left"])
    out: List[str] = []
    for z in zones:
        z = str(z).strip()
        if z in ("all", "全车"):
            return list(ALL_ZONES)
        if z in ("front", "前排"):
            out.extend(FRONT_ZONES)
            continue
        if z in ("rear", "后排"):
            out.extend(REAR_ZONES)
            continue
        if z in ALL_ZONES:
            out.append(z)
    # 去重保序
    return list(dict.fromkeys(out)) or list(default or ["front_left"])


def _zone_label(zones: List[str]) -> str:
    if set(zones) == set(ALL_ZONES):
        return "全车"
    if set(zones) == set(FRONT_ZONES):
        return "前排"
    if set(zones) == set(REAR_ZONES):
        return "后排"
    return "、".join(ZONE_NAMES.get(z, z) for z in zones)


class StubVehicleGateway(VehicleGateway):
    def __init__(self, state_file: Optional[Path] = None):
        self._lock = threading.RLock()
        self.state_file = Path(state_file) if state_file else None
        self._state = initial_vehicle_state()
        if self.state_file and self.state_file.exists():
            try:
                loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.get("meta", {}).get("version") == "V2":
                    self._state = loaded
            except Exception:
                pass
        self._persist()

    def _persist(self) -> None:
        self._state = touch(self._state)
        if not self.state_file:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def replace(self, state: Dict[str, Any]) -> None:
        with self._lock:
            self._state = deepcopy(state)
            self._persist()

    def reset(self) -> Dict[str, Any]:
        with self._lock:
            self._state = initial_vehicle_state()
            self._persist()
            return deepcopy(self._state)

    # -------- climate --------
    def climate_power(self, enable: bool, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            st = self._state
            if enable:
                targets = _normalize_zones(zones, default=ALL_ZONES if zones is None else None)
                if zones is None:
                    targets = list(ALL_ZONES)
                for z in targets:
                    st["climate"]["zones"][z]["on"] = True
                st["climate"]["power"] = True
                self._persist()
                return _ok(f"已打开{_zone_label(targets)}空调", {"zones": targets, "power": True})
            # 关闭
            if zones is None:
                for z in ALL_ZONES:
                    st["climate"]["zones"][z]["on"] = False
                st["climate"]["power"] = False
                self._persist()
                return _ok("已关闭全车空调", {"power": False})
            targets = _normalize_zones(zones)
            for z in targets:
                st["climate"]["zones"][z]["on"] = False
            st["climate"]["power"] = any(st["climate"]["zones"][z]["on"] for z in ALL_ZONES)
            self._persist()
            return _ok(f"已关闭{_zone_label(targets)}空调", {"zones": targets, "power": st["climate"]["power"]})

    def climate_set_temp(self, temperature: float, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            temp = max(16.0, min(30.0, float(temperature)))
            st = self._state
            if zones is None:
                on_zones = [z for z in ALL_ZONES if st["climate"]["zones"][z]["on"]]
                targets = on_zones or ["front_left"]
            else:
                targets = _normalize_zones(zones)
            auto_on = False
            if not st["climate"]["power"]:
                st["climate"]["power"] = True
                auto_on = True
            for z in targets:
                st["climate"]["zones"][z]["temp"] = temp
                st["climate"]["zones"][z]["on"] = True
            self._persist()
            prefix = "空调已自动开启，" if auto_on else ""
            return _ok(f"{prefix}{_zone_label(targets)}温度已设为{temp:.0f}°C", {"temperature": temp, "zones": targets})

    def climate_adjust_temp(self, delta: float, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            st = self._state
            if zones is None:
                on_zones = [z for z in ALL_ZONES if st["climate"]["zones"][z]["on"]]
                targets = on_zones or ["front_left"]
            else:
                targets = _normalize_zones(zones)
            # 用第一个区域当前温度做基准展示
            base = st["climate"]["zones"][targets[0]]["temp"]
            new_temp = max(16.0, min(30.0, float(base) + float(delta)))
        return self.climate_set_temp(new_temp, targets)

    def climate_set_fan(self, level: int, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            level = max(0, min(5, int(level)))
            st = self._state
            if zones is None:
                on_zones = [z for z in ALL_ZONES if st["climate"]["zones"][z]["on"]]
                targets = on_zones or ["front_left"]
            else:
                targets = _normalize_zones(zones)
            if not st["climate"]["power"]:
                st["climate"]["power"] = True
            for z in targets:
                st["climate"]["zones"][z]["fan"] = level
                st["climate"]["zones"][z]["on"] = True if level > 0 else st["climate"]["zones"][z]["on"]
            self._persist()
            return _ok(f"{_zone_label(targets)}风量已调至{level}档", {"level": level, "zones": targets})

    def climate_set_mode(self, mode: str, recirculation: Optional[bool] = None) -> Dict[str, Any]:
        with self._lock:
            mode = str(mode).lower()
            allowed = {"auto", "eco", "comfort", "heat", "cool"}
            if mode not in allowed:
                return _fail(f"不支持的空调模式: {mode}")
            self._state["climate"]["mode"] = mode
            self._state["climate"]["power"] = True
            if recirculation is not None:
                self._state["climate"]["recirculation"] = bool(recirculation)
            self._persist()
            return _ok(f"空调模式已切换为{mode}", {"mode": mode})

    # -------- seats --------
    def seat_set(self, feature: str, enable: bool, level: int = 2, positions: Optional[List[str]] = None, mode: str = "normal") -> Dict[str, Any]:
        with self._lock:
            feature = feature.lower()
            if feature not in {"heat", "ventilation", "massage"}:
                return _fail(f"不支持的座椅功能: {feature}")
            positions = _normalize_zones(positions, default=["front_left"])
            level = 0 if not enable else max(1, min(3, int(level or 2)))
            names = {"heat": "加热", "ventilation": "通风", "massage": "按摩"}
            for p in positions:
                node = self._state["seats"][feature][p]
                node["enable"] = bool(enable)
                node["level"] = level
                if feature == "massage":
                    node["mode"] = mode or "normal"
            self._persist()
            action = "已开启" if enable else "已关闭"
            return _ok(f"{_zone_label(positions)}座椅{names[feature]}{action}", {"feature": feature, "positions": positions, "level": level, "enable": enable})

    def steering_wheel_heat(self, enable: bool, level: int = 2) -> Dict[str, Any]:
        with self._lock:
            level = 0 if not enable else max(1, min(3, int(level or 2)))
            self._state["seats"]["steering_wheel_heat"] = {"enable": bool(enable), "level": level}
            self._persist()
            return _ok("方向盘加热已开启" if enable else "方向盘加热已关闭", {"enable": enable, "level": level})

    # -------- cabin --------
    def set_windows(self, percent: int, positions: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            percent = max(0, min(100, int(percent)))
            if not positions:
                positions = ["front_left"]
            cleaned = []
            for p in positions:
                if p in ("all", "全车"):
                    cleaned = list(WINDOW_POSITIONS)
                    break
                if p == "sunroof" or p in WINDOW_POSITIONS:
                    cleaned.append(p)
            cleaned = list(dict.fromkeys(cleaned)) or ["front_left"]
            for p in cleaned:
                self._state["cabin"]["windows"].setdefault(p, {"percent": 0})["percent"] = percent
            self._persist()
            label = "全车车窗" if set(cleaned) == set(WINDOW_POSITIONS) else "、".join(ZONE_NAMES.get(p, p) for p in cleaned)
            if percent == 0:
                msg = f"{label}已关闭"
            elif percent >= 95:
                msg = f"{label}已完全打开"
            else:
                msg = f"{label}已调节至{percent}%"
            return _ok(msg, {"positions": cleaned, "percent": percent})

    def adjust_windows(self, delta: int, positions: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            if not positions:
                positions = ["front_left"]
            cur = self._state["cabin"]["windows"].get(positions[0], {"percent": 0}).get("percent", 0)
            return self.set_windows(int(cur) + int(delta), positions)

    def set_door_locks(self, locked: bool, positions: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            if not positions:
                positions = ["front_left"]
            cleaned = []
            for p in positions:
                if p in ("all", "全车"):
                    cleaned = ["front_left", "front_right", "rear_left", "rear_right"]
                    break
                if p in {"front_left", "front_right", "rear_left", "rear_right"}:
                    cleaned.append(p)
            cleaned = list(dict.fromkeys(cleaned)) or ["front_left"]
            for p in cleaned:
                self._state["cabin"]["doors"][p] = {"locked": bool(locked)}
            self._persist()
            label = "全车车门" if len(cleaned) == 4 else "、".join(ZONE_NAMES.get(p, p) for p in cleaned)
            return _ok(f"{label}已{'上锁' if locked else '解锁'}", {"positions": cleaned, "locked": locked})

    def set_trunk(self, open_: bool) -> Dict[str, Any]:
        with self._lock:
            self._state["cabin"]["trunk"]["open"] = bool(open_)
            self._persist()
            return _ok("后备箱已打开" if open_ else "后备箱已关闭", {"open": open_})

    def set_light(self, target: str, enable: Optional[bool] = None, brightness: Optional[int] = None, color: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            lights = self._state["cabin"]["lights"]
            if target not in lights:
                return _fail(f"未知灯光目标: {target}")
            node = lights[target]
            if enable is not None:
                node["enable"] = bool(enable)
                if enable and node.get("brightness", 0) == 0:
                    node["brightness"] = 50
                if not enable:
                    node["brightness"] = 0
            if brightness is not None:
                node["brightness"] = max(0, min(100, int(brightness)))
                node["enable"] = node["brightness"] > 0
            if color and target == "ambient":
                node["color"] = color
            self._persist()
            return _ok(f"{target}灯光已更新", {"target": target, **node})

    def set_display_brightness(self, target: str, brightness: int) -> Dict[str, Any]:
        with self._lock:
            displays = self._state["cabin"]["displays"]
            if target not in displays:
                return _fail(f"未知屏幕: {target}")
            brightness = max(0, min(100, int(brightness)))
            displays[target] = {"brightness": brightness}
            self._persist()
            return _ok(f"{target}亮度已设为{brightness}%", {"target": target, "brightness": brightness})

    # -------- media --------
    def _find_song(self, artist: Optional[str], title: Optional[str]):
        artist = (artist or "").strip()
        title = (title or "").strip()
        for i, song in enumerate(MUSIC_LIBRARY):
            if artist and title:
                if song["artist"] == artist and song["title"] == title:
                    return i, song
            elif artist and song["artist"] == artist:
                return i, song
            elif title and song["title"] == title:
                return i, song
        return -1, None

    def play_music(self, artist: Optional[str] = None, title: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            idx, song = self._find_song(artist, title)
            if not song:
                return _fail("音乐库里没有这首歌，请换一首试试")
            self._state["media"]["radio"]["playing"] = False
            self._state["media"]["music"] = {
                "playing": True,
                "artist": song["artist"],
                "title": song["title"],
                "album": song["album"],
                "index": idx,
            }
            self._persist()
            return _ok(f"正在播放 {song['artist']} - {song['title']}", song)

    def control_music(self, action: str) -> Dict[str, Any]:
        with self._lock:
            action = action.lower()
            music = self._state["media"]["music"]
            if action == "play":
                if music.get("index", -1) < 0:
                    return self.play_music("周杰伦", "晴天")
                music["playing"] = True
                self._persist()
                return _ok(f"继续播放 {music.get('artist')} - {music.get('title')}", music)
            if action == "pause":
                music["playing"] = False
                self._persist()
                return _ok("音乐已暂停", music)
            if action == "stop":
                music["playing"] = False
                self._persist()
                return _ok("音乐已停止", music)
            return _fail(f"不支持的音乐操作: {action}")

    def switch_music(self, direction: str) -> Dict[str, Any]:
        with self._lock:
            direction = direction.lower()
            cur = self._state["media"]["music"].get("index", -1)
            if cur < 0:
                cur = 0
            if direction in {"next", "下一首"}:
                cur = (cur + 1) % len(MUSIC_LIBRARY)
            else:
                cur = (cur - 1) % len(MUSIC_LIBRARY)
            song = MUSIC_LIBRARY[cur]
            self._state["media"]["music"] = {
                "playing": True,
                "artist": song["artist"],
                "title": song["title"],
                "album": song["album"],
                "index": cur,
            }
            self._persist()
            return _ok(f"已切换到 {song['artist']} - {song['title']}", song)

    def play_radio(self, station_name: Optional[str] = None, category: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            station = None
            idx = -1
            for i, s in enumerate(RADIO_STATIONS):
                if station_name and s["station_name"] == station_name:
                    station, idx = s, i
                    break
                if category and s["category"] == category and station is None:
                    station, idx = s, i
            if station is None:
                station, idx = RADIO_STATIONS[0], 0
            self._state["media"]["music"]["playing"] = False
            self._state["media"]["radio"] = {
                "playing": True,
                "band": station["band"],
                "frequency": station["frequency"],
                "station_name": station["station_name"],
                "index": idx,
            }
            self._persist()
            return _ok(f"正在收听 {station['station_name']} {station['band']}{station['frequency']}", station)

    def control_radio(self, action: str) -> Dict[str, Any]:
        with self._lock:
            action = action.lower()
            radio = self._state["media"]["radio"]
            if action == "stop":
                radio["playing"] = False
                self._persist()
                return _ok("电台已停止", radio)
            if action == "play":
                if radio.get("index", -1) < 0:
                    return self.play_radio()
                radio["playing"] = True
                self._persist()
                return _ok(f"继续收听 {radio.get('station_name')}", radio)
            return _fail(f"不支持的电台操作: {action}")

    def set_volume(self, volume: Optional[int] = None, delta: Optional[int] = None, muted: Optional[bool] = None) -> Dict[str, Any]:
        with self._lock:
            media = self._state["media"]
            if muted is not None:
                media["muted"] = bool(muted)
            if volume is not None:
                media["volume"] = max(0, min(100, int(volume)))
            elif delta is not None:
                media["volume"] = max(0, min(100, int(media.get("volume", 50)) + int(delta)))
            self._persist()
            if media["muted"]:
                return _ok("已静音", media)
            return _ok(f"音量已设为{media['volume']}", {"volume": media["volume"], "muted": media["muted"]})

    # -------- nav / driving / apps --------
    def navigate_to(self, destination: str, preference: str = "fastest") -> Dict[str, Any]:
        with self._lock:
            destination = (destination or "").strip()
            if not destination:
                return _fail("请告诉我目的地")
            self._state["navigation"] = {
                "navigating": True,
                "destination": destination,
                "preference": preference or "fastest",
                "eta_min": 28,
                "traffic": "缓行",
            }
            self._persist()
            return _ok(f"已开始导航前往{destination}，预计28分钟", self._state["navigation"])

    def stop_navigation(self) -> Dict[str, Any]:
        with self._lock:
            self._state["navigation"] = {
                "navigating": False,
                "destination": None,
                "preference": "fastest",
                "eta_min": None,
                "traffic": None,
            }
            self._persist()
            return _ok("已结束导航", self._state["navigation"])

    def set_adas(self, feature: str, enable: bool) -> Dict[str, Any]:
        with self._lock:
            mapping = {
                "autohold": "auto_hold",
                "auto_hold": "auto_hold",
                "cruise": "acc",
                "acc": "acc",
                "autopark": "autopark",
                "auto_park": "autopark",
                "lane_keep": "lane_keep",
                "collision_warning": "collision_warning",
            }
            key = mapping.get(feature.lower())
            if not key:
                return _fail(f"未知ADAS功能: {feature}")
            self._state["driving"]["adas"][key] = bool(enable)
            self._persist()
            names = {
                "auto_hold": "自动驻车",
                "acc": "自适应巡航",
                "autopark": "自动泊车",
                "lane_keep": "车道保持",
                "collision_warning": "碰撞预警",
            }
            return _ok(f"{names[key]}已{'开启' if enable else '关闭'}", {"feature": key, "enable": enable})

    def set_drive_mode(self, mode: str) -> Dict[str, Any]:
        with self._lock:
            mode = mode.lower()
            if mode not in {"comfort", "sport", "eco", "standard"}:
                return _fail(f"不支持的驾驶模式: {mode}")
            self._state["driving"]["mode"] = mode
            self._persist()
            return _ok(f"驾驶模式已切换为{mode}", {"mode": mode})

    def launch_app(self, app_name: str, enable: bool = True) -> Dict[str, Any]:
        with self._lock:
            resolved = resolve_or_suggest(app_name)
            if not resolved.get("ok"):
                return _fail(resolved["message"], {"available": resolved.get("available")})
            app_name = resolved["app_name"]
            running = self._state["apps"].setdefault("running", [])
            installed = self._state["apps"].setdefault("installed", sorted(ALLOWED_APP_NAMES))
            if not installed:
                self._state["apps"]["installed"] = sorted(ALLOWED_APP_NAMES)
            if enable:
                if app_name not in running:
                    running.append(app_name)
                self._state["apps"]["active"] = app_name
                self._persist()
                return _ok(f"已打开{app_name}", {"active": app_name, "app_name": app_name})
            if app_name in running:
                running.remove(app_name)
            if self._state["apps"].get("active") == app_name:
                self._state["apps"]["active"] = running[-1] if running else None
            self._persist()
            return _ok(f"已关闭{app_name}", {"active": self._state["apps"]["active"], "app_name": app_name})

    def set_assistant(self, persona: Optional[str] = None, speech_rate: Optional[str] = None, scene: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            a = self._state["assistant"]
            if persona:
                a["persona"] = persona
            if speech_rate:
                a["speech_rate"] = speech_rate
            if scene is not None:
                a["scene"] = scene
            self._persist()
            return _ok("助手设置已更新", a)
