from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from typing import List, Optional, Set
from models import News, NewsCategory

def search_news_by_keyword(
    session : Session, 
    keyword: str, 
    limit: int = 3,
    category: Optional[NewsCategory] = None
) -> List[News]:
    """
    Поиск новостей по ключевому слову в заголовке и содержимом
    
    Args:
        session: SQLAlchemy session
        keyword: Ключевое слово для поиска
        limit: Максимальное количество результатов
        category: Опциональная фильтрация по категории
    
    Returns:
        Список найденных новостей
    """
    query = session.query(News)
    
    search_pattern = f"%{keyword.lower()}%"
    query = query.filter(
        or_(
            func.lower(News.title).like(search_pattern),
            func.lower(News.content).like(search_pattern)
        )
    )
    
    if category:
        query = query.filter(News.category == category)
    
    query = query.order_by(
        func.lower(News.title).like(search_pattern).desc(),
        News.created_at.desc()
    )
    
    return query.limit(limit).all()


from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from typing import List, Tuple

def load_stopwords(filepath: str) -> Set[str]:
    """
    Загружает стоп-слова из текстового файла
    
    Args:
        filepath: Путь к файлу со стоп-словами (одно слово на строку)
    
    Returns:
        Множество стоп-слов
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            stopwords = set(line.strip().lower() for line in f if line.strip())
        return stopwords
    except Exception as e:
        print(f"⚠️ Ошибка при загрузке стоп-слов: {e}")
        return set()

class NewsSearchEngine:
    """Движок поиска похожих новостей на основе TF-IDF"""
    def __init__(self):
        self.vectorizer = TfidfVectorizer(
            max_features=1000,
            stop_words=list(load_stopwords("/app/models/")),
            ngram_range=(1, 2),
            min_df=1
        )
        self.news_vectors = None
        self.news_ids = None
    
    def fit(self, session):
        """
        Обучение на всех новостях из базы
        Вызывайте периодически для обновления индекса
        """
        news_list = session.query(News).all()
        
        if not news_list:
            return
        
        # Создаем корпус текстов
        corpus = [f"{news.title} {news.content}" for news in news_list]
        self.news_ids = [news.id for news in news_list]
        
        # Векторизация
        self.news_vectors = self.vectorizer.fit_transform(corpus)
    
    def find_similar(
        self, 
        news: News, 
        session : Session,
        top_n: int = 10,
        exclude_same_category: bool = False
    ) -> List[Tuple[News, float]]:
        """
        Поиск похожих новостей
        
        Args:
            news: Новость, для которой ищем похожие
            session: SQLAlchemy session
            top_n: Количество результатов
            exclude_same_category: Исключить новости той же категории
        
        Returns:
            Список кортежей (News, similarity_score)
        """
        if self.news_vectors is None:
            self.fit(session)
        
        query_text = f"{news.title} {news.content}"
        query_vector = self.vectorizer.transform([query_text])
        
        similarities = cosine_similarity(query_vector, self.news_vectors)[0]
        similar_indices = np.argsort(similarities)[::-1]
        
        results = []
        for idx in similar_indices:
            news_id = self.news_ids[idx]
            
            if news_id == news.id:
                continue
            
            similar_news = session.query(News).get(news_id)
            
            if not similar_news:
                continue
            
            if exclude_same_category and similar_news.category == news.category:
                continue
            
            similarity_score = float(similarities[idx])
            results.append((similar_news, similarity_score))
            
            if len(results) >= top_n:
                break
        
        return results
    
    def search_by_text(
        self, 
        query_text: str, 
        session,
        top_n: int = 10,
        category: Optional[NewsCategory] = None
    ) -> List[Tuple[News, float]]:
        """
        Поиск новостей по произвольному тексту запроса
        
        Args:
            query_text: Текст запроса
            session: SQLAlchemy session
            top_n: Количество результатов
            category: Опциональная фильтрация по категории
        
        Returns:
            Список кортежей (News, relevance_score)
        """
        if self.news_vectors is None:
            self.fit(session)
        
        query_vector = self.vectorizer.transform([query_text])
        
        similarities = cosine_similarity(query_vector, self.news_vectors)[0]
        
        similar_indices = np.argsort(similarities)[::-1][:top_n * 2]
        
        results = []
        for idx in similar_indices:
            news_id = self.news_ids[idx]
            similar_news = session.query(News).get(news_id)
            
            if not similar_news:
                continue
            
            if category and similar_news.category != category:
                continue
            
            similarity_score = float(similarities[idx])
            
            if similarity_score > 0.1:
                results.append((similar_news, similarity_score))
            
            if len(results) >= top_n:
                break
        
        return results
