from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
import enum

Base = declarative_base()

class NewsCategory(str, enum.Enum):
    CLIMATE = "climate"
    CONFLICTS = "conflicts"
    CULTURE = "culture"
    ECONOMY = "economy"
    GLOSS = "gloss"
    HEALTH = "health"
    POLITICS = "politics"
    SCIENCE = "science"
    SOCIETY = "society"
    SPORTS = "sports"
    TRAVEL = "travel"

class ReactionType(str, enum.Enum):
    LIKE = "like"
    DISLIKE = "dislike"
    SKIP = "skip"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    max_id = Column(String(50), unique=True, nullable=False)
    username = Column(String(100))
    gender = Column(String(10), nullable=True)
    age = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    
    category_weights = relationship("UserCategoryWeight", back_populates="user", cascade="all, delete-orphan")
    interactions = relationship("UserInteraction", back_populates="user", cascade="all, delete-orphan")
    stats = relationship("UserStats", back_populates="user", uselist=False, cascade="all, delete-orphan")

class UserCategoryWeight(Base):
    __tablename__ = "user_category_weights"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(Enum(NewsCategory), nullable=False)
    
    weight = Column(Float, default=0.5)
    
    positive_reactions = Column(Integer, default=0)
    negative_reactions = Column(Integer, default=0)
    neutral_reactions = Column(Integer, default=0)
    
    total_shown = Column(Integer, default=0)
    confidence = Column(Float, default=0.0)
    
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="category_weights")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'category', name='unique_user_category'),
    )

class News(Base):
    __tablename__ = "news"
    
    id = Column(Integer, primary_key=True)
    title = Column(String(300), nullable=False)
    content = Column(String, nullable=False)
    summary = Column(String)
    
    category = Column(Enum(NewsCategory), nullable=False)
    category_confidence = Column(Float)
    
    source_url = Column(String(500))
    source_name = Column(String(100))
    
    total_shown = Column(Integer, default=0)
    total_reactions = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    interactions = relationship("UserInteraction", back_populates="news", cascade="all, delete-orphan")

class UserInteraction(Base):
    __tablename__ = "user_interactions"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    news_id = Column(Integer, ForeignKey("news.id"), nullable=True)
    news_title = Column(String(300))
    category = Column(Enum(NewsCategory), nullable=False)
    category_confidence = Column(Float)
    
    reaction = Column(Enum(ReactionType), nullable=False)
    reaction_time = Column(Integer)
    
    shown_at = Column(DateTime, default=datetime.utcnow)
    reacted_at = Column(DateTime)
    
    user = relationship("User", back_populates="interactions")
    news = relationship("News", back_populates="interactions")

class UserStats(Base):
    __tablename__ = "user_stats"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    
    total_news_shown = Column(Integer, default=0)
    total_reactions = Column(Integer, default=0)
    engagement_rate = Column(Float, default=0.0)
    
    total_likes = Column(Integer, default=0)
    total_dislikes = Column(Integer, default=0)
    total_skips = Column(Integer, default=0)
    total_bookmarks = Column(Integer, default=0)
    total_shares = Column(Integer, default=0)
    
    avg_reaction_time = Column(Integer, default=0)
    peak_activity_hour = Column(Integer)
    
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="stats")
