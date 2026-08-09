# -*- coding: utf-8 -*-
"""
Media Skill Handler - 20首本地音乐库 + 10个电台 V5

核心功能：
- 维护20首本地音乐库
- 维护10个预设电台
- 播放时校验歌曲/电台是否在库中
- 音乐播放控制和切换分离
- 电台控制和切换分离
- 音量控制
"""

import json
import os
from typing import Dict, Any, List, Optional


# ================= 本地音乐库 (20首) =================
LOCAL_MUSIC_LIBRARY = [
    # 王菲 (4首)
    {"artist": "王菲", "title": "红豆", "album": "唱游"},
    {"artist": "王菲", "title": "流年", "album": "王菲"},
    {"artist": "王菲", "title": "执迷不悔", "album": "执迷不悔"},
    {"artist": "王菲", "title": "矜持", "album": "天空"},
    
    # 周杰伦 (4首)
    {"artist": "周杰伦", "title": "晴天", "album": "叶惠美"},
    {"artist": "周杰伦", "title": "七里香", "album": "七里香"},
    {"artist": "周杰伦", "title": "稻香", "album": "魔杰座"},
    {"artist": "周杰伦", "title": "青花瓷", "album": "我很忙"},
    
    # 陈奕迅 (4首)
    {"artist": "陈奕迅", "title": "浮夸", "album": "U87"},
    {"artist": "陈奕迅", "title": "十年", "album": "黑白灰"},
    {"artist": "陈奕迅", "title": "富士山下", "album": "What's Going On...?"},
    {"artist": "陈奕迅", "title": "K歌之王", "album": "打得火热"},
    
    # 邓紫棋 (4首)
    {"artist": "邓紫棋", "title": "泡沫", "album": "Xposed"},
    {"artist": "邓紫棋", "title": "光年之外", "album": "光年之外"},
    {"artist": "邓紫棋", "title": "句号", "album": "摩天动物园"},
    {"artist": "邓紫棋", "title": "来自天堂的魔鬼", "album": "新的心跳"},
    
    # 林俊杰 (4首)
    {"artist": "林俊杰", "title": "江南", "album": "第二天堂"},
    {"artist": "林俊杰", "title": "可惜没如果", "album": "新地球"},
    {"artist": "林俊杰", "title": "修炼爱情", "album": "因你而在"},
    {"artist": "林俊杰", "title": "不为谁而作的歌", "album": "和自己对话"},
]


# ================= 预设电台列表 (10个) =================
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


def find_song_in_library(artist: str = None, title: str = None) -> Optional[Dict[str, str]]:
    """在音乐库中查找歌曲"""
    if not artist and not title:
        return None
    
    for song in LOCAL_MUSIC_LIBRARY:
        match_artist = True
        match_title = True
        
        if artist:
            match_artist = song["artist"] == artist
        if title:
            match_title = song["title"] == title
        
        if match_artist and match_title:
            return song
    
    return None


def find_songs_by_artist(artist: str) -> List[Dict[str, str]]:
    """查找某歌手的所有歌曲"""
    return [s for s in LOCAL_MUSIC_LIBRARY if s["artist"] == artist]


def get_current_song_index(artist: str, title: str) -> int:
    """获取当前歌曲在音乐库中的索引"""
    for i, song in enumerate(LOCAL_MUSIC_LIBRARY):
        if song["artist"] == artist and song["title"] == title:
            return i
    return -1


def find_radio_station(band: str = None, frequency: str = None, station_name: str = None) -> Optional[Dict[str, str]]:
    """在电台列表中查找电台"""
    for station in RADIO_STATIONS:
        match_band = True
        match_freq = True
        match_name = True
        
        if band:
            match_band = station["band"] == band.upper()
        if frequency:
            match_freq = station["frequency"] == frequency
        if station_name:
            match_name = station["station_name"] == station_name
        
        if match_band and match_freq and match_name:
            return station
    
    return None


def find_radio_by_category(category: str) -> List[Dict[str, str]]:
    """按类别查找电台"""
    return [s for s in RADIO_STATIONS if s["category"] == category]


def get_current_radio_index(band: str, frequency: str) -> int:
    """获取当前电台在列表中的索引"""
    for i, station in enumerate(RADIO_STATIONS):
        if station["band"] == band and station["frequency"] == frequency:
            return i
    return -1


