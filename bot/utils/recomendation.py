from sqlalchemy.orm import Session
from sqlalchemy import and_, func, desc
from datetime import datetime
from typing import List, Optional
import random
from models import *

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


def get_recommended_news(
    user: User,
    n: int,
    session: Session,
    diversity_factor: float = 0.2,
    freshness_hours: int = 72
) -> List[News]:
    """
    Выдаёт N новостей, наиболее подходящих пользователю
    
    Args:
        user: Объект пользователя
        n: Количество новостей для рекомендации
        session: Сессия БД
        diversity_factor: Фактор разнообразия (0-1), добавляет случайности
        freshness_hours: Рассматривать новости не старше N часов
    
    Returns:
        Список рекомендованных новостей
    """
    from datetime import timedelta
    
    category_weights_query = session.query(UserCategoryWeight).filter(
        UserCategoryWeight.user_id == user.id
    ).all()
    
    user_weights = {
        cw.category: cw.weight 
        for cw in category_weights_query
    }
    
    if not user_weights:
        user_weights = {cat: 0.5 for cat in NewsCategory}
    
    viewed_news_ids = session.query(UserInteraction.news_id).filter(
        UserInteraction.user_id == user.id,
        UserInteraction.news_id.isnot(None)
    ).distinct().all()
    viewed_ids = [nid[0] for nid in viewed_news_ids]
    
    cutoff_time = datetime.utcnow() - timedelta(hours=freshness_hours)
    
    query = session.query(News).filter(
        News.created_at >= cutoff_time
    )
    
    if viewed_ids:
        query = query.filter(~News.id.in_(viewed_ids))
    
    available_news = query.all()
    
    if not available_news:
        query = session.query(News)
        if viewed_ids:
            query = query.filter(~News.id.in_(viewed_ids))
        available_news = query.limit(n * 2).all()
    
    if not available_news:
        return []
    
    scored_news = []
    
    for news_item in available_news:
        # Базовый score на основе веса категории
        base_score = user_weights.get(news_item.category, 0.5)
        
        confidence_bonus = 0.0
        if news_item.category_confidence:
            confidence_bonus = (news_item.category_confidence - 0.5) * 0.2
        
        popularity_penalty = 0.0
        if news_item.total_shown > 0:
            import math
            popularity_penalty = math.log(1 + news_item.total_shown) * 0.05
        
        age_hours = (datetime.utcnow() - news_item.created_at).total_seconds() / 3600
        freshness_bonus = max(0, (48 - age_hours) / 48) * 0.15
        
        final_score = (
            base_score + 
            confidence_bonus - 
            popularity_penalty + 
            freshness_bonus
        )
        
        scored_news.append((news_item, final_score))
    
    scored_news.sort(key=lambda x: x[1], reverse=True)
    
    top_candidates = scored_news[:n * 2]
    
    if diversity_factor > 0 and len(top_candidates) > n:
        deterministic_count = int(n * (1 - diversity_factor))
        random_count = n - deterministic_count
        
        selected = [item[0] for item in top_candidates[:deterministic_count]]
        
        remaining = [item[0] for item in top_candidates[deterministic_count:]]
        if remaining:
            selected.extend(random.sample(
                remaining, 
                min(random_count, len(remaining))
            ))
        
        return selected[:n]
    else:
        return [item[0] for item in scored_news[:n]]
