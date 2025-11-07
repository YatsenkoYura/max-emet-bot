from maxapi import Dispatcher
from maxapi.types import MessageCreated


class MessageHandlers:
    """Класс для обработки сообщений бота."""
    def __init__(self, dp: Dispatcher):
        self.dp = dp
        self.register_handlers()
    
    def register_handlers(self):
        """Регистрируем все обработчики через Dispatcher."""
        self.dp.message_created()(self.echo)
        self.dp.message_created()(self.reverse_echo)
    
    async def echo(self, event: MessageCreated):
        """Простой echo — повторяет сообщение."""
        message_text = event.message.body.text if event.message.body else ""
        await event.message.answer(message_text)
    
    async def reverse_echo(self, event: MessageCreated):
        """Обратный echo."""
        message_text = event.message.body.text if event.message.body else ""
        if message_text and message_text[0] == "r":
            await event.message.answer(message_text[::-1])
