from maxapi import Router, F
from maxapi.types import MessageCallback, MessageCreated, Command
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types import CallbackButton
from maxapi.bot import ParseMode
from sqlalchemy.orm import Session
from models import User, News, ReactionType
from utils.recomendation import get_recommended_news, process_user_reaction
from utils.search_news import NewsSearchEngine, search_news_by_keyword
from typing import Optional
import logging
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)


class NewsManager:
    def __init__(self, bot, db_session: Session, search_engine: NewsSearchEngine):
        self.bot = bot
        self.db_session = db_session
        self.search_engine = search_engine
        self.user_news_cache = {}
        self.user_score_cache_time = {}
        self.router = Router()
        self.register_handlers()


    def register_handlers(self):
        self.router.message_created(Command("news"))(self.handle_news_command)
        self.router.message_created(Command("search"))(self.handle_search_command)
        self.router.message_callback(F.callback.payload == "start_reading")(self.handle_start_reading)
        self.router.message_callback(F.callback.payload == "news_prev")(self.handle_news_prev)
        self.router.message_callback(F.callback.payload == "news_next")(self.handle_news_next)
        self.router.message_callback(F.callback.payload.startswith("reaction_"))(self.handle_reaction)
        self.router.message_callback(F.callback.payload == "similar_prev")(self.handle_similar_prev)
        self.router.message_callback(F.callback.payload == "similar_next")(self.handle_similar_next)
        self.router.message_callback(F.callback.payload.startswith("similar_reaction_"))(self.handle_similar_reaction)
        self.router.message_callback(F.callback.payload.startswith("similar_"))(self.handle_similar_news)
        self.router.message_callback(F.callback.payload == "search_prev")(self.handle_search_prev)
        self.router.message_callback(F.callback.payload == "search_next")(self.handle_search_next)
        self.router.message_callback(F.callback.payload.startswith("search_reaction_"))(self.handle_search_reaction)


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
            await self.bot.send_message(chat_id, text="⚠️ Сначала пройдите регистрацию через /start")
            return
        builder = InlineKeyboardBuilder()
        builder.row(CallbackButton(text="📰 Читать", payload="start_reading"))
        await self.bot.send_message(chat_id=chat_id, text="Давайте почитаем новости!", attachments=[builder.as_markup()], parse_mode=ParseMode.MARKDOWN)


    async def handle_start_reading(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.message.answer(text="⚠️ Пользователь не найден")
            return
        await callback.message.delete()
        await self.load_and_show_news(chat_id, user)
        await callback.answer()


    async def handle_news_prev(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.message.answer(text="⚠️ Пользователь не найден")
            return
        await self.navigate_news(chat_id, user, callback.message, direction=-1)
        await callback.answer()


    async def handle_news_next(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.message.answer(text="⚠️ Пользователь не найден")
            return
        await self.navigate_news(chat_id, user, callback.message, direction=1)
        await callback.answer()


    async def handle_reaction(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.message.answer(text="⚠️ Пользователь не найден")
            return
        reaction_type = callback.callback.payload.replace("reaction_", "")
        await self.process_reaction(chat_id, user, callback.message, reaction_type)
        await callback.answer()


    async def handle_similar_news(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.answer("⚠️ Пользователь не найден")
            return
        news_id_str = callback.callback.payload.replace("similar_", "")
        if not news_id_str.isdigit():
            await callback.answer("⚠️ Некорректный ID новости")
            return
        news_id = int(news_id_str)
        news = self.db_session.query(News).get(news_id)
        if not news:
            await callback.answer("⚠️ Новость не найдена")
            return
        try:
            similar_news_list = self.search_engine.find_similar(
                news=news,
                session=self.db_session,
                top_n=10,
                exclude_same_category=False
            )
            similar_news_list = [sn for sn, score in similar_news_list if sn.category == news.category][:3]
        except Exception as e:
            logger.error(f"Ошибка поиска похожих новостей: {e}")
            await callback.answer("⚠️ Ошибка при поиске")
            return
        if not similar_news_list:
            await callback.answer("😔 Похожих новостей не найдено")
            return
        cache_key = f"{chat_id}_similar"
        self.user_news_cache[cache_key] = {
            'news': similar_news_list,
            'current_index': 0,
            'is_similar': True
        }
        await self.show_similar_news_at_index(chat_id, user, 0, callback.message)
        await callback.answer("🔍 Найдены похожие новости!")


    async def handle_similar_prev(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.answer("⚠️ Пользователь не найден")
            return
        cache_key = f"{chat_id}_similar"
        cache = self.user_news_cache.get(cache_key)
        if not cache:
            await callback.answer("⚠️ Сессия истекла")
            return
        new_index = cache['current_index'] - 1
        await self.show_similar_news_at_index(chat_id, user, new_index, callback.message)
        await callback.answer()


    async def handle_similar_next(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.answer("⚠️ Пользователь не найден")
            return
        cache_key = f"{chat_id}_similar"
        cache = self.user_news_cache.get(cache_key)
        if not cache:
            await callback.answer("⚠️ Сессия истекла")
            return
        new_index = cache['current_index'] + 1
        await self.show_similar_news_at_index(chat_id, user, new_index, callback.message)
        await callback.answer()


    async def handle_similar_reaction(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.answer("⚠️ Пользователь не найден")
            return
        reaction_type = callback.callback.payload.replace("similar_reaction_", "")
        cache_key = f"{chat_id}_similar"
        cache = self.user_news_cache.get(cache_key)
        if not cache:
            await callback.answer("⚠️ Сессия истекла")
            return
        current_index = cache['current_index']
        news = cache['news'][current_index]
        reaction_map = {
            'like': ReactionType.LIKE,
            'dislike': ReactionType.DISLIKE,
            'skip': ReactionType.SKIP
        }
        reaction = reaction_map.get(reaction_type)
        if not reaction:
            return
        try:
            process_user_reaction(user, news, reaction, self.db_session)
            if current_index < len(cache['news']) - 1:
                await self.show_similar_news_at_index(chat_id, user, current_index + 1, callback.message)
            else:
                await callback.message.edit_text(text="✅ Вы просмотрели все похожие новости!")
                del self.user_news_cache[cache_key]
        except Exception as e:
            logger.error(f"Ошибка реакции на похожую новость: {e}")
        await callback.answer()


    async def handle_search_command(self, event: MessageCreated):
        chat_id = event.get_ids()[0]
        user_id = event.message.sender.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await self.bot.send_message(chat_id, text="⚠️ Сначала пройдите регистрацию через /start", parse_mode=ParseMode.MARKDOWN)
            return

        text = event.message.body.text
        if not text:
            await self.bot.send_message(chat_id, text="⚠️ Пожалуйста, укажите текст для поиска. Например:\n/search футбол Россия", parse_mode=ParseMode.MARKDOWN)
            return

        keyword = text[len("/search"):].strip()
        if not keyword:
            await self.bot.send_message(chat_id, text="⚠️ Пожалуйста, укажите текст для поиска после команды.", parse_mode=ParseMode.MARKDOWN)
            return
        
        found_news = search_news_by_keyword(session=self.db_session, keyword=keyword, limit=10)

        if not found_news:
            await self.bot.send_message(chat_id, text=f"😔 По запросу «{keyword}» новостей не найдено.", parse_mode=ParseMode.MARKDOWN)
            return
        
        cache_key = f"{chat_id}_search"
        self.user_news_cache[cache_key] = {
            'news': found_news,
            'current_index': 0,
            'is_search': True,
            'keyword': keyword
        }
        
        await self.show_search_news_at_index(chat_id, user, 0)


    async def handle_search_prev(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.answer("⚠️ Пользователь не найден")
            return
        cache_key = f"{chat_id}_search"
        cache = self.user_news_cache.get(cache_key)
        if not cache:
            await callback.answer("⚠️ Сессия истекла")
            return
        new_index = cache['current_index'] - 1
        await self.show_search_news_at_index(chat_id, user, new_index, callback.message)
        await callback.answer()


    async def handle_search_next(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.answer("⚠️ Пользователь не найден")
            return
        cache_key = f"{chat_id}_search"
        cache = self.user_news_cache.get(cache_key)
        if not cache:
            await callback.answer("⚠️ Сессия истекла")
            return
        new_index = cache['current_index'] + 1
        await self.show_search_news_at_index(chat_id, user, new_index, callback.message)
        await callback.answer()


    async def handle_search_reaction(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        user_id = callback.callback.user.user_id
        user = self.db_session.query(User).filter(User.max_id == str(user_id)).first()
        if not user:
            await callback.answer("⚠️ Пользователь не найден")
            return
        reaction_type = callback.callback.payload.replace("search_reaction_", "")
        cache_key = f"{chat_id}_search"
        cache = self.user_news_cache.get(cache_key)
        if not cache:
            await callback.answer("⚠️ Сессия истекла")
            return
        current_index = cache['current_index']
        news = cache['news'][current_index]
        reaction_map = {
            'like': ReactionType.LIKE,
            'dislike': ReactionType.DISLIKE,
            'skip': ReactionType.SKIP
        }
        reaction = reaction_map.get(reaction_type)
        if not reaction:
            return
        try:
            process_user_reaction(user, news, reaction, self.db_session)
            if current_index < len(cache['news']) - 1:
                await self.show_search_news_at_index(chat_id, user, current_index + 1, callback.message)
            else:
                await callback.message.edit_text(text="✅ Вы просмотрели все найденные новости!")
                del self.user_news_cache[cache_key]
        except Exception as e:
            logger.error(f"Ошибка реакции на найденную новость: {e}")
        await callback.answer()


    async def show_search_news_at_index(self, chat_id: int, user: User, index: int, message_to_edit: Optional[object] = None):
        cache_key = f"{chat_id}_search"
        cache = self.user_news_cache.get(cache_key)
        if not cache or not cache['news']:
            await self.bot.send_message(chat_id, text="⚠️ Найденные новости не загружены")
            return
        
        news_list = cache['news']
        keyword = cache.get('keyword', '')
        index = max(0, min(index, len(news_list) - 1))
        cache['current_index'] = index
        news = news_list[index]
        
        text = self.format_search_news_message(news, index + 1, len(news_list), keyword)
        keyboard = self.build_search_news_keyboard(index, len(news_list))
        
        if message_to_edit:
            try:
                await message_to_edit.edit_text(text=text, attachments=[keyboard], parse_mode=ParseMode.MARKDOWN)
            except:
                await self.bot.send_message(chat_id, text=text, attachments=[keyboard], parse_mode=ParseMode.MARKDOWN)
        else:
            await self.bot.send_message(chat_id, text=text, attachments=[keyboard], parse_mode=ParseMode.MARKDOWN)


    def format_search_news_message(self, news: News, current: int, total: int, keyword: str) -> str:
        emoji_map = {
            "climate": "🌍", "conflicts": "⚔️", "culture": "🎭", "economy": "💰",
            "gloss": "🙂", "health": "🏥", "politics": "🏛️", "science": "🔬",
            "society": "👥", "sports": "⚽", "travel": "✈️"
        }
        emoji = emoji_map.get(news.category.value, "📰")
        content = news.content[:800] + "..." if len(news.content) > 800 else news.content
        text = f"🔎 *Результат поиска: «{keyword}»*\n\n{emoji} *{news.title}*\n\n{content}\n\n📌 {news.source_name}\n"
        if news.source_url:
            text += f"🔗 [Читать полностью]({news.source_url})\n"
        text += f"\n📊 Найденная новость {current} из {total}"
        return text


    def build_search_news_keyboard(self, current_index: int, total_count: int):
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(text="👍", payload="search_reaction_like"),
            CallbackButton(text="🤷", payload="search_reaction_skip"),
            CallbackButton(text="👎", payload="search_reaction_dislike")
        )
        nav_buttons = []
        if current_index > 0:
            nav_buttons.append(CallbackButton(text="⬅️", payload="search_prev"))
        if current_index < total_count - 1:
            nav_buttons.append(CallbackButton(text="➡️", payload="search_next"))
        if nav_buttons:
            builder.row(*nav_buttons)
        return builder.as_markup()


    async def load_and_show_news(self, chat_id: int, user: User, count: int = 10):
        last_calc = self.user_score_cache_time.get(user.id)
        now = datetime.utcnow()
        if not last_calc or (now - last_calc) > timedelta(minutes=30):
            from utils.recomendation import precompute_scores_for_user
            precompute_scores_for_user(user, self.db_session)
            self.user_score_cache_time[user.id] = now
        news_list = get_recommended_news(user=user, n=count, session=self.db_session, diversity_factor=0.2)
        if not news_list:
            await self.bot.send_message(chat_id, text="😔 К сожалению, новых новостей для вас пока нет.")
            return
        self.user_news_cache[chat_id] = {'news': news_list, 'current_index': 0}
        await self.show_news_at_index(chat_id, user, 0)


    async def show_news_at_index(self, chat_id: int, user: User, index: int, message_to_edit: Optional[object] = None):
        cache = self.user_news_cache.get(chat_id)
        if not cache or not cache['news']:
            await self.bot.send_message(chat_id, text="⚠️ Новости не загружены")
            return
        news_list = cache['news']
        index = max(0, min(index, len(news_list) - 1))
        cache['current_index'] = index
        news = news_list[index]
        text = self.format_news_message(news, index + 1, len(news_list))
        keyboard = self.build_news_keyboard(index, len(news_list), news.id)
        if message_to_edit:
            try:
                await message_to_edit.edit_text(text=text, attachments=[keyboard])
            except:
                await self.bot.send_message(chat_id, text=text, attachments=[keyboard], parse_mode=ParseMode.MARKDOWN)
        else:
            await self.bot.send_message(chat_id, text=text, attachments=[keyboard], parse_mode=ParseMode.MARKDOWN)


    async def show_similar_news_at_index(self, chat_id: int, user: User, index: int, message_to_edit: Optional[object] = None):
        cache_key = f"{chat_id}_similar"
        cache = self.user_news_cache.get(cache_key)
        if not cache or not cache['news']:
            await self.bot.send_message(chat_id, text="⚠️ Похожие новости не загружены")
            return
        news_list = cache['news']
        index = max(0, min(index, len(news_list) - 1))
        cache['current_index'] = index
        news = news_list[index]
        text = self.format_similar_news_message(news, index + 1, len(news_list))
        keyboard = self.build_similar_news_keyboard(index, len(news_list))
        if message_to_edit:
            try:
                await message_to_edit.edit_text(text=text, attachments=[keyboard])
            except:
                await self.bot.send_message(chat_id, text=text, attachments=[keyboard], parse_mode=ParseMode.MARKDOWN)
        else:
            await self.bot.send_message(chat_id, text=text, attachments=[keyboard], parse_mode=ParseMode.MARKDOWN)


    def format_news_message(self, news: News, current: int, total: int) -> str:
        emoji_map = {
            "climate": "🌍", "conflicts": "⚔️", "culture": "🎭", "economy": "💰",
            "gloss": "🙂", "health": "🏥", "politics": "🏛️", "science": "🔬",
            "society": "👥", "sports": "⚽", "travel": "✈️"
        }
        emoji = emoji_map.get(news.category.value, "📰")
        content = news.content[:800] + "..." if len(news.content) > 800 else news.content
        text = f"{emoji} *{news.title}*\n\n{content}\n\n📌 {news.source_name}\n"
        if news.source_url:
            text += f"🔗 [Читать полностью]({news.source_url})\n"
        text += f"\n📊 Новость {current} из {total}"
        return text


    def format_similar_news_message(self, news: News, current: int, total: int) -> str:
        emoji_map = {
            "climate": "🌍", "conflicts": "⚔️", "culture": "🎭", "economy": "💰",
            "gloss": "🙂", "health": "🏥", "politics": "🏛️", "science": "🔬",
            "society": "👥", "sports": "⚽", "travel": "✈️"
        }
        emoji = emoji_map.get(news.category.value, "📰")
        content = news.content[:800] + "..." if len(news.content) > 800 else news.content
        text = f"🔍 *Похожая новость*\n\n{emoji} *{news.title}*\n\n{content}\n\n📌 {news.source_name}\n"
        if news.source_url:
            text += f"🔗 [Читать полностью]({news.source_url})\n"
        text += f"\n📊 Похожая новость {current} из {total}"
        return text


    def build_news_keyboard(self, current_index: int, total_count: int, news_id: int):
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
        builder.row(
            CallbackButton(text="🔍 Похожие новости", payload=f"similar_{news_id}")
        )
        return builder.as_markup()


    def build_similar_news_keyboard(self, current_index: int, total_count: int):
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(text="👍", payload="similar_reaction_like"),
            CallbackButton(text="🤷", payload="similar_reaction_skip"),
            CallbackButton(text="👎", payload="similar_reaction_dislike")
        )
        nav_buttons = []
        if current_index > 0:
            nav_buttons.append(CallbackButton(text="⬅️", payload="similar_prev"))
        if current_index < total_count - 1:
            nav_buttons.append(CallbackButton(text="➡️", payload="similar_next"))
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
