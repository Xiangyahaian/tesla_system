# -*- coding: utf-8 -*-
"""全部车载 Tool 定义：Pydantic 契约 + Gateway 调用。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.gateway.apps_catalog import catalog_for_prompt
from app.gateway.base import VehicleGateway
from app.models import RiskLevel
from app.tools.registry import ToolRegistry, ToolSpec


# ---------- args models ----------
class ClimatePowerArgs(BaseModel):
    enable: bool = Field(..., description="true=打开空调, false=关闭")
    zones: Optional[List[str]] = Field(None, description="区域列表，如 front_left/rear_left；不传则全车")


class ClimateTempArgs(BaseModel):
    temperature: float = Field(..., description="目标温度 16-30", ge=16, le=30)
    zones: Optional[List[str]] = Field(None, description="区域列表")


class ClimateAdjustTempArgs(BaseModel):
    delta: float = Field(..., description="相对调温，如 -2 表示降2度")
    zones: Optional[List[str]] = Field(None, description="区域列表")


class ClimateFanArgs(BaseModel):
    level: int = Field(..., description="风量档位 0-5", ge=0, le=5)
    zones: Optional[List[str]] = Field(None, description="区域列表")


class ClimateModeArgs(BaseModel):
    mode: str = Field(..., description="auto/eco/comfort/heat/cool")
    recirculation: Optional[bool] = Field(None, description="是否内循环")


class SeatArgs(BaseModel):
    feature: str = Field(..., description="heat/ventilation/massage")
    enable: bool = Field(...)
    level: int = Field(2, ge=0, le=3)
    positions: Optional[List[str]] = None
    mode: str = Field("normal", description="按摩模式，仅 massage 有效")


class WheelHeatArgs(BaseModel):
    enable: bool
    level: int = Field(2, ge=0, le=3)


class WindowArgs(BaseModel):
    percent: int = Field(..., ge=0, le=100, description="开合百分比，0关闭100全开")
    positions: Optional[List[str]] = Field(
        None,
        description="front_left/front_right/rear_left/rear_right/sunroof；天窗必须用 sunroof；all=四侧窗不含天窗",
    )


class WindowAdjustArgs(BaseModel):
    delta: int = Field(..., description="相对调节，如 +20 / -20")
    positions: Optional[List[str]] = None


class DoorLockArgs(BaseModel):
    locked: bool = Field(..., description="true上锁 false解锁")
    positions: Optional[List[str]] = Field(None, description="默认主驾；all=四门")


class TrunkArgs(BaseModel):
    open: bool = Field(..., description="true打开 false关闭")


class BodyOpenArgs(BaseModel):
    open: bool = Field(..., description="true打开 false关闭")


class ChildLockArgs(BaseModel):
    enable: bool


class LightArgs(BaseModel):
    target: str = Field(..., description="dome/ambient/reading_left/reading_right")
    enable: Optional[bool] = None
    brightness: Optional[int] = Field(None, ge=0, le=100)
    color: Optional[str] = None


class DisplayArgs(BaseModel):
    target: str = Field(..., description="center_screen/instrument/hud")
    brightness: int = Field(..., ge=0, le=100)


class PlayMusicArgs(BaseModel):
    artist: Optional[str] = None
    title: Optional[str] = None


class MusicControlArgs(BaseModel):
    action: str = Field(..., description="play/pause/stop")


class MusicSwitchArgs(BaseModel):
    direction: str = Field(..., description="next/prev")


class MusicSeekArgs(BaseModel):
    position_sec: Optional[float] = Field(None, description="绝对进度秒，如 90 表示跳到 1:30")
    delta_sec: Optional[float] = Field(None, description="相对快进/快退秒，如 +15 / -10")
    percent: Optional[float] = Field(None, ge=0, le=100, description="进度百分比 0-100")


class PlayRadioArgs(BaseModel):
    station_name: Optional[str] = None
    category: Optional[str] = None


class RadioControlArgs(BaseModel):
    action: str = Field(..., description="play/stop")


class VolumeArgs(BaseModel):
    volume: Optional[int] = Field(None, ge=0, le=100, description="绝对音量 0-100；仅当用户说了具体数字时使用")
    delta: Optional[int] = Field(None, description="相对变化：调小用负数如 -10，调大用正数如 +10；不要连续多次调用")
    muted: Optional[bool] = None


class NavigateArgs(BaseModel):
    destination: str
    preference: str = Field("fastest", description="fastest/shortest/eco")
    origin: Optional[str] = Field(None, description="起点，默认北京理工大学中关村校区南门")
    destination_location: Optional[str] = Field(
        None, description="目的地 GCJ-02 坐标 lng,lat；有则跳过歧义检索"
    )


class NearbySearchArgs(BaseModel):
    keywords: str = Field(..., description="周边搜索词，如：美食/餐厅/充电站/加油站/停车场/咖啡")
    radius: int = Field(3000, ge=500, le=10000, description="搜索半径米")
    types: str = Field("", description="高德 POI 类型码，可空")


class EmptyArgs(BaseModel):
    pass


class AdasArgs(BaseModel):
    feature: str = Field(..., description="auto_hold/acc/autopark/lane_keep/collision_warning")
    enable: bool


class DriveModeArgs(BaseModel):
    mode: str = Field(..., description="comfort/sport/eco/standard")


class SpeedArgs(BaseModel):
    speed_kmh: float = Field(..., ge=0, le=180, description="目标车速 km/h")
    gear: Optional[str] = Field(None, description="P/R/N/D")
    parked: Optional[bool] = None


class AppArgs(BaseModel):
    app_name: str = Field(..., description="应用名，须为已安装列表中的名称或别名，如飞书/微信/网易云")
    enable: bool = Field(True, description="True打开 False关闭")


class AssistantArgs(BaseModel):
    persona: Optional[str] = None
    speech_rate: Optional[str] = None
    scene: Optional[str] = None


class WifiArgs(BaseModel):
    enable: bool = Field(..., description="true=打开 Wi‑Fi，false=关闭")


class MessageAuthArgs(BaseModel):
    enable: bool = Field(True, description="兼容字段，已无授权语义")


class ListMessagesArgs(BaseModel):
    unread_only: bool = Field(False, description="只列出未读")
    mark_read: bool = Field(True, description="播报后是否标为已读")


class MarkMessagesArgs(BaseModel):
    ids: Optional[List[str]] = Field(None, description="要标已读的消息 id 列表")
    all_unread: bool = Field(False, description="将全部未读标为已读")


class WebSearchArgs(BaseModel):
    query: str = Field(..., description="搜索关键词，保留用户原意；不要改成附近地点")
    count: int = Field(5, ge=1, le=8, description="返回条数，默认 5")


def _run_web_search(query: str, count: int = 5) -> dict:
    from app.websearch import web_search

    return web_search(query, count)


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()

    def add(name, desc, model, handler, risk=RiskLevel.LOW, domain="general"):
        reg.register(ToolSpec(name=name, description=desc, args_model=model, handler=handler, risk=risk, domain=domain))

    # climate
    add("climate.set_power", "打开或关闭空调（可指定区域）", ClimatePowerArgs,
        lambda gw, a: gw.climate_power(a.enable, a.zones), domain="climate")
    add("climate.set_temperature", "设置空调绝对温度", ClimateTempArgs,
        lambda gw, a: gw.climate_set_temp(a.temperature, a.zones), domain="climate")
    add("climate.adjust_temperature", "相对调节温度（如降2度）", ClimateAdjustTempArgs,
        lambda gw, a: gw.climate_adjust_temp(a.delta, a.zones), domain="climate")
    add("climate.set_fan", "设置风量档位", ClimateFanArgs,
        lambda gw, a: gw.climate_set_fan(a.level, a.zones), domain="climate")
    add("climate.set_mode", "设置空调模式", ClimateModeArgs,
        lambda gw, a: gw.climate_set_mode(a.mode, a.recirculation), domain="climate")

    # seats
    add("seat.set", "座椅加热/通风/按摩", SeatArgs,
        lambda gw, a: gw.seat_set(a.feature, a.enable, a.level, a.positions, a.mode), domain="seat")
    add("seat.steering_wheel_heat", "方向盘加热", WheelHeatArgs,
        lambda gw, a: gw.steering_wheel_heat(a.enable, a.level), domain="seat")

    # cabin
    add("cabin.set_windows", "设置车窗/天窗开合百分比（天窗 positions=[sunroof]）", WindowArgs,
        lambda gw, a: gw.set_windows(a.percent, a.positions), risk=RiskLevel.MEDIUM, domain="cabin")
    add("cabin.adjust_windows", "相对调节车窗", WindowAdjustArgs,
        lambda gw, a: gw.adjust_windows(a.delta, a.positions), risk=RiskLevel.MEDIUM, domain="cabin")
    add("cabin.set_door_locks", "车门锁止/解锁", DoorLockArgs,
        lambda gw, a: gw.set_door_locks(a.locked, a.positions), risk=RiskLevel.HIGH, domain="cabin")
    add("cabin.set_trunk", "打开/关闭后备箱", TrunkArgs,
        lambda gw, a: gw.set_trunk(a.open), risk=RiskLevel.HIGH, domain="cabin")
    add("cabin.set_frunk", "打开/关闭前备箱", BodyOpenArgs,
        lambda gw, a: gw.set_frunk(a.open), risk=RiskLevel.HIGH, domain="cabin")
    add("cabin.set_charge_port", "打开/关闭充电口", BodyOpenArgs,
        lambda gw, a: gw.set_charge_port(a.open), risk=RiskLevel.MEDIUM, domain="cabin")
    add("driving.set_child_lock", "儿童锁开关", ChildLockArgs,
        lambda gw, a: gw.set_child_lock(a.enable), risk=RiskLevel.MEDIUM, domain="driving")
    add("cabin.set_light", "车内灯光控制", LightArgs,
        lambda gw, a: gw.set_light(a.target, a.enable, a.brightness, a.color), domain="cabin")
    add("cabin.set_display_brightness", "屏幕亮度", DisplayArgs,
        lambda gw, a: gw.set_display_brightness(a.target, a.brightness), domain="cabin")

    # media
    add("media.play_music", "播放本地曲库歌曲", PlayMusicArgs,
        lambda gw, a: gw.play_music(a.artist, a.title), domain="media")
    add("media.control_music", "播放/暂停/停止音乐", MusicControlArgs,
        lambda gw, a: gw.control_music(a.action), domain="media")
    add("media.switch_music", "上一首/下一首", MusicSwitchArgs,
        lambda gw, a: gw.switch_music(a.direction), domain="media")
    add(
        "media.seek_music",
        "调整歌曲播放进度（快进/快退/跳到某时刻或百分比）。例如：快进30秒→delta_sec=30；退回开头→position_sec=0；进度一半→percent=50",
        MusicSeekArgs,
        lambda gw, a: gw.seek_music(a.position_sec, a.delta_sec, a.percent),
        domain="media",
    )
    add("media.play_radio", "播放预设电台", PlayRadioArgs,
        lambda gw, a: gw.play_radio(a.station_name, a.category), domain="media")
    add("media.control_radio", "电台播放/停止", RadioControlArgs,
        lambda gw, a: gw.control_radio(a.action), domain="media")
    add("media.switch_radio", "上一个/下一个电台", MusicSwitchArgs,
        lambda gw, a: gw.switch_radio(a.direction), domain="media")
    add("media.set_volume", "音量/静音", VolumeArgs,
        lambda gw, a: gw.set_volume(a.volume, a.delta, a.muted), domain="media")

    # nav / driving / apps
    add("navigation.navigate_to", "导航到目的地（高德 MCP/REST 真实路径）", NavigateArgs,
        lambda gw, a: gw.navigate_to(
            a.destination, a.preference, a.origin, getattr(a, "destination_location", None)
        ), domain="navigation")
    add("navigation.start", "开始导航（同 navigate_to）", NavigateArgs,
        lambda gw, a: gw.navigate_to(
            a.destination, a.preference, a.origin, getattr(a, "destination_location", None)
        ), domain="navigation")
    add("navigation.stop", "结束导航", EmptyArgs,
        lambda gw, a: gw.stop_navigation(), domain="navigation")
    add(
        "maps.search_nearby",
        "按当前车辆定位搜索周边地点（美食/充电站/加油站/停车场等，高德地图）",
        NearbySearchArgs,
        lambda gw, a: gw.search_nearby(a.keywords, a.radius, a.types),
        domain="maps",
    )
    add("driving.set_adas", "ADAS功能开关", AdasArgs,
        lambda gw, a: gw.set_adas(a.feature, a.enable), risk=RiskLevel.HIGH, domain="driving")
    add(
        "driving.set_speed",
        "设置目标车速/挡位/驻车。非零车速会退出驻车、挂入D挡并开启自适应巡航驶向该速度（高风险，需确认）",
        SpeedArgs,
        lambda gw, a: gw.set_speed(a.speed_kmh, a.gear, a.parked),
        risk=RiskLevel.HIGH,
        domain="driving",
    )
    add("driving.set_mode", "切换驾驶模式", DriveModeArgs,
        lambda gw, a: gw.set_drive_mode(a.mode), domain="driving")
    add("apps.launch",
        f"打开或关闭车机已安装应用。{catalog_for_prompt()}",
        AppArgs,
        lambda gw, a: gw.launch_app(a.app_name, a.enable),
        domain="apps",
    )
    add("assistant.configure", "助手人设/语速/情景", AssistantArgs,
        lambda gw, a: gw.set_assistant(a.persona, a.speech_rate, a.scene), domain="assistant")
    add(
        "connectivity.set_wifi",
        "打开或关闭车机 Wi‑Fi（通常为手机热点/车载热点连接）",
        WifiArgs,
        lambda gw, a: gw.set_wifi(a.enable),
        domain="connectivity",
    )
    add(
        "notifications.authorize",
        "兼容旧话术：说明消息无需授权（仪表盘可直接看；语音朗读走确认）",
        MessageAuthArgs,
        lambda gw, a: gw.authorize_messages(a.enable),
        domain="notifications",
    )
    add(
        "notifications.list_messages",
        "读取车机同步消息（Agent 调用需隐私确认；口头只摘要，完整正文进依据面板；默认读后标已读）",
        ListMessagesArgs,
        lambda gw, a: gw.list_messages(a.unread_only, a.mark_read),
        domain="notifications",
    )
    add(
        "notifications.mark_read",
        "将指定消息或全部未读标为已读",
        MarkMessagesArgs,
        lambda gw, a: gw.mark_messages_read(a.ids, a.all_unread),
        domain="notifications",
    )
    add(
        "web.search",
        "上网检索（新闻、攻略、评测、油价汇率比分、百科时事等）。"
        "用户明说要搜网，或答案依赖互联网、不能靠车况/手册瞎编时调用。"
        "query 写清检索主题（可结合对话上下文）。"
        "车主手册用法、附近门店、导航请分别用 knowledge / maps.search_nearby / navigation，不要用本工具替代。",
        WebSearchArgs,
        lambda _gw, a: _run_web_search(a.query, a.count),
        domain="web",
    )

    return reg
