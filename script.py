import json
from sqlalchemy.orm import Session
from bot.models import News
from bot.db import get_session

def dump_news_to_json(filename="news_dump.json"):
    session = get_session()
    news_data = []
    for news in session.query(News).all():
        news_data.append({
            "title": news.title,
            "content": news.content,
            "summary": news.summary,
            "category": news.category.value,
            "category_confidence": news.category_confidence,
            "source_url": news.source_url,
            "source_name": news.source_name,
            "created_at": news.created_at.isoformat()
        })
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(news_data, f, ensure_ascii=False, indent=2)
    print(f"Dumped {len(news_data)} news articles to {filename}")

if __name__ == "__main__":
    dump_news_to_json()
