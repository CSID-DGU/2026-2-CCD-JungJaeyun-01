"""호선 공식 색·버스 종류별 색을 경로에 입히는 함수. 색상표는 config/line_colors.yaml."""

import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import yaml

from app.route_model import BUS, SUBWAY, Route, Segment

PATH = Path(__file__).resolve().parents[1] / "config" / "line_colors.yaml"


@lru_cache
def load_table() -> dict:
    return yaml.safe_load(PATH.read_text(encoding="utf-8"))


def subway_color(line_name: str | None, table: dict | None = None) -> tuple[str, str] | None:
    table = table or load_table()
    for key, v in table["subway"].items():
        if line_name and key in line_name:
            return v["color"], v["text"]
    return None


def bus_kind_color(line_name: str | None, table: dict | None = None) -> tuple[str, str, str] | None:
    table = table or load_table()
    for rule in table["bus"]:
        if line_name and re.search(rule["pattern"], line_name):
            return rule["kind"], rule["color"], rule["text"]
    return None


def apply_line_colors(route: Route) -> Route:
    """지하철은 호선 공식 색, 버스는 종류별 색으로 바꾼다. 표에 없으면 Google 색을 그대로 둔다."""
    segments = []
    for seg in route.segments:
        new: Segment = seg
        if seg.mode == SUBWAY and (c := subway_color(seg.line_name)):
            new = replace(seg, line_color=c[0], line_text_color=c[1])
        elif seg.mode == BUS and (b := bus_kind_color(seg.line_name)):
            new = replace(seg, line_color=b[1], line_text_color=b[2], line_kind=b[0])
        segments.append(new)
    return replace(route, segments=tuple(segments))
