from maxapi import Router, F
from maxapi.types import MessageCallback, MessageCreated, Command
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types import CallbackButton
from sqlalchemy.orm import Session
from models import User, News, ReactionType
from utils.recomendation import get_recommended_news, process_user_reaction
from typing import Optional
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class NewsManager:
    def __init__(self, bot, db_session: Session):
        self.bot = bot
        self.db_session = db_session
        self.user_news_cache = {}
        self.user_score_cache_time = {}
        self.router = Router()
        self.register_handlers()

    def register_handlers(self):
        self.router.message_created(Command("news"))(self.handle_news_command)
        self.router.message_callback(F.callback.payload == "start_reading")(self.handle_start_reading)
        self.router.message_callback(F.callback.payload == "news_prev")(self.handle_news_prev)
        self.router.message_callback(F.callback.payload == "news_next")(self.handle_news_next)
        self.router.message_callback(F.callback.payload.startswith("reaction_"))(self.handle_reaction)

    async def handle_news_command(self, event: MessageCreated):
        if not event.message or not event.message.body:
            return
        text = event.message.body.text
        if not text or text.strip() != "/news":
            return
        chat_id = event.get_ids()[0]
        user_id = event.message.sender.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await self.bot.send_message(chat_id, "⚠️ Сначала пройдите регистрацию через /start")
            return
        builder = InlineKeyboardBuilder()
        builder.row(CallbackButton(text="📰 Читать", payload="start_reading"))
        await self.bot.send_message(chat_id=chat_id, text="Давайте почитаем новости!", attachments=[builder.as_markup()])

    async def handle_start_reading(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.message.answer("⚠️ Пользователь не найден")
            return
        await callback.message.delete()
        await self.load_and_show_news(chat_id, user)
        await callback.answer()

    async def handle_news_prev(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.message.answer("⚠️ Пользователь не найден")
            return
        await self.navigate_news(chat_id, user, callback.message, direction=-1)
        await callback.answer()

    async def handle_news_next(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.message.answer("⚠️ Пользователь не найден")
            return
        await self.navigate_news(chat_id, user, callback.message, direction=1)
        await callback.answer()

    async def handle_reaction(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.message.answer("⚠️ Пользователь не найден")
            return
        reaction_type = callback.callback.payload.replace("reaction_", "")
        await self.process_reaction(chat_id, user, callback.message, reaction_type)
        await callback.answer()

    async def load_and_show_news(self, chat_id: int, user: User, count: int = 10):
        # Кэшируем рекомендации, пересчитываем не чаще раза в 30 минут
        last_calc = self.user_score_cache_time.get(user.id)
        now = datetime.utcnow()
        if not last_calc or (now - last_calc) > timedelta(minutes=30):
            from utils.recomendation import precompute_scores_for_user
            precompute_scores_for_user(user, self.db_session)
            self.user_score_cache_time[user.id] = now

        news_list = get_recommended_news(user=user, n=count, session=self.db_session, diversity_factor=0.2)
        if not news_list:
            await self.bot.send_message(chat_id, "😔 К сожалению, новых новостей для вас пока нет.")
            return
        self.user_news_cache[chat_id] = {'news': news_list, 'current_index': 0}
        await self.show_news_at_index(chat_id, user, 0)

    async def show_news_at_index(self, chat_id: int, user: User, index: int, message_to_edit: Optional[object] = None):
        cache = self.user_news_cache.get(chat_id)
        if not cache or not cache['news']:
            await self.bot.send_message(chat_id, "⚠️ Новости не загружены")
            return
        news_list = cache['news']
        index = max(0, min(index, len(news_list) - 1))
        cache['current_index'] = index
        news = news_list[index]
        text = self.format_news_message(news, index + 1, len(news_list))
        keyboard = self.build_news_keyboard(index, len(news_list))
        if message_to_edit:
            try:
                await message_to_edit.edit_text(text=text, attachments=[keyboard])
            except:
                await self.bot.send_message(chat_id, text=text, attachments=[keyboard])
        else:
            await self.bot.send_message(chat_id, text=text, attachments=[keyboard])

    def format_news_message(self, news: News, current: int, total: int) -> str:
        emoji_map = {
            "climate": "🌍", "conflicts": "⚔️", "culture": "🎭", "economy": "💰",
            "gloss": "🙂", "health": "🏥", "politics": "🏛️", "science": "🔬",
            "society": "👥", "sports": "⚽", "travel": "✈️"
        }
        emoji = emoji_map.get(news.category.value, "📰")
        content = news.content[:800] + "..." if len(news.content) > 800 else news.content
        text = f"{emoji} *{news.title}*\n\n{content}\n\n"
        text += f"📌 {news.source_name}\n"
        if news.source_url:
            text += f"🔗 [Читать полностью]({news.source_url})\n"
        text += f"\n📊 Новость {current} из {total}"
        return text

    def build_news_keyboard(self, current_index: int, total_count: int):
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(text="👍", payload="reaction_like"),
            CallbackButton(text="🤷", payload="reaction_skip"),
            CallbackButton(text="👎", payload="reaction_dislike")
        )
        nav_buttons = []
        if current_index > 0:
            nav_buttons.append(CallbackButton(text="⬅️", payload="news_prev"))
        if current_index < total_count - 1:
            nav_buttons.append(CallbackButton(text="➡️", payload="news_next"))
        if nav_buttons:
            builder.row(*nav_buttons)
        return builder.as_markup()

    async def navigate_news(self, chat_id: int, user: User, message, direction: int):
        cache = self.user_news_cache.get(chat_id)
        if not cache:
            await message.answer(text="⚠️ Сессия истекла")
            return
        new_index = cache['current_index'] + direction
        await self.show_news_at_index(chat_id, user, new_index, message)

    async def process_reaction(self, chat_id: int, user: User, message, reaction_str: str):
        cache = self.user_news_cache.get(chat_id)
        if not cache:
            return
        current_index = cache['current_index']
        news = cache['news'][current_index]
        reaction_map = {
            'like': ReactionType.LIKE,
            'dislike': ReactionType.DISLIKE,
            'skip': ReactionType.SKIP
        }
        reaction = reaction_map.get(reaction_str)
        if not reaction:
            return
        try:
            process_user_reaction(user, news, reaction, self.db_session)
            if current_index < len(cache['news']) - 1:
                await self.show_news_at_index(chat_id, user, current_index + 1, message)
            else:
                await message.edit_text(text="✅ Вы просмотрели все новости!")
                del self.user_news_cache[chat_id]
        except Exception as e:
            logger.error(f"❌ Ошибка реакции: {e}")
