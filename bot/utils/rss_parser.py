import fasttext
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
        combined_text = f"{title} {title} {content}"
        processed_text = self.preprocess_text(combined_text)

        labels, probabilities = self.model.predict(processed_text, k=k)

        top_label = labels[0].replace('__label__', '')
        top_probability = float(probabilities[0])

        full_label = f'__label__{top_label}'
        category = self.label_mapping.get(full_label, 'SOCIETY')

        return category, top_probability



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
    full_text = ""

    if 'content' in entry and entry.content:
        content_item = entry.content[0]
        if 'value' in content_item:
            full_text = content_item['value']

    if not full_text and 'rbc_news_full-text' in entry:
        full_text = entry['rbc_news_full-text']

    if not full_text and hasattr(entry, 'summary_detail'):
        full_text = entry.summary_detail.get('value', '')

    if not full_text and 'description' in entry:
        full_text = entry.description

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


def parse_rss_and_populate_db(
    rss_url: str,
    source_name: str,
    session: Session,
    News,
    NewsCategory,
    classifier: Optional[NewsClassifier] = None,
    hours_filter: int = 1,
    limit: Optional[int] = None,
    fixed_category: Optional[str] = None,
    skip_classification: bool = False
) -> List[Dict]:
    """
    Универсальный парсер RSS с опциональной классификацией
    Парсит только новости за последние N часов
    Извлекает максимум текста из самого RSS (без парсинга HTML)
    
    Оптимизации:
    - Батчевая вставка через bulk_insert_mappings
    - Предварительная проверка существующих новостей одним запросом
    - Опциональная классификация через fixed_category

    Args:
        rss_url: URL RSS фида
        source_name: Название источника
        session: SQLAlchemy session
        News: ORM модель News
        NewsCategory: Enum категорий
        classifier: Объект NewsClassifier для классификации (опционально)
        hours_filter: Парсить новости за последние N часов (по умолчанию 1)
        limit: Максимальное количество записей
        fixed_category: Если указана, все новости получат эту категорию (минус AI)
        skip_classification: Если True, пропускает вызов классификатора

    Returns:
        Список добавленных новостей с ID
    """
    try:
        feed = feedparser.parse(rss_url)
        added_news = []
        skipped_old = 0

        entries = feed.entries[:limit] if limit else feed.entries

        titles_to_check = []
        entries_data = []

        for entry in entries:
            try:
                published = None
                if 'published_parsed' in entry and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6])
                elif 'updated_parsed' in entry and entry.updated_parsed:
                    published = datetime(*entry.updated_parsed[:6])

                if not is_recent_news(published, hours=hours_filter):
                    skipped_old += 1
                    continue

                title = entry.get('title', '').strip()
                title = clean_html(title)

                description = entry.get('description', '') or entry.get('summary', '')
                content = clean_html(description)

                full_text_from_rss = extract_full_text_from_rss(entry)
                full_text_cleaned = clean_html(full_text_from_rss)

                source_url = entry.get('link', '').strip()

                if not title or not content:
                    continue

                titles_to_check.append(title[:300])
                entries_data.append({
                    'title': title,
                    'content': content,
                    'full_text_cleaned': full_text_cleaned,
                    'source_url': source_url,
                    'published': published
                })

            except Exception as e:
                print(f"⚠️  Ошибка при обработке записи: {str(e)}")
                continue

        existing_titles = set()
        if titles_to_check:
            existing_news = session.query(News.title).filter(
                News.title.in_(titles_to_check),
                News.source_name == source_name
            ).all()
            existing_titles = {title[0] for title in existing_news}

        news_to_insert = []

        for entry_data in entries_data:
            title = entry_data['title']
            
            if title[:300] in existing_titles:
                continue

            content = entry_data['content']
            full_text_cleaned = entry_data['full_text_cleaned']
            source_url = entry_data['source_url']
            published = entry_data['published']

            if fixed_category:
                category_str = fixed_category
                confidence = 1.0
            elif skip_classification:
                category_str = 'SOCIETY'
                confidence = 0.5
            else:
                if not classifier:
                    raise ValueError("Classifier required when fixed_category is not set")
                
                classification_text = full_text_cleaned if len(full_text_cleaned) > len(content) else content
                category_str, confidence = classifier.classify(title, classification_text)

            # Преобразуем в enum
            try:
                category_enum = NewsCategory[category_str]
            except KeyError:
                category_enum = NewsCategory.SOCIETY
                confidence = 0.0

            summary = content[:300] if len(content) > 300 else None

            # Подготавливаем словарь для bulk_insert_mappings
            news_to_insert.append({
                'title': title[:300],
                'content': content,
                'summary': summary,
                'category': category_enum,
                'category_confidence': confidence,
                'source_url': source_url[:500] if source_url else None,
                'source_name': source_name,
                'total_shown': 0,
                'total_reactions': 0,
                'created_at': published or datetime.utcnow()
            })

            added_news.append({
                'title': title[:50] + '...' if len(title) > 50 else title,
                'source': source_name,
                'category': category_str,
                'confidence': f"{confidence:.2f}",
                'published': published.strftime('%H:%M') if published else 'N/A',
                'url': source_url,
                'used_full_rss': len(full_text_cleaned) > len(content),
                'used_fixed_category': bool(fixed_category)
            })

        # Батчевая вставка всех новостей
        if news_to_insert:
            try:
                session.bulk_insert_mappings(News, news_to_insert)
                session.commit()
                
                full_rss_count = sum(1 for item in added_news if item.get('used_full_rss'))
                fixed_cat_count = sum(1 for item in added_news if item.get('used_fixed_category'))
                
                print(f"✅ {source_name}: добавлено {len(added_news)} новостей "
                      f"(полный RSS: {full_rss_count}, фикс. категория: {fixed_cat_count}, "
                      f"пропущено старых: {skipped_old})")
            except Exception as e:
                session.rollback()
                print(f"❌ Ошибка при сохранении: {str(e)}")
                return []
        else:
            print(f"ℹ️  {source_name}: новых новостей не найдено (пропущено старых: {skipped_old})")

        return added_news

    except Exception as e:
        print(f"❌ Ошибка при парсинге {rss_url}: {str(e)}")
        return []


def parse_multiple_rss_sources(
    sources: List[Dict],
    session: Session,
    News,
    NewsCategory,
    classifier: Optional[NewsClassifier] = None,
    hours_filter: int = 1
) -> Dict[str, List[Dict]]:
    """
    Парсит несколько RSS источников последовательно
    
    Args:
        sources: Список словарей с параметрами источников
                 Формат: [{"url": "...", "name": "...", "fixed_category": "..." (опционально)}, ...]
        session: SQLAlchemy session
        News: ORM модель News
        NewsCategory: Enum категорий
        classifier: Объект NewsClassifier
        hours_filter: Парсить новости за последние N часов
    
    Returns:
        Словарь {source_name: [added_news]}
    """
    results = {}
    
    for source in sources:
        url = source.get('url')
        name = source.get('name')
        fixed_category = source.get('fixed_category')
        
        if not url or not name:
            print(f"⚠️  Пропущен источник: отсутствует url или name")
            continue
        
        added = parse_rss_and_populate_db(
            rss_url=url,
            source_name=name,
            session=session,
            News=News,
            NewsCategory=NewsCategory,
            classifier=classifier,
            hours_filter=hours_filter,
            fixed_category=fixed_category,
            skip_classification=False
        )
        
        results[name] = added
    
    return results
