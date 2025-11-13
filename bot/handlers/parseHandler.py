from sqlalchemy.orm import Session
from utils.rss_parser import NewsClassifier

class ParseHandler:
    def __init__(self, db_session: Session):
        self.db_session = db_session
        self.classifier = NewsClassifier("/app/models/fasttext_news_classifier.bin")

    async def command(self):
        rss_sources = [
            {"url": "https://www.kommersant.ru/rss/section-sport.xml", 
             "name": "Kommersant Sport", 
             "fixed_category": "SPORTS"},
            {"url": "https://www.kommersant.ru/rss/section-culture.xml", 
             "name": "Kommersant Culture", 
             "fixed_category": "CULTURE"},
            {"url": "https://habr.com/ru/rss/hubs/health/articles/?fl=ru", 
             "name": "Habr Health", 
             "fixed_category": "HEALTH"},
            {"url": "https://habr.com/ru/rss/hubs/Ecology/articles/?fl=ru", 
             "name": "Habr Ecology", 
             "fixed_category": "CLIMATE"},
            {"url": "https://lenta.ru/rss/news/travel", 
             "name": "Lenta Travel", 
             "fixed_category": "TRAVEL"},
            {"url": "https://elementy.ru/rss/news/it", "name": "Elementy IT"},
            {"url": "https://www.cnews.ru/inc/rss/news.xml", "name": "CNews"},
            {"url": "https://news.mail.ru/rss/", "name": "Mail.ru News"},
            {"url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "name": "RBC"},
        ]

        for source in rss_sources:
            results = parse_rss_and_populate_db(
                rss_url=source["url"],
                source_name=source["name"],
                session=self.db_session,
                News=News,
                NewsCategory=NewsCategory,
                classifier=self.classifier,
                hours_filter=1,
                fixed_category=source.get("fixed_category"),
                skip_classification=False
            )
