import asyncio
import logging
from maxapi import Bot, Dispatcher
from db import get_session
from handlers.regHandler import RegHandler
from handlers.parseHandler import ParseHandler
from handlers.NewsHandler import NewsManager
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Главная функция запуска бота."""
    bot = Bot(token=os.getenv("TOKEN"))
    dp = Dispatcher()
    session = get_session()
    
    logger.info("🚀 Регистрация обработчиков...")
    
    reg_handler = RegHandler(bot=bot, db_session=session)
    news_manager = NewsManager(bot=bot, db_session=session)
    dp.include_routers(news_manager.router)
    dp.include_routers(reg_handler.dp)
    logger.info("✅ Роутеры подключены")
    
    # ParseHandler и scheduler
    parse_handler = ParseHandler(session)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(parse_handler.command, 'interval', minutes=10)
    scheduler.start()
    logger.info("✅ Scheduler запущен")
    
    logger.info("🤖 Запуск polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
