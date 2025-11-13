import asyncio
import logging
from maxapi import Bot, Dispatcher
from db import get_session
from handlers.regHandler import RegHandler
from handlers.parseHandler import ParseHandler
from handlers.NewsHandler import NewsManager
from utils.recomendation import precompute_scores_for_user
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def recompute_all_users_weights(db_session):
    """Автоматический периодический перерасчёт весов для всех активных пользователей"""
    logger.info("♻️ Запуск перерасчёта весов для всех пользователей...")
    try:
        users = db_session.query(User).all()
        for user in users:
            precompute_scores_for_user(user, db_session)
        logger.info("✅ Перерасчёт весов завершён")
    except Exception as e:
        logger.error(f"❌ Ошибка при перерасчёте весов: {e}")


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
    
    parse_handler = ParseHandler(session)
    scheduler = AsyncIOScheduler()
    
    scheduler.add_job(parse_handler.command, 'interval', minutes=10)
    
    scheduler.add_job(lambda: asyncio.create_task(recompute_all_users_weights(session)), 'interval', minutes=30)
    
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
