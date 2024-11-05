import asyncio
from django.utils import timezone
from core.models import NewsPage, NewsSource, Journalist
from spider_rs import Website
from django.db import close_old_connections, IntegrityError, transaction
from asgiref.sync import sync_to_async
from django.utils.text import slugify
from bs4 import BeautifulSoup
import re


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


def extract_journalists(html: str):
    """
    Extract journalist information from article HTML.
    Returns dict with journalist name and metadata.
    """
    # Create BeautifulSoup object to parse HTML
    soup = BeautifulSoup(html, 'html.parser')
    
    # Look for journalist info in byline/contributor tags
    journalists = {}
    
    # Try to find byline elements
    bylines = soup.find_all(attrs={"data-component": "meta-byline"})
    
    for byline in bylines:
        # Extract name from byline
        name = byline.get_text().strip()
        
        # Look for associated metadata
        meta = {}
        
        # Try to find profile URL
        profile_link = byline.find('a')
        if profile_link:
            meta['profile_url'] = profile_link['href']
            
        # Try to find image URL    
        img = byline.find('img')
        if img:
            meta['image_url'] = img['src']
            
        # Add to journalists dict
        journalists[name] = meta
        
    return journalists


async def process_journalists():
    """
    Process all NewsPages to extract and update journalist information
    """
    # Get all NewsPages that need processing
    news_pages = await sync_to_async(list)(NewsPage.objects.all())
    
    for page in news_pages:
        # Extract journalists from page content
        journalists_data = extract_journalists(page.content)
        
        # Process each journalist
        for name, metadata in journalists_data.items():
            await update_journalist(name, metadata, page)


@sync_to_async
@transaction.atomic
def update_journalist(name: str, metadata: dict, page: NewsPage):
    """
    Create or update journalist record and link to page
    """
    # Get or create journalist
    journalist, created = Journalist.objects.get_or_create(
        name=name,
        defaults={
            'profile_url': metadata.get('profile_url'),
            'image_url': metadata.get('image_url')
        }
    )
    
    # Update metadata if journalist exists
    if not created:
        update_fields = []
        if metadata.get('profile_url') and not journalist.profile_url:
            journalist.profile_url = metadata['profile_url']
            update_fields.append('profile_url')
        if metadata.get('image_url') and not journalist.image_url:
            journalist.image_url = metadata['image_url']
            update_fields.append('image_url')
        if update_fields:
            journalist.save(update_fields=update_fields)
    
    # Link journalist to page and source
    page.journalists.add(journalist)
    journalist.sources.add(page.source)


# Sync runner
def run_journalist_processing():
    """
    Sync wrapper to run the async journalist processing
    """
    import asyncio
    
    async def run():
        await process_journalists()
    
    asyncio.run(run())


