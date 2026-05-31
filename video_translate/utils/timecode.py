from __future__ import annotations


def format_srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def parse_srt_time(value: str) -> float:
    hours_part, minutes_part, rest = value.strip().split(":")
    seconds_part, millis_part = rest.split(",")
    return (
        int(hours_part) * 3600
        + int(minutes_part) * 60
        + int(seconds_part)
        + int(millis_part) / 1000
    )
