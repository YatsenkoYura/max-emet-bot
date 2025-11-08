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
    regHandler = RegHandler(bot=bot, dp=dp)
    regHandler.register_handler()
    session = get_session()
    
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
