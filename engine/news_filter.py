import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import httpx

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_NEXT_URL = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

HIGH_IMPACT_COUNTRIES = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"}


class NewsEvent:
    def __init__(self, title: str, country: str, dt: datetime, impact: str,
                 forecast: str = "", previous: str = ""):
        self.title = title
        self.country = country
        self.dt = dt
        self.impact = impact
        self.forecast = forecast
        self.previous = previous


class NewsFilter:
    def __init__(self, window_minutes: int = 30, refresh_hours: int = 6,
                 major_only: bool = True):
        self.window_minutes = window_minutes
        self.refresh_hours = refresh_hours
        self.major_only = major_only
        self._events: List[NewsEvent] = []
        self._last_fetch: Optional[datetime] = None

    async def refresh(self):
        if self._last_fetch:
            elapsed = (datetime.now(timezone.utc) - self._last_fetch).total_seconds()
            if elapsed < self.refresh_hours * 3600:
                return

        events = []
        fetched_any = False
        for url in [CALENDAR_URL, CALENDAR_NEXT_URL]:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    raw = resp.json()

                fetched_any = True
                for item in raw:
                    if item.get("impact") != "High":
                        continue
                    if self.major_only and item.get("country") not in HIGH_IMPACT_COUNTRIES:
                        continue

                    dt_str = item.get("date", "")
                    if not dt_str:
                        continue

                    try:
                        dt = datetime.fromisoformat(dt_str)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        continue

                    events.append(NewsEvent(
                        title=item.get("title", ""),
                        country=item.get("country", ""),
                        dt=dt,
                        impact=item.get("impact", ""),
                        forecast=item.get("forecast", ""),
                        previous=item.get("previous", ""),
                    ))
            except Exception as e:
                logger.warning(f"Failed to fetch calendar from {url}: {e}")

        if not fetched_any:
            # Keep the previously cached event list instead of replacing it
            # with an empty one when every upstream fetch failed.
            logger.warning(
                f"All calendar fetches failed; keeping {len(self._events)} cached events"
            )
            return

        self._events = sorted(events, key=lambda e: e.dt)
        self._last_fetch = datetime.now(timezone.utc)
        logger.info(f"News filter loaded {len(self._events)} high-impact events")

    def is_blocked(self, dt: Optional[datetime] = None) -> bool:
        if not self._events:
            return False

        if dt is None:
            dt = datetime.now(timezone.utc)

        window = timedelta(minutes=self.window_minutes)
        for event in self._events:
            if abs((event.dt - dt).total_seconds()) <= window.total_seconds():
                return True
        return False

    def get_nearest_event(self, dt: Optional[datetime] = None) -> Optional[NewsEvent]:
        if not self._events:
            return None

        if dt is None:
            dt = datetime.now(timezone.utc)

        future = [e for e in self._events if e.dt > dt]
        if not future:
            return None

        return min(future, key=lambda e: e.dt)

    def get_upcoming_events(self, hours: int = 72) -> List[NewsEvent]:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours)
        return [e for e in self._events if now <= e.dt <= cutoff]

    def format_event(self, event: NewsEvent) -> str:
        dt_local = event.dt.astimezone()
        time_str = dt_local.strftime("%a %H:%M")
        return f"{time_str} | {event.country} | {event.title}"
