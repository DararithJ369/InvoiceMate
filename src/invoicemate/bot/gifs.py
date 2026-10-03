import os
import logging
from typing import Optional, Union
from aiogram.types import FSInputFile, Message, CallbackQuery, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

GIF_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "gifs"))

GIF_PATHS = {
    "welcome": os.path.join(GIF_DIR, "welcome.gif"),
    "success": os.path.join(GIF_DIR, "success.gif"),
    "paid": os.path.join(GIF_DIR, "paid.gif"),
    "clear": os.path.join(GIF_DIR, "clear.gif"),
}

GIF_URLS = {
    "welcome": "https://media.giphy.com/media/QDjpIL6oNCVZ4qzGs7/giphy.gif",
    "success": "https://media.giphy.com/media/26u4lOMA8JKSnL9Uk/giphy.gif",
    "paid": "https://media.giphy.com/media/V2RSH43jhxjJdiQAoZ/giphy.gif",
    "clear": "https://media.giphy.com/media/d7Zv95YKA28s1yrqqX/giphy.gif",
}

PAID_GIF_URL = GIF_URLS["paid"]


def get_animation_target(key: str) -> Union[FSInputFile, str]:
    """Return local FSInputFile if file exists, else direct fallback URL."""
    local_path = GIF_PATHS.get(key)
    if local_path and os.path.exists(local_path):
        return FSInputFile(local_path)
    return GIF_URLS.get(key, "")


async def send_event_gif(
    message: Message,
    key: str,
    caption: str = "",
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    """
    Send an animated GIF for key bot events (Greeting, Invoice Issued, Paid, Cleared).
    Falls back gracefully to text message if animation dispatch fails.
    """
    anim = get_animation_target(key)
    if anim:
        try:
            return await message.answer_animation(
                animation=anim,
                caption=caption if caption else None,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Failed to send GIF for event '{key}': {e}")

    if caption:
        return await message.answer(caption, reply_markup=reply_markup, parse_mode="HTML")
    return None
