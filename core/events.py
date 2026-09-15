import asyncio
import logging
from typing import Callable, Dict, List, Any
from datetime import datetime


class EventBus:
    def __init__(self):
        self.handlers: Dict[str, List[Callable]] = {}

    def on(self, event: str, handler: Callable):
        if event not in self.handlers:
            self.handlers[event] = []
        self.handlers[event].append(handler)

    def off(self, event: str, handler: Callable):
        if event in self.handlers:
            self.handlers[event] = [h for h in self.handlers[event] if h != handler]

    async def emit(self, event: str, data: Any = None):
        for handler in self.handlers.get(event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logging.error(f"Event handler error for {event}: {e}")


class Events:
    # Only the events actually consumed by the system are kept. The analysis
    # and result loops poll the database; candle ingestion is driven directly
    # by the CandleCollector polling loop, so no CANDLE_CLOSE bus plumbing is
    # needed.
    SIGNAL_GENERATED = "signal_generated"
