import asyncio
import logging
from maxapi import Bot, Dispatcher
from handlers.message_handlers import MessageHandlers
import os

logging.basicConfig(level=logging.INFO)


async def main():
    """Главная функция запуска бота."""
    bot = Bot(token=os.getenv("TOKEN"))
    dp = Dispatcher()
    
    # Регистрируем обработчики через класс
    MessageHandlers(dp)
    
    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
