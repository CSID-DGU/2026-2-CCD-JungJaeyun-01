"""경로 프로바이더 공통 인터페이스와 호출 보호 도구."""

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Sequence

from app.geo import Coord
from app.route_model import Route
from app.stations import Station


class RouteUnavailable(Exception):
    """경로/이동시간을 구하지 못했다. str(e)가 사용자에게 보여줄 사유."""


@dataclass
class MatrixResult:
    """minutes[i][j] = 출발지 i → 도착역 j 이동시간(분). 구하지 못한 칸은 None."""

    minutes: list[list[float | None]]
    api_calls: int = 0          # 이번 요청에서 실제로 보낸 외부 API 호출 수
    cache_hits: int = 0         # 캐시/저장본에서 가져온 칸 수
    error: str | None = None    # 요청 전체가 실패한 경우의 사유


class RouteProvider(ABC):
    """2단계 구조: matrix()는 상위 후보 확인용(검색당 1회), route()는 참여자 이름을 눌렀을 때만 호출한다. 둘 다 약속 시간(meeting_time) 도착 기준이다."""

    name: str

    @abstractmethod
    def matrix(self, origins: Sequence[Coord], destinations: Sequence[Station], meeting_time: datetime) -> MatrixResult: ...

    @abstractmethod
    def route(self, origin: Coord, destination: Station, meeting_time: datetime) -> Route:
        """실패하면 RouteUnavailable."""


class _InFlight:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None


class SingleFlight:
    """같은 key의 요청이 동시에 들어오면 한 번만 실행하고, 나머지는 그 결과를 함께 받는다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, _InFlight] = {}

    def do(self, key: str, fn: Callable[[], Any]) -> Any:
        with self._lock:
            call = self._inflight.get(key)
            leader = call is None
            if leader:
                call = self._inflight[key] = _InFlight()
        if not leader:
            call.event.wait()
            if call.error is not None:
                raise call.error
            return call.value
        try:
            call.value = fn()
            return call.value
        except BaseException as e:
            call.error = e
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)
            call.event.set()
