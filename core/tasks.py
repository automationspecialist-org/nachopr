import asyncio
from django.utils import timezone
from core.models import NewsPage, NewsSource
from spider_rs import Website
from django.db import close_old_connections, IntegrityError
from asgiref.sync import sync_to_async
from django.utils.text import slugify


async def crawl_news_sources():
    news_sources = await sync_to_async(list)(NewsSource.objects.all())
    for news_source in news_sources:
        print(f"Crawling {news_source.url}")
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
        # Generate a slug from the title
        slug = slugify(page.title)
        
        try:
            # Use get_or_create to avoid duplicates
            _, created = await sync_to_async(NewsPage.objects.get_or_create)(
                url=page.url,
                slug=slug,
                defaults={
                    'title': page.title,
                    'content': page.content,
                    'source': news_source,
                    'slug': slug
                }
            )
        except IntegrityError as e:
            print(f"Skipping duplicate page: {page.url} - {str(e)}")
            continue
        
        close_old_connections()



