import asyncio
from django.utils import timezone
from core.models import NewsPage, NewsSource
from spider_rs import Website
from django.db import close_old_connections, IntegrityError
from asgiref.sync import sync_to_async
from django.utils.text import slugify


async def crawl_news_sources():
    news_sources = await sync_to_async(list)(NewsSource.objects.all())
    
    tasks = [fetch_website(source.url) for source in news_sources]
    
    await asyncio.gather(*tasks, return_exceptions=True)
    
    await sync_to_async(NewsSource.objects.filter(
        url__in=[source.url for source in news_sources]
    ).update)(last_crawled=timezone.now())
    
    close_old_connections()


def crawl_news_sources_sync():
    print("Crawling news sources...")
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(crawl_news_sources())
    finally:
        loop.close()
        close_old_connections()


async def fetch_website(url: str) -> None:
    try:
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
                await sync_to_async(NewsPage.objects.get_or_create)(
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
    except Exception as e:
        print(f"Error processing {url}: {str(e)}")
        # Let the error propagate up to be handled by gather()
        raise



