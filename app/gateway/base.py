# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class VehicleGateway(ABC):
    """车控网关抽象：Stub / 真车机只换实现。"""

    @abstractmethod
    def snapshot(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    def replace(self, state: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def reset(self) -> Dict[str, Any]:
        ...

    # ---- climate ----
    @abstractmethod
    def climate_power(self, enable: bool, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def climate_set_temp(self, temperature: float, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def climate_adjust_temp(self, delta: float, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def climate_set_fan(self, level: int, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def climate_set_mode(self, mode: str, recirculation: Optional[bool] = None) -> Dict[str, Any]:
        ...

    # ---- seats ----
    @abstractmethod
    def seat_set(self, feature: str, enable: bool, level: int = 2, positions: Optional[List[str]] = None, mode: str = "normal") -> Dict[str, Any]:
        ...

    @abstractmethod
    def steering_wheel_heat(self, enable: bool, level: int = 2) -> Dict[str, Any]:
        ...

    # ---- cabin ----
    @abstractmethod
    def set_windows(self, percent: int, positions: Optional[List[str]] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def adjust_windows(self, delta: int, positions: Optional[List[str]] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_door_locks(self, locked: bool, positions: Optional[List[str]] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_trunk(self, open_: bool) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_frunk(self, open_: bool) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_charge_port(self, open_: bool) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_child_lock(self, enable: bool) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_light(self, target: str, enable: Optional[bool] = None, brightness: Optional[int] = None, color: Optional[str] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_display_brightness(self, target: str, brightness: int) -> Dict[str, Any]:
        ...

    # ---- media ----
    @abstractmethod
    def play_music(self, artist: Optional[str] = None, title: Optional[str] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def control_music(self, action: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def switch_music(self, direction: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def seek_music(
        self,
        position_sec: Optional[float] = None,
        delta_sec: Optional[float] = None,
        percent: Optional[float] = None,
    ) -> Dict[str, Any]:
        ...

    @abstractmethod
    def play_radio(self, station_name: Optional[str] = None, category: Optional[str] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def control_radio(self, action: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def switch_radio(self, direction: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_volume(self, volume: Optional[int] = None, delta: Optional[int] = None, muted: Optional[bool] = None) -> Dict[str, Any]:
        ...

    # ---- nav / driving / apps ----
    @abstractmethod
    def navigate_to(self, destination: str, preference: str = "fastest", origin: Optional[str] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def stop_navigation(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    def search_nearby(
        self,
        keywords: str,
        radius: int = 3000,
        types: str = "",
    ) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_adas(self, feature: str, enable: bool) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_speed(self, speed_kmh: float, gear: Optional[str] = None, parked: Optional[bool] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def tick_dynamics(self, dt: float = 0.25) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_drive_mode(self, mode: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def launch_app(self, app_name: str, enable: bool = True) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_assistant(self, persona: Optional[str] = None, speech_rate: Optional[str] = None, scene: Optional[str] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def set_wifi(self, enable: bool) -> Dict[str, Any]:
        ...

    @abstractmethod
    def authorize_messages(self, enable: bool = True) -> Dict[str, Any]:
        ...

    @abstractmethod
    def list_messages(self, unread_only: bool = False, mark_read: bool = True) -> Dict[str, Any]:
        ...

    @abstractmethod
    def mark_messages_read(self, ids: Optional[List[str]] = None, all_unread: bool = False) -> Dict[str, Any]:
        ...
