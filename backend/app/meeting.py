"""약속 시간: 기본값 계산과 검증.

경로는 '약속 시간에 도착'하는 기준(arrivalTime)으로 구한다. 그러면 참여자별로 몇 시에 출발해야 하는지가 나온다.
"""

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
MIN_LEAD = timedelta(minutes=30)   # 약속 시간은 지금보다 최소 이만큼 뒤여야 한다
SATURDAY = 5


class InvalidMeetingTime(ValueError):
    """약속 시간이 과거이거나 너무 가깝다."""


def default_meeting_time(now: datetime | None = None, weekday: int = SATURDAY, hour: int = 18) -> datetime:
    """오늘 이후 첫 `weekday`(기본 토요일) hour시(KST). 오늘이 그 요일이어도 다음 주로 잡는다."""
    today = (now or datetime.now(KST)).astimezone(KST).date()
    days = (weekday - today.weekday()) % 7 or 7
    d = today + timedelta(days=days)
    return datetime(d.year, d.month, d.day, hour, tzinfo=KST)


def resolve_meeting_time(value: datetime | None, now: datetime | None = None,
                         weekday: int = SATURDAY, hour: int = 18) -> datetime:
    """요청에 약속 시간이 없으면 기본값, 있으면 KST로 맞춰 검증한다 (시간대가 없으면 KST로 본다)."""
    current = (now or datetime.now(KST)).astimezone(KST)
    if value is None:
        return default_meeting_time(current, weekday, hour)
    meeting = value.replace(tzinfo=KST) if value.tzinfo is None else value.astimezone(KST)
    if meeting < current + MIN_LEAD:
        raise InvalidMeetingTime("약속 시간은 지금부터 30분 이상 뒤여야 해요.")
    return meeting
