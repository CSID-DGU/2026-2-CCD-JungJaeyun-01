"""Evaluate published business periods in Seoul local time."""
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def opening_status(schedule, meeting):
    if not schedule or not meeting:
        return "확인 필요"
    local = meeting.astimezone(KST)
    today = date.fromisoformat(schedule["retrieved"])
    current = schedule.get("current")
    if current is not None and today <= local.date() < today + timedelta(days=7):
        periods = current.get("periods")
        dated = True
    else:
        periods = (schedule.get("regular") or {}).get("periods")
        dated = False
    if periods is None:
        return "확인 필요"
    minute = local.hour * 60 + local.minute
    target = ((local.weekday() + 1) % 7) * 1440 + minute
    try:
        for period in periods:
            start = period["open"]
            end = period.get("close")
            if not end:
                if start["day"] == 0 and not start.get("hour") and not start.get("minute"):
                    return "영업 예상"
                return "확인 필요"
            if dated:
                def point(p):
                    d = p["date"]
                    return datetime(d["year"], d["month"], d["day"], p.get("hour", 0), p.get("minute", 0), tzinfo=KST)
                if point(start) <= local < point(end):
                    return "영업 예상"
            else:
                def weekly(p):
                    return p["day"] * 1440 + p.get("hour", 0) * 60 + p.get("minute", 0)
                a, b = weekly(start), weekly(end)
                if a <= target < b or (b <= a and (target >= a or target < b)):
                    return "영업 예상"
    except (KeyError, TypeError, ValueError):
        return "확인 필요"
    return "영업시간 외 예상"
