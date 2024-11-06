import asyncio
from django.utils import timezone
from core.models import NewsPage, NewsSource, Journalist
from spider_rs import Website 
from django.db import close_old_connections, IntegrityError, transaction
from asgiref.sync import sync_to_async
from django.utils.text import slugify
from bs4 import BeautifulSoup


async def crawl_news_sources(limit : int = None):
    # Add debug print
    print("Running on", timezone.now())
    
    news_sources = await sync_to_async(list)(
        # Modify or temporarily remove the time filter
        NewsSource.objects.all()  # Remove filter temporarily for testing
        # Original: NewsSource.objects.filter(
        #     last_crawled__lt=timezone.now() - timezone.timedelta(days=1)
        # )
    )
    
    # Add debug print
    print(f"Found {len(news_sources)} news sources to crawl")
    
    for news_source in news_sources:
        print(f"Crawling {news_source.url}")
        start_time = timezone.now()
        
        await fetch_website(news_source.url)
        
        end_time = timezone.now()
        duration = end_time - start_time
        print(f"Finished crawling {news_source.url} in {duration}")
        
        news_source.last_crawled = end_time
        await sync_to_async(news_source.save)()
        close_old_connections()


def crawl_news_sources_sync(limit : int = None):
    loop = asyncio.get_event_loop()
    loop.run_until_complete(crawl_news_sources(limit))


async def fetch_website(url: str, limit: int = None, depth: int = 3) -> Website:
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    website = (
        Website(url)
        .with_budget({"*": limit})
        .with_user_agent(user_agent)
        .with_request_timeout(30000)
        .with_respect_robots_txt(False)
        .with_depth(depth)
    )
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
            # Extract journalists from the page content
            journalists_data = extract_journalists(page.content)
            
            for name, meta in journalists_data.items():
                # Generate a slug from the journalist's name
                journalist_slug = slugify(name)
                
                # Use get_or_create to avoid duplicates
                journalist, created = await sync_to_async(Journalist.objects.get_or_create)(
                    name=name,
                    slug=journalist_slug,
                    defaults={
                        'profile_url': meta.get('profile_url'),
                        'image_url': meta.get('image_url')
                    }
                )
                
                # Associate the journalist with the news page
                await sync_to_async(page.journalists.add)(journalist)
            
                # Mark the page as processed
                page.processed = True
                await sync_to_async(page.save)()
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
    news_pages = await sync_to_async(list)(NewsPage.objects.filter(processed=False))
    
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
    journalist = None
    created = False
    
    # Generate base slug
    base_slug = slugify(name)

    # First try to find journalist by profile_url if it exists
    profile_url = metadata.get('profile_url')
    if profile_url:
        try:
            journalist = Journalist.objects.get(profile_url=profile_url)
            # Update name if different
            if journalist.name != name:
                journalist.name = name
                journalist.save(update_fields=['name'])
        except Journalist.DoesNotExist:
            pass

    # If we didn't find by profile_url, try to get or create by name with unique slug
    if journalist is None:
        counter = 0
        while True:
            slug = base_slug if counter == 0 else f"{base_slug}-{counter}"
            try:
                journalist, created = Journalist.objects.get_or_create(
                    slug=slug,
                    defaults={
                        'name': name,
                        'profile_url': profile_url,
                        'image_url': metadata.get('image_url')
                    }
                )
                break
            except IntegrityError:
                counter += 1

    # Update metadata if needed
    if not created:
        update_fields = []
        if profile_url and not journalist.profile_url:
            journalist.profile_url = profile_url
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