# ================= 状态读写工具 =================
def load_state(state_file: str) -> Dict[str, Any]:
    """从 state.json 加载状态"""
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[Media] 加载状态失败: {e}")
    return {}


def save_state(state_file: str, state: Dict[str, Any]) -> bool:
    """保存状态到 state.json"""
    try:
        if "meta" in state:
            from datetime import datetime
            state["meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[Media] 保存状态失败: {e}")
        return False


def get_media_state(full_state: Dict) -> Dict[str, Any]:
    """获取 media 部分的当前状态"""
    return full_state.get("media", {
        "music_control": {
            "action": "stop",
            "source": "local",
            "artist": None,
            "title": None,
            "album": None,
            "playing": False
        },
        "music_switch": {
            "direction": None,
            "current_index": -1
        },
        "radio_control": {
            "action": "stop",
            "band": None,
            "frequency": None,
            "station_name": None,
            "category": None,
            "playing": False
        },
        "radio_switch": {
            "direction": None,
            "current_index": -1
        },
        "volume_control": {
            "volume": 50,
            "muted": False
        }
    })


# ================= 核心函数 =================
def music_control(
    state_file: str,
    action: str = "play",
    source: str = "local",
    artist: str = None,
    title: str = None,
    album: str = None
) -> Dict[str, Any]:
    """音乐播放控制（仅支持 play/pause/stop）"""
    
    full_state = load_state(state_file)
    media_state = get_media_state(full_state)
    music_state = media_state.get("music_control", {})
    switch_state = media_state.get("music_switch", {})
    
    new_music_state = dict(music_state)
    new_music_state["action"] = action
    new_music_state["source"] = source or music_state.get("source", "local")
    
    if action == "play":
        if source == "local" or source is None:
            song = find_song_in_library(artist, title)
            
            if not song:
                if artist and not title:
                    songs = find_songs_by_artist(artist)
                    if songs:
                        song = songs[0]
                    else:
                        return {
                            "success": False,
                            "message": f"对不起，音乐库里没有「{artist}」的歌曲",
                            "data": None
                        }
                elif title and not artist:
                    return {
                        "success": False,
                        "message": f"对不起，音乐库里没有「{title}」这首歌",
                        "data": None
                    }
                else:
                    search_info = ""
                    if artist:
                        search_info += f"「{artist}」"
                    if title:
                        search_info += f"「{title}」"
                    return {
                        "success": False,
                        "message": f"对不起，音乐库里没有{search_info}这首歌",
                        "data": None
                    }
            
            new_music_state["artist"] = song["artist"]
            new_music_state["title"] = song["title"]
            new_music_state["album"] = song["album"]
            new_music_state["playing"] = True
            
            # 同步更新 switch 状态的 current_index
            current_index = get_current_song_index(song["artist"], song["title"])
            media_state["music_switch"] = {**switch_state, "current_index": current_index}
            
            msg = f"正在播放：{song['artist']}的《{song['title']}》(专辑：《{song['album']}》)"
        
        else:  # USB音乐
            new_music_state["playing"] = True
            if artist:
                new_music_state["artist"] = artist
            if title:
                new_music_state["title"] = title
            if album:
                new_music_state["album"] = album
            
            song_info = ""
            if artist and title:
                song_info = f"{artist}的《{title}》"
            elif artist:
                song_info = f"{artist}的歌曲"
            elif title:
                song_info = f"《{title}》"
            else:
                song_info = "USB音乐"
            
            msg = f"正在播放USB音乐：{song_info}"
    
    elif action == "pause":
        new_music_state["playing"] = False
        msg = "音乐已暂停"
    
    elif action == "stop":
        new_music_state["playing"] = False
        msg = "音乐已停止"
    
    else:
        return {
            "success": False,
            "message": f"music_control 不支持的操作：{action}（请使用 music_switch 进行切换）",
            "data": None
        }
    
    media_state["music_control"] = new_music_state
    full_state["media"] = media_state
    save_state(state_file, full_state)
    
    return {
        "success": True,
        "message": msg,
        "data": {
            "action": action,
            "source": new_music_state["source"],
            "artist": new_music_state.get("artist"),
            "title": new_music_state.get("title"),
            "album": new_music_state.get("album"),
            "playing": new_music_state["playing"]
        }
    }


