import asyncio
from django.utils import timezone
from core.models import NewsPage, NewsSource
from spider_rs import Website
from django.db import close_old_connections, IntegrityError
from asgiref.sync import sync_to_async


async def crawl_news_sources():
    news_sources = await sync_to_async(list)(NewsSource.objects.all())
    for news_source in news_sources:
        await fetch_website(news_source.url)
        news_source.last_crawled = timezone.now()
        await sync_to_async(news_source.save)()
        close_old_connections()


def crawl_news_sources_sync():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(crawl_news_sources())


async def fetch_website(url: str) -> Website:
    website = Website(url)
    website.scrape()
    pages = website.get_pages()
    
    # Get the news source asynchronously
    news_source = await sync_to_async(NewsSource.objects.get)(url=url)
    
    for page in pages:
        try:
            news_page = NewsPage(
                url=page.url,
                title=page.title,
                content=page.content,
                source=news_source
            )
            await sync_to_async(news_page.save)()
        except IntegrityError:
            # Skip duplicate URLs
            continue
        finally:
            close_old_connections()



