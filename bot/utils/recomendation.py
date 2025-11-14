from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from datetime import datetime, timedelta
from typing import List, Optional
import random
import math
from models import *

def calculate_news_score(
    user: User,
    news: News,
    user_weights: dict,
    viewed_ids: set
) -> float:
    """
    Вычисляет скор для одной новости
    
    Args:
        user: Объект пользователя
        news: Объект новости
        user_weights: Словарь весов категорий пользователя
        viewed_ids: Множество ID просмотренных новостей
    
    Returns:
        Скор новости (float)
    """
    if news.id in viewed_ids:
        return -1.0
    
    base_score = user_weights.get(news.category, 0.5)
    
    confidence_bonus = 0.0
    if news.category_confidence:
        confidence_bonus = (news.category_confidence - 0.5) * 0.2
    
    popularity_penalty = 0.0
    if news.total_shown > 0:
        popularity_penalty = math.log(1 + news.total_shown) * 0.05
    
    age_hours = (datetime.utcnow() - news.created_at).total_seconds() / 3600
    freshness_bonus = max(0, (48 - age_hours) / 48) * 0.15
    
    final_score = (
        base_score + 
        confidence_bonus - 
        popularity_penalty + 
        freshness_bonus
    )
    
    return final_score


def precompute_scores_for_user(
    user: User,
    session: Session,
    freshness_hours: int = 72
) -> None:
    """
    Предрассчитывает и сохраняет скоры для всех подходящих новостей для пользователя
    
    Args:
        user: Объект пользователя
        session: Сессия БД
        freshness_hours: Рассматривать новости не старше N часов
    """
    category_weights_query = session.query(UserCategoryWeight).filter(
        UserCategoryWeight.user_id == user.id
    ).all()
    
    user_weights = {cw.category: cw.weight for cw in category_weights_query}
    
    if not user_weights:
        user_weights = {cat: 0.5 for cat in NewsCategory}
    
    viewed_news_ids = session.query(UserInteraction.news_id).filter(
        UserInteraction.user_id == user.id,
        UserInteraction.news_id.isnot(None)
    ).distinct().all()
    viewed_ids = {nid[0] for nid in viewed_news_ids}
    
    cutoff_time = datetime.utcnow() - timedelta(hours=freshness_hours)
    
    query = session.query(News).filter(
        News.created_at >= cutoff_time
    )
    
    if viewed_ids:
        query = query.filter(~News.id.in_(viewed_ids))
    
    news_list = query.all()
    
    session.query(UserNewsScore).filter(
        UserNewsScore.user_id == user.id
    ).delete(synchronize_session=False)
    
    new_scores = []
    for news in news_list:
        score = calculate_news_score(user, news, user_weights, viewed_ids)
        if score > 0:
            new_scores.append({
                'user_id': user.id,
                'news_id': news.id,
                'score': score,
                'calculated_at': datetime.utcnow()
            })
    
    if new_scores:
        session.bulk_insert_mappings(UserNewsScore, new_scores)
        session.commit()


def get_recommended_news(
    user: User,
    n: int,
    session: Session,
    diversity_factor: float = 0.2
) -> List[News]:
    """
    Выдаёт N новостей, наиболее подходящих пользователю из предрассчитанных скоров
    
    Args:
        user: Объект пользователя
        n: Количество новостей для рекомендации
        session: Сессия БД
        diversity_factor: Фактор разнообразия (0-1), добавляет случайности
    
    Returns:
        Список рекомендованных новостей
    """
    recent_score = session.query(UserNewsScore).filter(
        UserNewsScore.user_id == user.id,
        UserNewsScore.calculated_at >= datetime.utcnow() - timedelta(hours=1)
    ).first()
    
    if not recent_score:
        precompute_scores_for_user(user, session)
    
    top_news = session.query(News).join(
        UserNewsScore,
        News.id == UserNewsScore.news_id
    ).filter(
        UserNewsScore.user_id == user.id
    ).order_by(
        UserNewsScore.score.desc()
    ).limit(n * 2).all()
    
    if not top_news:
        viewed_news_ids = session.query(UserInteraction.news_id).filter(
            UserInteraction.user_id == user.id,
            UserInteraction.news_id.isnot(None)
        ).distinct().all()
        viewed_ids = [nid[0] for nid in viewed_news_ids]
        
        query = session.query(News).order_by(News.created_at.desc())
        
        if viewed_ids:
            query = query.filter(~News.id.in_(viewed_ids))
        
        return query.limit(n).all()
    
    if diversity_factor > 0 and len(top_news) > n:
        deterministic_count = int(n * (1 - diversity_factor))
        random_count = n - deterministic_count
        
        selected = top_news[:deterministic_count]
        remaining = top_news[deterministic_count:]
        
        if remaining:
            selected.extend(random.sample(
                remaining, 
                min(random_count, len(remaining))
            ))
        
        return selected[:n]
    
    return top_news[:n]