def music_switch(
    state_file: str,
    direction: str = "next"
) -> Dict[str, Any]:
    """音乐切换（上一首/下一首）"""
    
    full_state = load_state(state_file)
    media_state = get_media_state(full_state)
    music_state = media_state.get("music_control", {})
    switch_state = media_state.get("music_switch", {})
    
    # 获取当前索引
    current_index = switch_state.get("current_index", -1)
    
    if direction == "prev":
        if current_index > 0:
            new_index = current_index - 1
            song = LOCAL_MUSIC_LIBRARY[new_index]
            msg = f"上一首：{song['artist']}的《{song['title']}》"
        else:
            # 循环到末尾
            new_index = len(LOCAL_MUSIC_LIBRARY) - 1
            song = LOCAL_MUSIC_LIBRARY[new_index]
            msg = f"上一首：{song['artist']}的《{song['title']}》(已循环到末尾)"
    
    elif direction == "next":
        if 0 <= current_index < len(LOCAL_MUSIC_LIBRARY) - 1:
            new_index = current_index + 1
            song = LOCAL_MUSIC_LIBRARY[new_index]
            msg = f"下一首：{song['artist']}的《{song['title']}》"
        else:
            # 循环到开头
            new_index = 0
            song = LOCAL_MUSIC_LIBRARY[new_index]
            msg = f"下一首：{song['artist']}的《{song['title']}》(已循环到开头)"
    
    else:
        return {
            "success": False,
            "message": f"不支持的切换方向：{direction}（仅支持 prev/next）",
            "data": None
        }
    
    # 更新 music_control 状态
    new_music_state = dict(music_state)
    new_music_state["action"] = "play"
    new_music_state["source"] = music_state.get("source", "local")
    new_music_state["artist"] = song["artist"]
    new_music_state["title"] = song["title"]
    new_music_state["album"] = song["album"]
    new_music_state["playing"] = True
    
    # 更新 switch 状态
    new_switch_state = {
        "direction": direction,
        "current_index": new_index
    }
    
    media_state["music_control"] = new_music_state
    media_state["music_switch"] = new_switch_state
    full_state["media"] = media_state
    save_state(state_file, full_state)
    
    return {
        "success": True,
        "message": msg,
        "data": {
            "direction": direction,
            "current_index": new_index,
            "artist": song["artist"],
            "title": song["title"],
            "album": song["album"]
        }
    }


def radio_control(
    state_file: str,
    action: str = "play",
    band: str = None,
    frequency: str = None,
    station_name: str = None,
    category: str = None
) -> Dict[str, Any]:
    """广播收听控制（仅支持 play/pause/stop）"""
    
    full_state = load_state(state_file)
    media_state = get_media_state(full_state)
    radio_state = media_state.get("radio_control", {})
    switch_state = media_state.get("radio_switch", {})
    
    new_radio_state = dict(radio_state)
    new_radio_state["action"] = action
    
    if action == "play":
        # 查找电台
        station = None
        
        if station_name or (band and frequency):
            station = find_radio_station(band, frequency, station_name)
        elif category:
            stations = find_radio_by_category(category)
            if stations:
                station = stations[0]
        
        if not station and (band or frequency or station_name):
            # 用户明确指定了电台但未找到
            search_info = ""
            if station_name:
                search_info = f"「{station_name}」"
            elif band and frequency:
                search_info = f"「{band}{frequency}」"
            return {
                "success": False,
                "message": f"对不起，没有{search_info}这个电台",
                "data": None
            }
        
        if station:
            new_radio_state["band"] = station["band"]
            new_radio_state["frequency"] = station["frequency"]
            new_radio_state["station_name"] = station["station_name"]
            new_radio_state["category"] = station["category"]
            new_radio_state["playing"] = True
            
            # 同步更新 switch 状态的 current_index
            current_index = get_current_radio_index(station["band"], station["frequency"])
            media_state["radio_switch"] = {**switch_state, "current_index": current_index}
            
            msg = f"正在收听：{station['station_name']} ({station['band']}{station['frequency']})"
        else:
            # 没有指定，播放当前电台或第一个
            current_idx = switch_state.get("current_index", -1)
            if current_idx >= 0:
                station = RADIO_STATIONS[current_idx]
                new_radio_state["playing"] = True
                msg = f"正在收听：{station['station_name']} ({station['band']}{station['frequency']})"
            else:
                station = RADIO_STATIONS[0]
                new_radio_state["band"] = station["band"]
                new_radio_state["frequency"] = station["frequency"]
                new_radio_state["station_name"] = station["station_name"]
                new_radio_state["category"] = station["category"]
                new_radio_state["playing"] = True
                media_state["radio_switch"] = {**switch_state, "current_index": 0}
                msg = f"正在收听：{station['station_name']} ({station['band']}{station['frequency']})"
    
    elif action == "pause":
        new_radio_state["playing"] = False
        msg = "广播已暂停"
    
    elif action == "stop":
        new_radio_state["playing"] = False
        msg = "广播已停止"
    
    else:
        return {
            "success": False,
            "message": f"radio_control 不支持的操作：{action}（请使用 radio_switch 进行切换）",
            "data": None
        }
    
    media_state["radio_control"] = new_radio_state
    full_state["media"] = media_state
    save_state(state_file, full_state)
    
    return {
        "success": True,
        "message": msg,
        "data": {
            "action": action,
            "band": new_radio_state.get("band"),
            "frequency": new_radio_state.get("frequency"),
            "station_name": new_radio_state.get("station_name"),
            "category": new_radio_state.get("category"),
            "playing": new_radio_state["playing"]
        }
    }


