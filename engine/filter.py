from datetime import datetime, timezone
from typing import List


class SessionFilter:
    def __init__(self, blocked_hours: List[int] = None):
        self.blocked_hours = blocked_hours or [1, 11, 17, 20]

    def is_tradable(self) -> bool:
        current_hour = datetime.now(timezone.utc).hour
        return current_hour not in self.blocked_hours

    def get_current_session(self) -> str:
        hour = datetime.now(timezone.utc).hour
        if 7 <= hour < 9:
            return "LONDON_OPEN"
        elif 13 <= hour < 17:
            return "LONDON_NY_OVERLAP"
        elif 9 <= hour < 13:
            return "LONDON_SESSION"
        elif 17 <= hour < 21:
            return "NY_SESSION"
        elif 0 <= hour < 7:
            return "ASIAN_SESSION"
        else:
            return "OFF_HOURS"

    def should_skip_payout(self, payout: int, min_payout: int = 80) -> bool:
        return payout < min_payout