def process_user_reaction(
    user: User,
    news: News,
    reaction: ReactionType,
    session: Session,
    reaction_time: Optional[int] = None
) -> None:
    """
    Обрабатывает реакцию пользователя на новость и обновляет веса категорий
    
    Args:
        user: Объект пользователя
        news: Объект новости
        reaction: Тип реакции (LIKE, DISLIKE, SKIP)
        session: Сессия БД
        reaction_time: Время реакции в секундах
    """
    LEARNING_RATE = 0.15
    CONFIDENCE_MULTIPLIER = 1.5 
    
    reaction_weights = {
        ReactionType.LIKE: 1.0,
        ReactionType.DISLIKE: -1.0,
        ReactionType.SKIP: -0.3
    }
    
    category_weight = session.query(UserCategoryWeight).filter(
        and_(
            UserCategoryWeight.user_id == user.id,
            UserCategoryWeight.category == news.category
        )
    ).first()
    
    if not category_weight:
        category_weight = UserCategoryWeight(
            user_id=user.id,
            category=news.category,
            weight=0.5
        )
        session.add(category_weight)
        session.flush()
    
    if reaction == ReactionType.LIKE:
        category_weight.positive_reactions += 1
    elif reaction == ReactionType.DISLIKE:
        category_weight.negative_reactions += 1
    else:
        category_weight.neutral_reactions += 1
    
    category_weight.total_shown += 1
    
    base_adjustment = reaction_weights[reaction] * LEARNING_RATE
    
    confidence_factor = 1.0
    if news.category_confidence and news.category_confidence > 0.7:
        confidence_factor = CONFIDENCE_MULTIPLIER
    
    weight_adjustment = base_adjustment * confidence_factor
    
    new_weight = category_weight.weight + weight_adjustment
    category_weight.weight = max(0.0, min(1.0, new_weight))
    
    total_reactions = (
        category_weight.positive_reactions + 
        category_weight.negative_reactions + 
        category_weight.neutral_reactions
    )
    if total_reactions > 0:
        category_weight.confidence = (
            category_weight.positive_reactions / total_reactions
        )
    
    category_weight.last_updated = datetime.utcnow()
    
    interaction = UserInteraction(
        user_id=user.id,
        news_id=news.id,
        news_title=news.title,
        category=news.category,
        category_confidence=news.category_confidence,
        reaction=reaction,
        reaction_time=reaction_time,
        shown_at=datetime.utcnow(),
        reacted_at=datetime.utcnow()
    )
    session.add(interaction)
    
    if not user.stats:
        user.stats = UserStats(user_id=user.id)
        session.add(user.stats)
        session.flush()
    
    user.stats.total_news_shown += 1
    user.stats.total_reactions += 1
    
    if reaction == ReactionType.LIKE:
        user.stats.total_likes += 1
    elif reaction == ReactionType.DISLIKE:
        user.stats.total_dislikes += 1
    elif reaction == ReactionType.SKIP:
        user.stats.total_skips += 1
    
    if user.stats.total_news_shown > 0:
        user.stats.engagement_rate = (
            (user.stats.total_likes + user.stats.total_dislikes) / 
            user.stats.total_news_shown
        )
    
    if reaction_time:
        if user.stats.avg_reaction_time == 0:
            user.stats.avg_reaction_time = reaction_time
        else:
            alpha = 0.2
            user.stats.avg_reaction_time = int(
                alpha * reaction_time + (1 - alpha) * user.stats.avg_reaction_time
            )
    
    user.stats.last_updated = datetime.utcnow()
    user.last_active = datetime.utcnow()
    
    news.total_shown += 1
    news.total_reactions += 1
    
    session.commit()
    
    if user.stats.total_reactions % 5 == 0:
        precompute_scores_for_user(user, session)