def radio_switch(
    state_file: str,
    direction: str = "next"
) -> Dict[str, Any]:
    """电台切换（上一个/下一个）"""
    
    full_state = load_state(state_file)
    media_state = get_media_state(full_state)
    radio_state = media_state.get("radio_control", {})
    switch_state = media_state.get("radio_switch", {})
    
    # 获取当前索引
    current_index = switch_state.get("current_index", -1)
    
    if direction == "prev":
        if current_index > 0:
            new_index = current_index - 1
            station = RADIO_STATIONS[new_index]
            msg = f"上一个电台：{station['station_name']}"
        else:
            # 循环到末尾
            new_index = len(RADIO_STATIONS) - 1
            station = RADIO_STATIONS[new_index]
            msg = f"上一个电台：{station['station_name']}(已循环到末尾)"
    
    elif direction == "next":
        if 0 <= current_index < len(RADIO_STATIONS) - 1:
            new_index = current_index + 1
            station = RADIO_STATIONS[new_index]
            msg = f"下一个电台：{station['station_name']}"
        else:
            # 循环到开头
            new_index = 0
            station = RADIO_STATIONS[new_index]
            msg = f"下一个电台：{station['station_name']}(已循环到开头)"
    
    else:
        return {
            "success": False,
            "message": f"不支持的切换方向：{direction}（仅支持 prev/next）",
            "data": None
        }
    
    # 更新 radio_control 状态
    new_radio_state = dict(radio_state)
    new_radio_state["action"] = "play"
    new_radio_state["band"] = station["band"]
    new_radio_state["frequency"] = station["frequency"]
    new_radio_state["station_name"] = station["station_name"]
    new_radio_state["category"] = station["category"]
    new_radio_state["playing"] = True
    
    # 更新 switch 状态
    new_switch_state = {
        "direction": direction,
        "current_index": new_index
    }
    
    media_state["radio_control"] = new_radio_state
    media_state["radio_switch"] = new_switch_state
    full_state["media"] = media_state
    save_state(state_file, full_state)
    
    return {
        "success": True,
        "message": msg,
        "data": {
            "direction": direction,
            "current_index": new_index,
            "band": station["band"],
            "frequency": station["frequency"],
            "station_name": station["station_name"],
            "category": station["category"]
        }
    }


