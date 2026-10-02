import asyncio
import logging
from aiogram import Bot, Dispatcher
from invoicemate.core.config import settings
from invoicemate.db.database import init_db
from invoicemate.bot.handlers import router
from invoicemate.bot.rate_limiter import RateLimitMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_bot():
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set!")
        print("Error: Please set TELEGRAM_BOT_TOKEN in your environment or .env file.")
        return

    init_db()

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()

    # Register 20 req/min rate limiting middleware on messages and callback queries
    rate_limiter = RateLimitMiddleware(limit=20, window_seconds=60.0)
    dp.message.middleware(rate_limiter)
    dp.callback_query.middleware(rate_limiter)

    dp.include_router(router)

    logger.info("InvoiceAI Telegram bot started with Rate Limiting (20 req/min/org). Listening...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run_bot())
