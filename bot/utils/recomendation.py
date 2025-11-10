from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from datetime import datetime
import math
from models import User, NewsCategory, UserCategoryWeight, ReactionType, UserInteraction, UserStats, News
def create_user(
    session: Session,
    max_id: str,
    username: str,
    selected_categories: List[NewsCategory]
) -> User:
    user = User(max_id=max_id, username=username)
    session.add(user)
    session.commit()

    for category in NewsCategory:
        weight = 0.8 if category in selected_categories else 0.3
        ucw = UserCategoryWeight(user_id=user.id, category=category, weight=weight)
        session.add(ucw)

    session.commit()
    return user

def get_user_category_weights(user: User) -> Dict[NewsCategory, float]:
    return {ucw.category: ucw.weight for ucw in user.category_weights}

def update_category_weight(
    cat_weight: UserCategoryWeight,
    reaction: ReactionType,
    tau: int = 21600,
    eta: float = 0.6
) -> None:
    r_map = {'like': 1.0, 'skip': 0.5, 'dislike': 0.0}
    r = r_map.get(reaction.value, 0.5)
    dt = (datetime.utcnow() - cat_weight.last_updated).total_seconds()
    decay = math.exp(-dt / tau)
    cat_weight.weight = cat_weight.weight * decay + eta * (r - 0.5)
    cat_weight.last_updated = datetime.utcnow()

    if r == 1.0:
        cat_weight.positive_reactions += 1
    elif r == 0.0:
        cat_weight.negative_reactions += 1
    else:
        cat_weight.neutral_reactions += 1

    cat_weight.total_shown += 1

def log_user_interaction(
    session: Session,
    user: User,
    news: News,
    reaction: ReactionType,
    reaction_time_ms: Optional[int] = None
) -> None:
    cat_weight = next((cw for cw in user.category_weights if cw.category == news.category), None)
    if not cat_weight:
        cat_weight = UserCategoryWeight(user_id=user.id, category=news.category, weight=0.5)
        session.add(cat_weight)
        session.flush()

    update_category_weight(cat_weight, reaction)

    interaction = UserInteraction(
        user_id=user.id,
        news_id=news.id,
        news_title=news.title,
        category=news.category,
        category_confidence=news.category_confidence,
        reaction=reaction,
        reaction_time=reaction_time_ms,
        reacted_at=datetime.utcnow(),
        shown_at=datetime.utcnow()
    )
    session.add(interaction)

    news.total_reactions += 1

    session.commit()

def update_user_stats(session: Session, user: User) -> None:
    stats = user.stats
    if not stats:
        stats = UserStats(user_id=user.id)
        session.add(stats)

    interactions = user.interactions
    total_reactions = len(interactions)
    likes = sum(1 for i in interactions if i.reaction == ReactionType.LIKE)
    dislikes = sum(1 for i in interactions if i.reaction == ReactionType.DISLIKE)
    skips = sum(1 for i in interactions if i.reaction == ReactionType.SKIP)

    stats.total_news_shown = sum(cw.total_shown for cw in user.category_weights)
    stats.total_reactions = total_reactions
    stats.engagement_rate = likes / total_reactions if total_reactions > 0 else 0.0
    stats.total_likes = likes
    stats.total_dislikes = dislikes
    stats.total_skips = skips
    stats.last_updated = datetime.utcnow()
    session.commit()
