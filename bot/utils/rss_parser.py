import fasttext
import numpy as np
import re
from typing import Tuple, Optional, List, Dict
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

import feedparser
from sqlalchemy.orm import Session
from html import unescape


class NewsClassifier:
    """Классификатор новостей на основе fastText"""

    def __init__(self, model_path: str):
        """
        Инициализация классификатора

        Args:
            model_path: Путь к обученной модели fastText (.bin файл)
        """
        self.model = fasttext.load_model(model_path)

        # Маппинг меток fastText на ваши категории
        self.label_mapping = {
            '__label__climate': 'CLIMATE',
            '__label__conflicts': 'CONFLICTS',
            '__label__culture': 'CULTURE',
            '__label__economy': 'ECONOMY',
            '__label__gloss': 'GLOSS',
            '__label__health': 'HEALTH',
            '__label__politics': 'POLITICS',
            '__label__science': 'SCIENCE',
            '__label__society': 'SOCIETY',
            '__label__sports': 'SPORTS',
            '__label__travel': 'TRAVEL',
        }

    def preprocess_text(self, text: str) -> str:
        """Предобработка текста для классификации"""
        text = text.lower()
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'http\S+|www.\S+', '', text)
        return text

    def classify(self, title: str, content: str, k: int = 1) -> Tuple[str, float]:
        """Классифицирует новость"""
        # Заголовок дважды, так как он важнее
        combined_text = f"{title} {title} {content}"
        processed_text = self.preprocess_text(combined_text)

        labels, probabilities = self.model.predict(processed_text, k=k)

        top_label = labels[0].replace('__label__', '')
        top_probability = float(probabilities[0])

        full_label = f'__label__{top_label}'
        category = self.label_mapping.get(full_label, 'SOCIETY')

        return category, top_probability


# ==================== УТИЛИТЫ ====================

def clean_html(html_text: str) -> str:
    """Удаляет HTML теги и декодирует HTML сущности"""
    if not html_text:
        return ""
    text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', html_text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_full_text_from_rss(entry: dict) -> str:
    """
    Извлекает максимально полный текст из RSS entry
    Пробует разные поля в порядке приоритета

    Args:
        entry: Элемент feedparser entry

    Returns:
        Максимально полный текст из RSS
    """
    # Приоритет полей для извлечения текста:
    # 1. content (обычно полный текст) - используется в RSS 2.0
    # 2. summary_detail
    # 3. description (краткое описание)
    # 4. summary (самое краткое)

    full_text = ""

    # 1. Пробуем content (может содержать полную статью)
    if 'content' in entry and entry.content:
        # content это список, берем первый элемент
        content_item = entry.content[0]
        if 'value' in content_item:
            full_text = content_item['value']

    # 2. Для RBC: специальное поле rbc_news:full-text
    if not full_text and 'rbc_news_full-text' in entry:
        full_text = entry['rbc_news_full-text']

    # 3. Если не нашли в content, пробуем summary_detail
    if not full_text and hasattr(entry, 'summary_detail'):
        full_text = entry.summary_detail.get('value', '')

    # 4. Если все еще пусто, берем description
    if not full_text and 'description' in entry:
        full_text = entry.description

    # 5. Последний шанс - summary
    if not full_text and 'summary' in entry:
        full_text = entry.summary

    return full_text


def is_recent_news(published_time: Optional[datetime], hours: int = 1) -> bool:
    """
    Проверяет, является ли новость свежей (за последние N часов)

    Args:
        published_time: Время публикации новости
        hours: Количество часов (по умолчанию 1)

    Returns:
        True если новость свежая, False иначе
    """
    if not published_time:
        return True

    now = datetime.utcnow()
    time_threshold = now - timedelta(hours=hours)

    return published_time >= time_threshold


# ==================== RSS ПАРСЕР С КЛАССИФИКАЦИЕЙ И ФИЛЬТРАЦИЕЙ ====================

