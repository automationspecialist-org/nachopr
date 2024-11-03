import asyncio
from django.utils import timezone
from core.models import NewsSource
from spider_rs import Website


async def crawl_news_sources():
    news_sources = NewsSource.objects.all()
    for news_source in news_sources:
        await fetch_website(news_source.url)
        news_source.last_crawled = timezone.now()
        news_source.save()


async def fetch_website(url: str) -> Website:
    website = Website(url)
    website.scrape()
    pages = website.get_pages()
    for page in pages[:1]:
        print(help(page))
        print(page.url)
        print(page.title)
        print(page.content)



