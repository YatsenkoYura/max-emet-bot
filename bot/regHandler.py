from maxapi import Dispatcher, Bot
from maxapi.types import BotStarted, MessageCallback, MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from maxapi.types import (
    ChatButton, 
    LinkButton, 
    CallbackButton, 
    RequestGeoLocationButton, 
    MessageButton, 
    ButtonsPayload,
    RequestContactButton, 
    OpenAppButton, 
)

user_states = {}

class RegHandler():
    def __init__(self, bot: Bot, dp: Dispatcher):
        self.bot = bot
        self.dp = dp
        self.register_handler()
        self.user_add_info = {
            "age": None,
            "gender": None,
            "hobby": None
        }
        self.hobby_builder = InlineKeyboardBuilder()
        self.hobby_builder.row()

    def register_handler(self):
        self.dp.bot_started()(self.start_reg)
        self.dp.message_callback()(self.callback_gender)
        self.dp.message_created()(self.handle_user_input_age)

    async def start_reg(self, event: BotStarted):
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(
                text="👨 Мужчина",
                payload="m_gender"
            ),
            CallbackButton(
                text="👱‍♀️ Женщина",
                payload="f_gender"
            ),
        )
        await self.bot.send_message(
            chat_id=event.chat_id,
            text=f"Привет! Прежде чем перейти к использованию, пройдите простую регестрацию. \nВыберете свой пол",
            attachments=[
                builder.as_markup()
            ])
    
    async def callback_gender(self, callback: MessageCallback):
        await callback.message.delete()
        if callback.callback.payload == "f_gender":
            self.user_add_info["gender"] = "f"
            await self.bot.send_message(callback.chat.chat_id,
            text="Спасибо!\nУкажите свой возраст, отправьте сообщение")
            user_states[callback.callback.user.user_id] = 'waiting_for_numbers'

        if callback.callback.payload == "m_gender":
            self.user_add_info["gender"] = "m"
            await self.bot.send_message(callback.chat.chat_id,
            text="Спасибо!\nУкажите свой возраст, отправьте сообщение")
            user_states[callback.chat.chat_id] = 'waiting_for_numbers'

    async def handle_user_input_age(self, event: MessageCreated):
        chat_id = event.get_ids()[0]
        if user_states.get(chat_id) == 'waiting_for_numbers':
            user_text = event.message.body.text
            if user_text and user_text.isdigit():
                self.user_add_info["age"] = int(user_text)
                await event.message.answer(
                    text="Мы почти закончили!\nВыберете интересующие вас категории"

                )
            
                del user_states[chat_id]
            else:
                await event.message.answer(
                    'Ошибка! Пожалуйста, отправьте только цифры.'
                )