def parse_rss_and_populate_db(
    rss_url: str,
    source_name: str,
    session: Session,
    News,
    NewsCategory,
    classifier: NewsClassifier,
    hours_filter: int = 1,
    limit: int = None
) -> List[Dict]:
    """
    Универсальный парсер RSS с автоматической классификацией
    Парсит только новости за последние N часов
    Извлекает максимум текста из самого RSS (без парсинга HTML)

    Args:
        rss_url: URL RSS фида
        source_name: Название источника
        session: SQLAlchemy session
        News: ORM модель News
        NewsCategory: Enum категорий
        classifier: Объект NewsClassifier для классификации
        hours_filter: Парсить новости за последние N часов (по умолчанию 1)
        limit: Максимальное количество записей

    Returns:
        Список добавленных новостей с ID
    """

    try:
        feed = feedparser.parse(rss_url)
        added_news = []
        skipped_old = 0

        entries = feed.entries[:limit] if limit else feed.entries

        for entry in entries:
            try:
                # ============ ИЗВЛЕКАЕМ ДАТУ ПУБЛИКАЦИИ ============
                published = None
                if 'published_parsed' in entry and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6])
                elif 'updated_parsed' in entry and entry.updated_parsed:
                    published = datetime(*entry.updated_parsed[:6])

                # ============ ФИЛЬТРАЦИЯ ПО ВРЕМЕНИ ============
                if not is_recent_news(published, hours=hours_filter):
                    skipped_old += 1
                    continue

                # ============ ИЗВЛЕКАЕМ ДАННЫЕ ============
                title = entry.get('title', '').strip()
                title = clean_html(title)

                # Обычное краткое описание (для сохранения в БД)
                description = entry.get('description', '') or entry.get('summary', '')
                content = clean_html(description)

                # Полный текст из RSS (для классификации)
                full_text_from_rss = extract_full_text_from_rss(entry)
                full_text_cleaned = clean_html(full_text_from_rss)

                source_url = entry.get('link', '').strip()

                if not title or not content:
                    continue

                # ============ КЛАССИФИКАЦИЯ С FASTTEXT ============
                # Используем полный текст из RSS если он есть, иначе description
                classification_text = full_text_cleaned if len(full_text_cleaned) > len(content) else content

                category_str, confidence = classifier.classify(title, classification_text)

                try:
                    category_enum = NewsCategory[category_str]
                except KeyError:
                    category_enum = NewsCategory.SOCIETY
                    confidence = 0.0

                # ============ ПРОВЕРКА НА ДУБЛИКАТЫ ============
                existing = session.query(News).filter(
                    News.title == title[:300],
                    News.source_name == source_name
                ).first()

                if existing:
                    continue

                # Создаем summary (из краткого описания)
                summary = content[:300] if len(content) > 300 else None

                # ============ СОЗДАЕМ ОБЪЕКТ NEWS ============
                # В БД сохраняем ТОЛЬКО краткое описание
                news_item = News(
                    title=title[:300],
                    content=content,  # Краткое описание из description
                    summary=summary,
                    category=category_enum,
                    category_confidence=confidence,
                    source_url=source_url[:500] if source_url else None,
                    source_name=source_name,
                    total_shown=0,
                    total_reactions=0,
                    created_at=published or datetime.utcnow()
                )

                session.add(news_item)
                session.flush()

                added_news.append({
                    'id': news_item.id,
                    'title': title[:50] + '...' if len(title) > 50 else title,
                    'source': source_name,
                    'category': category_str,
                    'confidence': f"{confidence:.2f}",
                    'published': published.strftime('%H:%M') if published else 'N/A',
                    'url': source_url,
                    'used_full_rss': len(full_text_cleaned) > len(content)
                })

            except Exception as e:
                print(f"⚠️  Ошибка при обработке записи: {str(e)}")
                continue

        try:
            session.commit()
            full_rss_count = sum(1 for item in added_news if item.get('used_full_rss'))
            print(f"✅ {source_name}: добавлено {len(added_news)} новостей "
                  f"(полный RSS текст: {full_rss_count}, пропущено старых: {skipped_old})")
        except Exception as e:
            session.rollback()
            print(f"❌ Ошибка при сохранении: {str(e)}")
            return []

        return added_news

    except Exception as e:
        print(f"❌ Ошибка при парсинге {rss_url}: {str(e)}")
        return []


# ==================== ПРИМЕР ИСПОЛЬЗОВАНИЯ ====================

if __name__ == "__main__":
    print("="*70)
    print("RSS ПАРСЕР С ИЗВЛЕЧЕНИЕМ ПОЛНОГО ТЕКСТА ИЗ RSS")
    print("="*70)

    print("""
ОСОБЕННОСТИ:
  ✓ Извлекает максимум текста из самого RSS (без парсинга HTML)
  ✓ Пробует разные поля: content, rbc_news:full-text, summary_detail
  ✓ В БД сохраняется только краткое описание (content/summary)
  ✓ Полный текст из RSS используется ТОЛЬКО для классификации
  ✓ Фильтрация по времени: последний час
  ✓ НЕТ парсинга HTML - только RSS

ПОЛЯ RSS ДЛЯ ИЗВЛЕЧЕНИЯ (по приоритету):
  1. <content> - полный текст (RSS 2.0)
  2. <rbc_news:full-text> - для RBC
  3. <summary_detail> - расширенное описание
  4. <description> - краткое описание
  5. <summary> - самое краткое

ИСПОЛЬЗОВАНИЕ:

from sqlalchemy.orm import sessionmaker
from your_models import News, NewsCategory

classifier = NewsClassifier("models/news_classifier.bin")
Session = sessionmaker(bind=engine)
session = Session()

rss_sources = [
    {"url": "https://elementy.ru/rss/news/it", "name": "Elementy IT"},
    {"url": "https://www.cnews.ru/inc/rss/news.xml", "name": "CNews"},
    {"url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "name": "RBC"},
    # ... остальные
]

for source in rss_sources:
    results = parse_rss_and_populate_db(
        rss_url=source["url"],
        source_name=source["name"],
        session=session,
        News=News,
        NewsCategory=NewsCategory,
        classifier=classifier,
        hours_filter=1
    )

ТРЕБОВАНИЯ:
  • pip install fasttext feedparser
    """)
