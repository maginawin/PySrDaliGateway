"""Dali Gateway Types"""

from typing import TypedDict


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
    prop: list[DeviceProperty]


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
    channel_total: list[int]


class VersionType(TypedDict):
    software: str
    firmware: str
