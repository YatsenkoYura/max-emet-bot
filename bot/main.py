import asyncio
import logging
from maxapi import Bot, Dispatcher
from db import get_session
from handlers.regHandler import RegHandler
from handlers.parseHandler import ParseHandler
from handlers.NewsHandler import NewsManager
from utils.recomendation import precompute_scores_for_user
from sqlalchemy.orm import Session
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import functools
from models import User, News
import json
from datetime import datetime


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def recompute_all_users_weights(db_session):
    """Автоматический периодический перерасчёт весов для всех активных пользователей"""
    logger.info("♻️ Запуск перерасчёта весов для всех пользователей...")
    try:
        users = db_session.query(User).all()
        for user in users:
            await asyncio.to_thread(precompute_scores_for_user, user, db_session)
        logger.info("Перерасчёт весов завершён")
    except Exception as e:
        logger.error(f"Ошибка при перерасчёте весов: {e}")


async def job_wrapper(session):
    await recompute_all_users_weights(session)

def job_sync_wrapper(session):
    asyncio.run(job_wrapper(session))
import json
from models import News, NewsCategory
from sqlalchemy.exc import IntegrityError

def load_news_from_dump(session: Session, filename="news_dump.json"):
    now = datetime.utcnow()
    with open(filename, "r", encoding="utf-8") as f:
        news_data = json.load(f)
    for item in news_data:
        news = News(
            title=item["title"],
            content=item["content"],
            summary=item.get("summary"),
            category=NewsCategory(item["category"]),
            category_confidence=item.get("category_confidence"),
            source_url=item.get("source_url"),
            source_name=item.get("source_name"),
            created_at=now
        )
        session.add(news)
    try:
        session.commit()
        print(f"Loaded {len(news_data)} news from dump")
    except IntegrityError:
        session.rollback()
        print("Some data already exists, rollback done")


async def main():
    """Главная функция запуска бота."""
    bot = Bot(token=os.getenv("TOKEN"))
    dp = Dispatcher()
    session = get_session()
    
    logger.info("Тренериуем поисковую систему")

    from utils.search_news import NewsSearchEngine
    search_engine = NewsSearchEngine()
    search_engine.fit(session)

    logger.info("Регистрация обработчиков...")
    
    reg_handler = RegHandler(bot=bot, db_session=session)
    news_manager = NewsManager(bot=bot, db_session=session, search_engine=search_engine)
    
    dp.include_routers(news_manager.router)
    dp.include_routers(reg_handler.dp)
    
    logger.info("Роутеры подключены")
    
    parse_handler = ParseHandler(session)
    scheduler = AsyncIOScheduler()
    
    scheduler.add_job(parse_handler.command, 'interval', minutes=10)

    scheduler.add_job(functools.partial(job_sync_wrapper, session), 'interval', minutes=10)


    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    session = get_session()
    news_count = session.query(News).count()
    if news_count == 0:
        load_news_from_dump(session)
    asyncio.run(main())
