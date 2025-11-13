from maxapi import Bot, Dispatcher
from sqlalchemy.orm import Session
from utils.rss_parser import NewsClassifier, parse_rss_and_populate_db
from models import News, NewsCategory
from maxapi.types import MessageCreated, Command

class ParseHandler:
    def __init__(self, db_session : Session):
        self.db_session = db_session
        self.classifier = NewsClassifier("/app/models/fasttext_news_classifier.bin")

    async def command(self):
        rss_sources = [
            {"url": "https://elementy.ru/rss/news/it", "name": "Elementy IT"},
            {"url": "https://www.cnews.ru/inc/rss/news.xml", "name": "CNews"},
            {"url": "https://news.mail.ru/rss/", "name": "Mail.ru News"},
            {"url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "name": "RBC"},
            {"url": "https://www.kommersant.ru/rss/section-sport.xml", "name": "Kommersant Sport"},
            {"url": "https://www.kommersant.ru/rss/section-culture.xml", "name": "Kommersant Culture"},
            {"url": "https://habr.com/ru/rss/hubs/health/articles/?fl=ru", "name": "Habr Health"},
            {"url": "https://habr.com/ru/rss/hubs/Ecology/articles/?fl=ru", "name": "Habr Ecology"},
            {"url": "https://lenta.ru/rss/news/travel", "name": "Lenta Travel"}
        ]

        for source in rss_sources:
            results = parse_rss_and_populate_db(
                rss_url=source["url"],
                source_name=source["name"],
                session=self.db_session,
                News=News,
                NewsCategory=NewsCategory,
                classifier=self.classifier,
                hours_filter=1
            )
