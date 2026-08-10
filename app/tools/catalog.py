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
    positions: Optional[List[str]] = Field(None, description="默认主驾；all=四窗")


class WindowAdjustArgs(BaseModel):
    delta: int = Field(..., description="相对调节，如 +20 / -20")
    positions: Optional[List[str]] = None


class DoorLockArgs(BaseModel):
    locked: bool = Field(..., description="true上锁 false解锁")
    positions: Optional[List[str]] = Field(None, description="默认主驾；all=四门")


class TrunkArgs(BaseModel):
    open: bool = Field(..., description="true打开 false关闭")


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


class PlayRadioArgs(BaseModel):
    station_name: Optional[str] = None
    category: Optional[str] = None


class RadioControlArgs(BaseModel):
    action: str = Field(..., description="play/stop")


class VolumeArgs(BaseModel):
    volume: Optional[int] = Field(None, ge=0, le=100)
    delta: Optional[int] = None
    muted: Optional[bool] = None


class NavigateArgs(BaseModel):
    destination: str
    preference: str = Field("fastest", description="fastest/shortest/eco")


class EmptyArgs(BaseModel):
    pass


class AdasArgs(BaseModel):
    feature: str = Field(..., description="auto_hold/acc/autopark/lane_keep/collision_warning")
    enable: bool


class DriveModeArgs(BaseModel):
    mode: str = Field(..., description="comfort/sport/eco/standard")


class AppArgs(BaseModel):
    app_name: str = Field(..., description="应用名，须为已安装列表中的名称或别名，如飞书/微信/网易云")
    enable: bool = Field(True, description="True打开 False关闭")


class AssistantArgs(BaseModel):
    persona: Optional[str] = None
    speech_rate: Optional[str] = None
    scene: Optional[str] = None


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
    add("cabin.set_windows", "设置车窗开合百分比", WindowArgs,
        lambda gw, a: gw.set_windows(a.percent, a.positions), risk=RiskLevel.MEDIUM, domain="cabin")
    add("cabin.adjust_windows", "相对调节车窗", WindowAdjustArgs,
        lambda gw, a: gw.adjust_windows(a.delta, a.positions), risk=RiskLevel.MEDIUM, domain="cabin")
    add("cabin.set_door_locks", "车门锁止/解锁", DoorLockArgs,
        lambda gw, a: gw.set_door_locks(a.locked, a.positions), risk=RiskLevel.HIGH, domain="cabin")
    add("cabin.set_trunk", "打开/关闭后备箱", TrunkArgs,
        lambda gw, a: gw.set_trunk(a.open), risk=RiskLevel.HIGH, domain="cabin")
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
    add("media.play_radio", "播放预设电台", PlayRadioArgs,
        lambda gw, a: gw.play_radio(a.station_name, a.category), domain="media")
    add("media.control_radio", "电台播放/停止", RadioControlArgs,
        lambda gw, a: gw.control_radio(a.action), domain="media")
    add("media.set_volume", "音量/静音", VolumeArgs,
        lambda gw, a: gw.set_volume(a.volume, a.delta, a.muted), domain="media")

    # nav / driving / apps
    add("navigation.navigate_to", "导航到目的地", NavigateArgs,
        lambda gw, a: gw.navigate_to(a.destination, a.preference), domain="navigation")
    add("navigation.stop", "结束导航", EmptyArgs,
        lambda gw, a: gw.stop_navigation(), domain="navigation")
    add("driving.set_adas", "ADAS功能开关", AdasArgs,
        lambda gw, a: gw.set_adas(a.feature, a.enable), risk=RiskLevel.HIGH, domain="driving")
    add("driving.set_mode", "切换驾驶模式", DriveModeArgs,
        lambda gw, a: gw.set_drive_mode(a.mode), domain="driving")
    add(
        "apps.launch",
        f"打开或关闭车机已安装应用。{catalog_for_prompt()}",
        AppArgs,
        lambda gw, a: gw.launch_app(a.app_name, a.enable),
        domain="apps",
    )
    add("assistant.configure", "助手人设/语速/情景", AssistantArgs,
        lambda gw, a: gw.set_assistant(a.persona, a.speech_rate, a.scene), domain="assistant")

    return reg
