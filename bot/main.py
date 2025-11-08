import asyncio
import logging
from maxapi import Bot, Dispatcher
from db import get_session
from regHandler import RegHandler
import os

logging.basicConfig(level=logging.INFO)

async def main():
    """Главная функция запуска бота."""
    bot = Bot(token=os.getenv("TOKEN"))
    dp = Dispatcher()
    session = get_session()

    regHandler = RegHandler(bot=bot, dp=dp, db_session=session)
    regHandler.register_handler()
    
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