def volume_control(
    state_file: str,
    action: str = "adjust",
    value: int = 50
) -> Dict[str, Any]:
    """音量控制 - 统一控制系统音量"""
    
    full_state = load_state(state_file)
    media_state = get_media_state(full_state)
    volume_state = media_state.get("volume_control", {
        "volume": 50, "muted": False
    })
    
    new_volume_state = dict(volume_state)
    current_value = new_volume_state.get("volume", 50)
    
    if action == "adjust":
        # 直接设置到指定值
        new_value = max(0, min(100, value))
        new_volume_state["volume"] = new_value
        new_volume_state["muted"] = False
        msg = f"音量已调到{new_value}"
        
    elif action == "up":
        # 增加音量（推荐+20）
        new_value = min(100, current_value + 20)
        new_volume_state["volume"] = new_value
        new_volume_state["muted"] = False
        msg = f"音量已增加到{new_value}"
        
    elif action == "down":
        # 减少音量（推荐-20）
        new_value = max(0, current_value - 20)
        new_volume_state["volume"] = new_value
        if new_value == 0:
            new_volume_state["muted"] = True
            msg = f"音量已减少到0（静音）"
        else:
            new_volume_state["muted"] = False
            msg = f"音量已减少到{new_value}"
            
    elif action == "mute":
        # 静音
        new_volume_state["muted"] = True
        msg = f"已静音"
        
    elif action == "unmute":
        # 取消静音
        new_volume_state["muted"] = False
        msg = f"已取消静音，当前音量为{current_value}"
        
    else:
        return {
            "success": False,
            "message": f"不支持的音量操作：{action}",
            "data": None
        }
    
    media_state["volume_control"] = new_volume_state
    full_state["media"] = media_state
    save_state(state_file, full_state)
    
    return {
        "success": True,
        "message": msg,
        "data": {
            "action": action,
            "volume": new_volume_state["volume"],
            "muted": new_volume_state["muted"]
        }
    }


# ================= 统一执行入口 =================
def execute(script: str, params: Dict[str, Any], state_file: str) -> Dict[str, Any]:
    """统一执行入口"""
    params_with_state = {"state_file": state_file, **params}
    
    scripts = {
        "music_control": music_control,
        "music_switch": music_switch,
        "radio_control": radio_control,
        "radio_switch": radio_switch,
        "volume_control": volume_control,
    }
    
    handler = scripts.get(script)
    if not handler:
        return {
            "success": False,
            "message": f"Media Skill 不支持 script: {script}",
            "data": None
        }
    
    try:
        return handler(**params_with_state)
    except Exception as e:
        import traceback
        return {
            "success": False,
            "message": f"执行失败: {str(e)}",
            "data": {"traceback": traceback.format_exc()}
        }


# ================= 测试 =================
if __name__ == "__main__":
    import tempfile
    
    test_state = {
        "meta": {"version": "2.0", "last_updated": "2026-03-18T22:00:00"},
        "media": {
            "music_control": {
                "action": "stop",
                "source": "local",
                "artist": None,
                "title": None,
                "album": None,
                "playing": False
            },
            "music_switch": {
                "direction": None,
                "current_index": -1
            },
            "radio_control": {
                "action": "stop",
                "band": None,
                "frequency": None,
                "station_name": None,
                "category": None,
                "playing": False
            },
            "radio_switch": {
                "direction": None,
                "current_index": -1
            },
            "volume_control": {
                "volume": 50,
                "muted": False
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(test_state, f, ensure_ascii=False, indent=2)
        test_file = f.name
    
    print("=" * 60)
    print("Media Handler V5 - 20首音乐 + 10个电台 测试")
    print("=" * 60)
    
    tests = [
        {"script": "music_control", "params": {"action": "play", "artist": "王菲", "title": "流年"}, "desc": "播放王菲的流年"},
        {"script": "music_switch", "params": {"direction": "next"}, "desc": "下一首"},
        {"script": "music_switch", "params": {"direction": "prev"}, "desc": "上一首"},
        {"script": "radio_control", "params": {"action": "play", "station_name": "中国之声"}, "desc": "播放中国之声"},
        {"script": "radio_switch", "params": {"direction": "next"}, "desc": "下一个电台"},
        {"script": "radio_switch", "params": {"direction": "prev"}, "desc": "上一个电台"},
        {"script": "radio_control", "params": {"action": "play", "category": "音乐"}, "desc": "播放音乐类电台"},
        {"script": "volume_control", "params": {"action": "adjust", "value": 60}, "desc": "音量调到60"},
        {"script": "volume_control", "params": {"action": "up"}, "desc": "增加音量"},
        {"script": "volume_control", "params": {"action": "down"}, "desc": "减少音量"},
        {"script": "volume_control", "params": {"action": "mute"}, "desc": "静音"},
    ]
    
    for case in tests:
        print(f"\n[测试] {case['desc']}")
        result = execute(case["script"], case["params"], test_file)
        print(f"  [{'OK' if result['success'] else 'ERR'}] {result['message']}")
    
    os.unlink(test_file)
    print("\n测试完成!")
