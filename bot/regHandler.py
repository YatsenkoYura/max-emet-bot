from maxapi import Dispatcher, Bot
from maxapi.types import BotStarted, MessageCallback, MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types import CallbackButton
from sqlalchemy.orm import Session
from models import User, UserStats, NewsCategory, UserCategoryWeight
from datetime import datetime


user_states = {}


def create_default_category_weights(user_id: int, selected_categories: list = None):
    """
    Создает начальные веса для всех категорий новостей
    selected_categories: список категорий, которые выбрал пользователь
    """
    weights = []
    
    for category in NewsCategory:
        # Если пользователь выбрал категорию, ставим вес выше
        if selected_categories and category.value in selected_categories:
            initial_weight = 0.8
        else:
            initial_weight = 0.3
        
        weight = UserCategoryWeight(
            user_id=user_id,
            category=category,
            weight=initial_weight,
            positive_reactions=0,
            negative_reactions=0,
            neutral_reactions=0,
            total_shown=0,
            confidence=0.0
        )
        weights.append(weight)
    
    return weights


class RegHandler():
    def __init__(self, bot: Bot, dp: Dispatcher, db_session: Session):
        self.bot = bot
        self.dp = dp
        self.db_session = db_session
        self.register_handler()
        self.user_add_info = {}
        
        self.category_names = {
            "climate": "🌍 Климат",
            "conflicts": "⚔️ Конфликты",
            "culture": "🎭 Культура",
            "economy": "💰 Экономика",
            "gloss": "🙂 Желтуха",
            "health": "🏥 Здоровье",
            "politics": "🏛️ Политика",
            "science": "🔬 Наука",
            "society": "👥 Общество",
            "sports": "⚽ Спорт",
            "travel": "✈️ Путешествия"
        }


    def register_handler(self):
        self.dp.bot_started()(self.start_reg)
        self.dp.message_callback()(self.handle_callbacks)
        self.dp.message_created()(self.handle_user_input_age)


    async def start_reg(self, event: BotStarted):
        """Начало работы с ботом - всегда с чистого листа"""
        chat_id = event.chat_id
        user_id = event.user.user_id
        
        try:
            # Проверяем, есть ли уже пользователь в БД
            existing_user = self.db_session.query(User).filter(
                User.max_id == str(user_id)
            ).first()
            
            if existing_user:
                print(f"🗑️ Найден существующий пользователь {user_id}, удаляем...")
                
                # Удаляем старого пользователя со всеми данными
                self.db_session.delete(existing_user)
                self.db_session.commit()
                
                print(f"✅ Старый профиль удален, начинаем с нуля")
            
            # Очищаем временные данные если остались
            if chat_id in self.user_add_info:
                del self.user_add_info[chat_id]
            if chat_id in user_states:
                del user_states[chat_id]
            
        except Exception as e:
            self.db_session.rollback()
            print(f"❌ Ошибка при очистке данных: {e}")
            import traceback
            traceback.print_exc()
        
        # Инициализируем данные для нового пользователя
        self.user_add_info[chat_id] = {
            "age": None,
            "gender": None,
            "categories": set(),
            "max_id": user_id,
            "username": None
        }
        
        # Начинаем регистрацию
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(text="👨 Мужчина", payload="m_gender"),
            CallbackButton(text="👱‍♀️ Женщина", payload="f_gender"),
        )
        
        await self.bot.send_message(
            chat_id=chat_id,
            text=(
                "Привет! Прежде чем перейти к использованию, "
                "пройдите простую регистрацию.\n\nВыберите свой пол:"
            ),
            attachments=[builder.as_markup()]
        )


    async def handle_callbacks(self, callback: MessageCallback):
        chat_id = callback.chat.chat_id
        payload = callback.callback.payload
        
        await callback.message.delete()
        
        if chat_id not in self.user_add_info:
            self.user_add_info[chat_id] = {
                "age": None,
                "gender": None,
                "categories": set(),
                "max_id": callback.callback.user.user_id,
                "username": callback.callback.user.username
            }
        
        if payload == "f_gender":
            self.user_add_info[chat_id]["gender"] = "f"
            self.user_add_info[chat_id]["max_id"] = callback.callback.user.user_id
            self.user_add_info[chat_id]["username"] = callback.callback.user.username
            
            await self.bot.send_message(
                chat_id,
                text="Спасибо!\nУкажите свой возраст (отправьте число):"
            )
            user_states[chat_id] = 'waiting_for_age'
        
        elif payload == "m_gender":
            self.user_add_info[chat_id]["gender"] = "m"
            self.user_add_info[chat_id]["max_id"] = callback.callback.user.user_id
            self.user_add_info[chat_id]["username"] = callback.callback.user.username
            
            await self.bot.send_message(
                chat_id,
                text="Спасибо!\nУкажите свой возраст (отправьте число):"
            )
            user_states[chat_id] = 'waiting_for_age'
        
        elif payload.startswith("cat_"):
            category = payload.replace("cat_", "")
            
            if category in self.user_add_info[chat_id]["categories"]:
                self.user_add_info[chat_id]["categories"].remove(category)
            else:
                self.user_add_info[chat_id]["categories"].add(category)
            
            await self.show_category_selection(chat_id)
        
        elif payload == "finish_categories":
            if len(self.user_add_info[chat_id]["categories"]) > 0:
                await self.save_user_to_db(chat_id)
                await self.bot.send_message(
                    chat_id,
                    text="✅ Регистрация завершена! Начинаем подбирать новости для вас..."
                )
            else:
                await self.bot.send_message(
                    chat_id,
                    text="⚠️ Выберите хотя бы одну категорию!"
                )


    async def handle_user_input_age(self, event: MessageCreated):
        chat_id = event.get_ids()[0]
        
        if user_states.get(chat_id) == 'waiting_for_age':
            user_text = event.message.body.text
            
            if user_text and user_text.isdigit():
                age = int(user_text)
                
                if 5 <= age <= 120:
                    self.user_add_info[chat_id]["age"] = age
                    await event.message.answer(
                        text="Отлично! Теперь выберите интересующие вас категории новостей:"
                    )
                    
                    del user_states[chat_id]
                    await self.show_category_selection(chat_id)
                else:
                    await event.message.answer(
                        text="⚠️ Укажите корректный возраст (от 5 до 120 лет)."
                    )
            else:
                await event.message.answer(
                    text='⚠️ Ошибка! Пожалуйста, отправьте только цифры.'
                )


    async def show_category_selection(self, chat_id: int):
        """Показывает клавиатуру с категориями"""
        builder = InlineKeyboardBuilder()
        
        selected = self.user_add_info[chat_id]["categories"]
        
        categories = list(self.category_names.items())
        for i in range(0, len(categories), 2):
            row_buttons = []
            
            for j in range(2):
                if i + j < len(categories):
                    cat_key, cat_name = categories[i + j]
                    prefix = "✅ " if cat_key in selected else ""
                    row_buttons.append(
                        CallbackButton(
                            text=f"{prefix}{cat_name}",
                            payload=f"cat_{cat_key}"
                        )
                    )
            
            builder.row(*row_buttons)
        
        builder.row(
            CallbackButton(
                text=f"✅ Готово ({len(selected)} выбрано)",
                payload="finish_categories"
            )
        )
        
        await self.bot.send_message(
            chat_id,
            text=(
                f"Выбрано категорий: {len(selected)}\n"
                "Нажмите на категории, которые вас интересуют:"
            ),
            attachments=[builder.as_markup()]
        )


    async def save_user_to_db(self, chat_id: int):
        """Сохраняет нового пользователя в БД"""
        user_info = self.user_add_info[chat_id]
        
        try:
            # Создаем пользователя (он всегда новый, старый удален в start_reg)
            new_user = User(
                max_id=str(user_info["max_id"]),
                username=user_info["username"],
                gender=user_info["gender"],
                age=user_info["age"],
                created_at=datetime.utcnow(),
                last_active=datetime.utcnow()
            )
            
            self.db_session.add(new_user)
            self.db_session.flush()  # Получаем ID
            
            # Создаем веса категорий
            category_weights = create_default_category_weights(
                user_id=new_user.id,
                selected_categories=list(user_info["categories"])
            )
            
            self.db_session.add_all(category_weights)
            
            # Создаем статистику
            user_stats = UserStats(
                user_id=new_user.id,
                total_news_shown=0,
                total_reactions=0,
                engagement_rate=0.0
            )
            
            self.db_session.add(user_stats)
            self.db_session.commit()
            
            print(f"✅ Новый пользователь {new_user.max_id} успешно создан")
            
            # Очищаем временные данные
            del self.user_add_info[chat_id]
            
            return new_user
            
        except Exception as e:
            self.db_session.rollback()
            print(f"❌ Ошибка при сохранении пользователя: {e}")
            import traceback
            traceback.print_exc()
            
            await self.bot.send_message(
                chat_id,
                text="❌ Произошла ошибка при сохранении. Попробуйте еще раз."
            )
            
            raise
