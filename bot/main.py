import asyncio
import logging
from maxapi import Bot, Dispatcher
from db import get_session
from handlers.regHandler import RegHandler
from handlers.parseHandler import ParseHandler
import os

logging.basicConfig(level=logging.INFO)

async def main():
    """Главная функция запуска бота."""
    bot = Bot(token=os.getenv("TOKEN"))
    dp = Dispatcher()
    session = get_session()
    ParseHandler(bot, dp, session)
    reg_handler = RegHandler(bot=bot, dp=dp, db_session=session)
    reg_handler.register_handler()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
