import time
from collections import defaultdict
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject


class RateLimitMiddleware(BaseMiddleware):
    """
    In-memory sliding window rate limiter per organization / Telegram user.
    Enforces the mandate of maximum 20 requests per minute per org.
    """

    def __init__(self, limit: int = 20, window_seconds: float = 60.0):
        super().__init__()
        self.limit = limit
        self.window_seconds = window_seconds
        self.request_history: Dict[str, list[float]] = defaultdict(list)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = str(event.from_user.id)
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = str(event.from_user.id)

        if user_id:
            now = time.time()
            cutoff = now - self.window_seconds

            # Prune expired timestamps
            timestamps = [t for t in self.request_history[user_id] if t > cutoff]
            self.request_history[user_id] = timestamps

            if len(timestamps) >= self.limit:
                if isinstance(event, Message):
                    await event.answer(
                        "⚠️ <b>Rate limit exceeded:</b> Maximum 20 requests per minute allowed. "
                        "Please wait a moment before sending another request.",
                        parse_mode="HTML",
                    )
                elif isinstance(event, CallbackQuery):
                    await event.answer(
                        "⚠️ Rate limit exceeded (20 req/min). Please wait a moment.",
                        show_alert=True,
                    )
                return None

            self.request_history[user_id].append(now)

        return await handler(event, data)
