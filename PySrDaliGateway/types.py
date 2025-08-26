"""Dali Gateway Types"""

from typing import List, TypedDict


class DeviceProperty:
    dpid: int
    data_type: str


class DeviceType(TypedDict):
    unique_id: str
    id: str
    name: str
    dev_type: str
    channel: int
    address: int
    status: str
    dev_sn: str
    area_name: str
    area_id: str
    prop: List[DeviceProperty]


class GroupType(TypedDict):
    unique_id: str
    id: int
    name: str
    channel: int
    area_id: str


class SceneType(TypedDict):
    unique_id: str
    id: int
    name: str
    channel: int
    area_id: str


class DaliGatewayType(TypedDict):
    gw_sn: str
    gw_ip: str
    port: int
    name: str
    username: str
    passwd: str
    is_tls: bool
    channel_total: List[int]


class VersionType(TypedDict):
    software: str
    firmware: str


class DeviceParamType(TypedDict):
    # address: int
    # fade_time: int
    # fade_rate: int
    # power_status: int
    # system_failure_status: int
    max_brightness: int
    # min_brightness: int
    # standby_power: int
    # max_power: int
    # cct_cool: int
    # cct_warm: int
    # phy_cct_cool: int
    # phy_cct_warm: int
    # step_cct: int
    # temp_thresholds: int
    # runtime_thresholds: int
