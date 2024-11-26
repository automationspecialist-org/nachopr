import asyncio
import json
import os
from django.utils import timezone
import openai
from tqdm import tqdm
from core.models import DigitalPRExample, NewsPage, NewsPageCategory, NewsSource, Journalist
from spider_rs import Website 
from django.db import close_old_connections, IntegrityError
from asgiref.sync import sync_to_async
from django.utils.text import slugify
from openai import AzureOpenAI
from dotenv import load_dotenv
import logging
from PIL import Image, ImageDraw, ImageFont
from django.conf import settings
from django.db.models import Q
import lunary
import uuid
from markdownify import markdownify
from django.db import transaction
from mailscout import Scout
from functools import lru_cache
from datetime import datetime
import requests
from typing import List, Optional
import tiktoken  # Add this import for token counting
from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver
import requests_cache
from urllib.parse import urlparse, urlunparse
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from openai import APIError, APIConnectionError, RateLimitError
from celery import shared_task, chain
from celery.signals import task_success


load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

lunary.config(app_id=os.getenv('LUNARY_PUBLIC_KEY'))



# Cache failed domains to avoid rechecking
failed_domains = set()

@lru_cache(maxsize=1000)
def is_failed_domain(domain: str) -> bool:
    """Check if domain is in failed set"""
    return domain in failed_domains

async def crawl_news_sources(domain_limit: int = None, page_limit: int = None, max_concurrent_tasks: int = 2):
    try:
        logger.info(f"Starting crawl at {timezone.now()}")
        
        # Use sync_to_async with thread_sensitive=False to avoid holding connections
        news_sources = await sync_to_async(list, thread_sensitive=False)(
            NewsSource.objects.filter(
                Q(last_crawled__lt=timezone.now() - timezone.timedelta(days=7)) |
                Q(last_crawled__isnull=True)
            ).order_by(
                '-priority',
                'last_crawled'
            )[:domain_limit]
        )
        
        logger.info(f"Found {len(news_sources)} news sources to crawl")
        
        # Limit concurrent tasks to avoid too many DB connections
        semaphore = asyncio.Semaphore(min(max_concurrent_tasks, 5))
        
        tasks = []
        for news_source in news_sources:
            tasks.append(crawl_single_news_source(news_source, limit=page_limit, semaphore=semaphore))
        
        await asyncio.gather(*tasks)
                
    except Exception as e:
        logger.error(f"Critical error in crawl_news_sources: {str(e)}")
        raise
    finally:
        # Ensure connections are closed
        close_old_connections()

async def crawl_single_news_source(news_source, limit, semaphore):
    async with semaphore:
        try:
            logger.info(f"Starting crawl for {news_source.url}")
            
            await fetch_website(news_source.url, limit=limit)
            
            # Move database operation inside sync_to_async wrapper with thread_sensitive=False
            @sync_to_async(thread_sensitive=False)
            def update_news_source():
                with transaction.atomic():
                    news_source.refresh_from_db()
                    news_source.last_crawled = timezone.now()
                    news_source.save()
                
            await update_news_source()
            
        except Exception as e:
            logger.error(f"Error crawling {news_source.url}: {str(e)}")
        finally:
            close_old_connections()


def crawl_news_sources_sync(domain_limit: int = None, page_limit: int = None, max_concurrent_tasks: int = 2):
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    message = f"[{timezone.now()}] NachoPR crawl starting..."
    logger.info(message)
    requests.post(slack_webhook_url, json={"text": message})
    loop = asyncio.get_event_loop()
    loop.run_until_complete(crawl_news_sources( 
        domain_limit=domain_limit, 
        page_limit=page_limit, 
        max_concurrent_tasks=max_concurrent_tasks
    ))


async def fetch_website(url: str, limit: int = 1000_000, depth: int = 3) -> Website:
    try:
        user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        if limit:
            website = (
                Website(url)
                .with_budget({"*": limit})
                .with_user_agent(user_agent)
                .with_request_timeout(30000)
                .with_respect_robots_txt(False)
                .with_depth(depth)
            )
        else:
            website = (
                Website(url)
                .with_user_agent(user_agent)
                .with_request_timeout(30000)
                .with_respect_robots_txt(False)
                .with_depth(depth)
            )

        website.scrape()
        pages = website.get_pages()
        logger.info(f"Fetched {len(pages)} pages from {url}")
        
        @sync_to_async
        def get_news_source():
            return NewsSource.objects.get(url=url)
            
        news_source = await get_news_source()
        
        for page in pages:
            await asyncio.sleep(0.1)
            try:
                @sync_to_async
                def create_news_page():
                    with transaction.atomic():
                        # Skip if page already exists
                        if NewsPage.objects.filter(url=page.url).exists():
                            return None, False

                        cleaned_content = clean_html(page.content)

                        # Create new page only if it doesn't exist
                        news_page = NewsPage.objects.create(
                            url=page.url,
                            title=str(page.title()),  # Convert title to string
                            content=cleaned_content,
                            source=news_source
                        )
                        return news_page, True

                await create_news_page()
                
            except Exception as e:
                logger.error(f"Error processing page {page.url}: {str(e)}", exc_info=True)
                continue
            finally:
                close_old_connections()

    except Exception as e:
        logger.error(f"Error in fetch_website for {url}: {str(e)}", exc_info=True)
        raise
    finally:
        close_old_connections()


def clean_html(html: str) -> str:
    # Convert HTML to markdown
    cleaned_html = markdownify(html)
    
    # Remove excessive newlines (more than 2 in a row)
    cleaned_html = '\n'.join([line for line in cleaned_html.splitlines() if line.strip()])
    cleaned_html = cleaned_html.replace('\n\n\n', '\n\n')
    
    return cleaned_html


def extract_journalists_with_gpt(content: str, track_prompt: bool = False) -> dict:
    """
    Extract journalist information from the HTML content using GPT-4 on Azure.
    """
    run_id = str(uuid.uuid4())

    clean_content = clean_html(content)
    
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_deployment="gpt-4o-mini",
        api_version="2024-08-01-preview",
        api_key=os.getenv("AZURE_OPENAI_API_KEY")
    )
    lunary.monitor(client)


    journalist_json = { 
        "content_is_full_news_article": True,
        "article_published_date": "2024-01-01",
        "journalists": [
            {
                "name": "John Doe",
                "description": "An experienced journalist covering international news.",
                "profile_url": "https://example.com/john-doe",
                "image_url": "https://example.com/john-doe.jpg"
            },
            {
                "name": "Jane Smith",
                "description": "A journalist specializing in technology and science.",
                "profile_url": "https://example.com/jane-smith",
                "image_url": "https://example.com/jane-smith.jpg"
            }
        ]
    }
    # Define the prompt for GPT-4
    prompt = f"""
    Extract journalist information from the following HTML content and return it as a JSON object with the journalist's name as the key and their metadata (profile_url and image_url) as the value:
    Only extract journalists that are individual humans, not editorial teams such as 'Weather Team', '11alive.com', or '1News Reporters'.
    HTML content:
    ```
    {clean_content}
    ```

    Use the following JSON schema:
    ```
    {journalist_json}
    ```
    If you cannot find any valid journalists, return an empty JSON object. Never output the example JSON objects such as 'John Doe' and 'Jane Smith'.
    If you cannot extract the publushed article date, return an empty string for 'article_published_date'. 
    The value of content_is_full_news_article should be true if the page is a full news article, and false otherwise.
    If the page is a category page or list of multiple stories, set content_is_full_news_article to false.
    """

    

    try:
        # Call the GPT-4 API on Azure
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a html to json extractor."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            n=1,
            stop=None,
            temperature=0.3,
            response_format={"type": "json_object"}
        )

        result = response.choices[0].message.content
        journalists_data = json.loads(result)


    except (Exception, json.JSONDecodeError) as e:
        # Track error with the raw response if available
        error_data = {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "raw_response": result if 'result' in locals() else None
        }
        
        logger.error(f"Error in extract_journalists_with_gpt: {str(e)}")
        print('error:', result if 'result' in locals() else str(e))
        journalists_data = {}

    return journalists_data


async def process_all_pages_journalists(limit: int = 10, re_process: bool = False):
    """Process journalists for multiple pages using GPT"""
    # Create queues for processing
    gpt_queue = asyncio.Queue()  # Queue of pages to process with GPT
    db_queue = asyncio.Queue()   # Queue of results to write to DB
    
    # Get pages to process
    if re_process:
        pages = await sync_to_async(list)(NewsPage.objects.exclude(content='').all()[:limit])
    else:
        pages = await sync_to_async(list)(NewsPage.objects.exclude(content='').filter(processed=False)[:limit])
    
    # Add all pages to the GPT queue
    for page in pages:
        await gpt_queue.put(page)

    async def gpt_worker():
        """Async worker to process GPT requests"""
        while True:
            try:
                # Get next page from queue
                page = await gpt_queue.get()
                
                # Process with GPT
                journalists_data = extract_journalists_with_gpt(page.content)
                
                # Put results in DB queue
                await db_queue.put((page, journalists_data))
                
                # Mark task as done
                gpt_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in GPT worker: {str(e)}")
                gpt_queue.task_done()

    async def db_worker():
        """Sequential worker to handle DB writes"""
        while True:
            try:
                # Get next result from queue
                page, journalists_data = await db_queue.get()
                
                # Write to DB synchronously
                @sync_to_async
                def save_to_db():
                    with transaction.atomic():
                        # Save the is_news_article value
                        page.is_news_article = journalists_data.get('content_is_full_news_article', False)
                        
                        # Try to save the published date if it exists and is valid
                        published_date_str = journalists_data.get('article_published_date')
                        if published_date_str:
                            try:
                                # Convert string to date object
                                published_date = datetime.strptime(published_date_str, '%Y-%m-%d').date()
                                page.published_date = published_date
                            except (ValueError, TypeError):
                                # If date is invalid, just ignore it and continue processing
                                logger.warning(f"Invalid date format for page {page.id}: {published_date_str}")
                        
                        if journalists_data and 'journalists' in journalists_data:
                            for journalist_dict in journalists_data['journalists']:
                                if 'name' in journalist_dict:
                                    name = journalist_dict['name']
                                    profile_url = clean_url(journalist_dict.get('profile_url', ''))
                                    image_url = clean_url(journalist_dict.get('image_url', ''))
                                    journalist_slug = slugify(name)
                                    
                                    try:
                                        journalist, created = Journalist.objects.get_or_create(
                                            name=name,
                                            slug=journalist_slug,
                                            defaults={
                                                'profile_url': profile_url,
                                                'image_url': image_url
                                            }
                                        )
                                        page.journalists.add(journalist)
                                    except IntegrityError:
                                        # Log duplicate journalist as info instead of error
                                        logger.info(f"Duplicate journalist found: {name}")
                                        # Try to get existing journalist and add to page
                                        try:
                                            journalist = Journalist.objects.get(slug=journalist_slug)
                                            page.journalists.add(journalist)
                                        except Journalist.DoesNotExist:
                                            logger.warning(f"Could not find existing journalist with slug: {journalist_slug}")
                        
                        page.processed = True
                        page.save()
                
                await save_to_db()
                
                # Mark task as done
                db_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in DB worker: {str(e)}")
                db_queue.task_done()
            finally:
                close_old_connections()

    # Create multiple GPT workers but only one DB worker
    gpt_workers = [asyncio.create_task(gpt_worker()) for _ in range(20)]
    db_worker_task = asyncio.create_task(db_worker())
    
    # Wait for all pages to be processed
    await gpt_queue.join()
    await db_queue.join()
    
    # Cancel workers
    for worker in gpt_workers:
        worker.cancel()
    db_worker_task.cancel()
    
    # Wait for workers to finish
    await asyncio.gather(*gpt_workers, db_worker_task, return_exceptions=True)

def process_all_journalists_sync(limit: int = 10, re_process: bool = False):
    """Sync wrapper for processing multiple pages"""
    loop = asyncio.get_event_loop()
    loop.run_until_complete(process_all_pages_journalists(limit, re_process))



def categorize_news_page_with_gpt(page: NewsPage):
    """Add this transaction wrapper and explicit category sync"""
    available_categories = NewsPageCategory.objects.all()
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_deployment="gpt-4o-mini",
        api_version="2024-08-01-preview",
        api_key=os.getenv("AZURE_OPENAI_API_KEY")
    )
    available_categories_str = ', '.join([f"{category.name}" for category in available_categories])
    json_schema = {
        "categories": [
            "category_name"
        ]
    }
    prompt = f"""
    Categorize the following news page into one or more of the following categories, 
    and return a json object with one or more category names. 
    If no category is relevant, return one or more new categories to be created.
    Available categories: {available_categories_str}

    News page title: {page.title}
    News page content: {page.content[:1000]}

    Use the following JSON schema:
    ```
    {json_schema}
    ```
    The categories should be specific types of news, not 'news'. 
    For example 'software', 'hardware', 'space' are categories, but 'news' is not.
    The categories should always be in English, regardless of the original language of the news page.
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a news page categorizer."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=2000,
        n=1,
        stop=None,
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    result = response.choices[0].message.content
    try:
        categories_data = json.loads(result)
        logger.info(f"Categories from GPT: {categories_data}")
        
        with transaction.atomic():
            # First, add categories to the page
            for category_name in categories_data['categories']:
                category, created = NewsPageCategory.objects.get_or_create(
                    name=category_name,
                    defaults={'slug': slugify(category_name)}
                )
                logger.info(f"Adding category {category.name} to page {page.title}")
                page.categories.add(category)
            
            # The signals should handle the rest, but let's force sync just in case
            page.source.sync_categories()
            for journalist in page.journalists.all():
                journalist.sync_categories()
                
    except json.JSONDecodeError:
        logger.error(f'JSON decode error for result: {result}')
    except Exception as e:
        logger.error(f'Error in categorize_news_page_with_gpt: {str(e)}')


@shared_task(
    bind=True,
    time_limit=900,  # 15 minute timeout
    soft_time_limit=800,  # ~13 minute soft timeout
    max_retries=3,
    default_retry_delay=300  # 5 minutes between retries
)
def categorize_page_task(self, page_id):
    """Categorize a single news page"""
    try:
        page = NewsPage.objects.get(id=page_id)
        categorize_news_page_with_gpt(page)
    except Exception as e:
        logger.error(f"Error categorizing page {page_id}: {str(e)}")
        raise self.retry(exc=e)

@shared_task(
    time_limit=3600,  # 1 hour timeout
    soft_time_limit=3300,  # 55 minute soft timeout
    rate_limit='2/m'  # Max 2 tasks per minute
)
def categorize_pages_task(limit=1000):
    """Distribute categorization tasks"""
    pages = NewsPage.objects.filter(
        categories__isnull=True, 
        journalists__isnull=False,
        is_news_article=True
    ).distinct()[:limit]
    
    for page in pages:
        categorize_page_task.delay(page.id)


def create_social_sharing_image():
    logger.info("Starting social sharing image creation")
    try:
        media_outlets_count = NewsSource.objects.count()
        journalists_count = Journalist.objects.count()
        logger.info(f"Found {media_outlets_count:,} media outlets and {journalists_count:,} journalists")
        
        # Create gradient background
        width = 1200
        height = 630
        image = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(image)
        logger.debug(f"Created new image with dimensions {width}x{height}")

        # Draw gradient from dark green to light green
        for y in range(height):
            r = int(22 + (y/height) * 20)  # Slight red variation
            g = int(163 + (y/height) * 20)  # Green variation from ~163 to ~183
            b = int(74 + (y/height) * 20)   # Slight blue variation
            for x in range(width):
                draw.point((x, y), fill=(r, g, b))

        # Load and paste logo
        logo_path = os.path.join(settings.STATIC_ROOT, 'img', 'logo.png')
        logger.debug(f"Loading logo from: {logo_path}")
        try:
            logo = Image.open(logo_path)
            logger.info(f"Successfully loaded logo with dimensions {logo.size}")
        except Exception as e:
            logger.error(f"Failed to load logo from {logo_path}: {str(e)}")
            raise

        # Resize logo to reasonable size (e.g. 200px height)
        logo_height = 200
        aspect_ratio = logo.size[0] / logo.size[1]
        logo_width = int(logo_height * aspect_ratio)
        logo = logo.resize((logo_width, logo_height))
        
        # Add text on right side
        try:
            font_path = os.path.join(settings.STATIC_ROOT, 'fonts', 'SpaceMono-Bold.ttf')
            logger.debug(f"Loading font from: {font_path}")
            font = ImageFont.truetype(font_path, 60)
            # Create larger font for NachoPR
            nacho_font = ImageFont.truetype(font_path, 120)
            logger.info("Successfully loaded custom fonts")
        except Exception as e:
            logger.warning(f"Failed to load custom font, falling back to default: {str(e)}")
            font = ImageFont.load_default()
            nacho_font = font

        # Calculate vertical position for logo and text to be aligned
        content_y = 200  # Common starting position for logo and text
        
        # Add NachoPR text centered at top
        nacho_text = "NachoPR"
        nacho_bbox = draw.textbbox((0, 0), nacho_text, font=nacho_font)
        nacho_width = nacho_bbox[2] - nacho_bbox[0]
        nacho_x = (width - nacho_width) // 2
        nacho_y = 40  # Padding from top
        draw.text((nacho_x, nacho_y), nacho_text, font=nacho_font, fill=(255, 255, 255))

        # Paste logo on left side with padding
        logo_x = 100
        logo_y = content_y - 20
        image.paste(logo, (logo_x, logo_y), logo if logo.mode == 'RGBA' else None)

        # Add main text aligned with logo
        text = f"Connect with\n{journalists_count:,} Journalists\nfrom {media_outlets_count:,}\nMedia Outlets"
        text_x = logo_x + logo_width + 100
        text_y = content_y
        
        # Draw text with white color
        draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255))

        # Save the image
        output_path = os.path.join(settings.STATIC_ROOT, 'img', 'social_share.png')
        logger.debug(f"Saving image to: {output_path}")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        image.save(output_path, 'PNG')
        logger.info("Successfully created and saved social sharing image")

    except Exception as e:
        logger.error(f"Failed to create social sharing image: {str(e)}", exc_info=True)
        raise



def search_google_for_digital_pr_examples(domain_limit: int = 2, query: str = ''):
    """Search Google for digital PR examples"""

    url = "https://google.serper.dev/search"

    domain = "timeout.com"
    query = "expert reveals"
    negative_queries = ["university", "professor"]

    payload = json.dumps({
    "q": f"site:{domain} \"{query}\" -{'-'.join(negative_queries)}",
    "tbs": "qdr:y"
    })
    headers = {
    'X-API-KEY': os.getenv("SERPER_API_KEY"),
    'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload) 

    print(response.text)

    pass


def find_digital_pr_examples(search_google: bool = False):
    """
    Find news pages that match digital PR patterns and create DigitalPRExample entries.
    """
    pr_queries = [
        "expert reveals",
    ]
    negative_queries = [
        'university',
        'professor',
    ]

    # Build Q objects for positive and negative queries
    positive_q = Q()
    for query in pr_queries:
        positive_q |= (
            Q(content__icontains=query) | 
            Q(title__icontains=query)
        )

    negative_q = Q()
    for query in negative_queries:
        negative_q |= (
            Q(content__icontains=query) | 
            Q(title__icontains=query)
        )

    # Find matching news pages that don't already have PR examples
    matching_pages = NewsPage.objects.filter(
        positive_q  # Must match positive queries
    ).exclude(
        negative_q  # Must not match negative queries
    ).exclude(
        pr_examples__isnull=False  # Must not already have PR examples
    ).exclude(
        is_news_article=False # Has to be a news article, not category or something
    )

    # Create PR examples for matching pages
    for page in matching_pages:
        DigitalPRExample.objects.create(
            news_page=page,
            title=page.title,
            url=page.url,
            published_date=page.published_date or timezone.now().date(),
            confirmed=False
        )
        logger.info(f"Created digital PR example for: {page.title}")
    
    if search_google:
        search_google_for_digital_pr_examples(domain_limit=2)
    

async def process_journalist_descriptions(limit: int = 10):
    """Process descriptions for journalists that have profile URLs but no descriptions"""
    # Create queues for processing
    scrape_queue = asyncio.Queue()  # Queue of journalists to scrape
    gpt_queue = asyncio.Queue()     # Queue of content to process with GPT
    db_queue = asyncio.Queue()      # Queue of results to write to DB
    
    # Get journalists to process
    journalists = await sync_to_async(list)(
        Journalist.objects.filter(
            profile_url__isnull=False,
            description__isnull=True
        )[:limit]
    )
    
    # Add all journalists to the scrape queue
    for journalist in journalists:
        await scrape_queue.put(journalist)

    async def scrape_worker():
        """Async worker to scrape profile pages"""
        while True:
            try:
                journalist = await scrape_queue.get()
                
                # Scrape the profile page
                website = (
                    Website(journalist.profile_url)
                    .with_user_agent("Mozilla/5.0")
                    .with_request_timeout(30000)
                    .with_respect_robots_txt(False)
                    .with_depth(0)
                )
                
                website.scrape()
                pages = website.get_pages()
                
                if pages:
                    # Put content in GPT queue
                    await gpt_queue.put((journalist, pages[0].content))
                
                scrape_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error scraping {journalist.profile_url}: {str(e)}")
                scrape_queue.task_done()

    async def gpt_worker():
        """Async worker to process GPT requests"""
        while True:
            try:
                journalist, content = await gpt_queue.get()
                
                # Process with GPT
                client = AzureOpenAI(
                    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                    azure_deployment="gpt-4o-mini",
                    api_version="2024-08-01-preview",
                    api_key=os.getenv("AZURE_OPENAI_API_KEY")
                )

                prompt = f"""
                Extract a professional description of the journalist from their profile page.
                Return a JSON object with a single 'description' field containing a 2-3 sentence summary.
                
                Profile content:
                {clean_html(content)}
                """

                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a professional bio writer."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=500,
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )

                result = json.loads(response.choices[0].message.content)
                
                # Put results in DB queue
                await db_queue.put((journalist, result.get('description')))
                
                gpt_queue.task_done()
            except Exception as e:
                logger.error(f"Error in GPT processing: {str(e)}")
                gpt_queue.task_done()

    async def db_worker():
        """Sequential worker to handle DB writes"""
        while True:
            try:
                journalist, description = await db_queue.get()
                
                @sync_to_async
                def save_to_db():
                    with transaction.atomic():
                        journalist.description = description
                        journalist.save()
                
                await save_to_db()
                
                db_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in DB worker: {str(e)}")
                db_queue.task_done()
            finally:
                close_old_connections()

    # Create workers
    scrape_workers = [asyncio.create_task(scrape_worker()) for _ in range(5)]
    gpt_workers = [asyncio.create_task(gpt_worker()) for _ in range(3)]
    db_worker_task = asyncio.create_task(db_worker())
    
    # Wait for all journalists to be processed
    await scrape_queue.join()
    await gpt_queue.join()
    await db_queue.join()
    
    # Cancel workers
    for worker in scrape_workers:
        worker.cancel()
    for worker in gpt_workers:
        worker.cancel()
    db_worker_task.cancel()
    
    # Wait for workers to finish
    await asyncio.gather(*scrape_workers, *gpt_workers, db_worker_task, return_exceptions=True)

def process_journalist_descriptions_sync(limit: int = 10):
    """Sync wrapper for processing journalist descriptions"""
    loop = asyncio.get_event_loop()
    loop.run_until_complete(process_journalist_descriptions(limit))


def guess_journalist_email_address(journalist: Journalist):
    """Guess an email address for a journalist based on their first linked publication"""
    try:
        # Skip if email already exists
        if journalist.email_address:
            return
            
        # Get first linked source's domain
        first_source = journalist.sources.first()
        if not first_source:
            return
            
        # Extract domain from source URL and remove www if present
        domain = first_source.url.split('//')[1].split('/')[0]
        domain = domain.replace('www.', '')
        
        # Skip if domain previously failed
        if is_failed_domain(domain):
            logger.debug(f"Skipping known failed domain: {domain}")
            return
            
        # Initialize mailscout with shorter timeout
        scout = Scout(
            check_variants=False,  # We'll handle variants ourselves
            check_prefixes=False,
            check_catchall=True,
            normalize=True,
            smtp_timeout=2
        )
        
        # Split journalist name into parts
        name_parts = journalist.name.split()
        first_name = name_parts[0].lower()
        
        # Try a single email first to validate domain
        test_email = f"{first_name}@{domain}"
        try:
            valid_emails = scout.find_valid_emails(domain, name_parts)
            if not valid_emails:
                # If no valid emails found, mark domain as failed
                failed_domains.add(domain)
                logger.warning(f"Adding {domain} to failed domains - no valid emails found")
                return None
                
            # Save first valid email found
            with transaction.atomic():
                journalist.email_address = valid_emails[0]
                journalist.email_status = 'guessed'
                journalist.save()
                
            return valid_emails[0]
            
        except Exception as e:
            # Handle any other exceptions
            failed_domains.add(domain)
            logger.error(f"Error guessing email for {journalist.name}: {str(e)}")
            return None
            
    except Exception as e:
        logger.error(f"Error guessing email for {journalist.name}: {str(e)}")
        return None


def guess_journalist_email_addresses(limit: int = 10):
    """Guess email addresses for journalists that have no email addresses"""
    journalists = Journalist.objects.filter(email_address__isnull=True)[:limit]
    for journalist in tqdm(journalists, desc="Guessing emails"):
        guess_journalist_email_address(journalist)


@retry(
    retry=retry_if_exception_type((APIError, APIConnectionError, RateLimitError)),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5)
)
def generate_embedding(text: str) -> List[float]:
    """Generate embedding with retry logic"""
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT"),
        api_version="2023-05-15",
        api_key=os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")
    )
    
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

async def update_page_embeddings(limit: int = 100):
    """Update embeddings for NewsPages that don't have them"""
    try:
        pages = await sync_to_async(list)(
            NewsPage.objects.filter(
                embedding__isnull=True,
                content__isnull=False,
                is_news_article=True
            )[:limit]
        )

        if not pages:
            logger.info("No pages found needing embeddings")
            return

        # Prepare texts for embedding
        texts = [
            truncate_text_for_embeddings(
                f"{page.title}\n\n{page.content}",
                max_tokens=8000
            ) 
            for page in pages
        ]
        
        # Generate embeddings in batches of 20
        batch_size = 20
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = await generate_embeddings(batch_texts)
            all_embeddings.extend(batch_embeddings)

        # Update pages with embeddings
        @sync_to_async
        def save_embeddings():
            with transaction.atomic():
                for page, embedding in zip(pages, all_embeddings):
                    page.embedding = embedding
                    page.save(update_fields=['embedding'])
        
        await save_embeddings()
        logger.info(f"Updated embeddings for {len(pages)} pages")

    except Exception as e:
        logger.error(f"Error updating page embeddings: {str(e)}")
        raise

def update_page_embeddings_sync(limit: int = 100):
    """Sync wrapper for updating page embeddings"""
    loop = asyncio.get_event_loop()
    loop.run_until_complete(update_page_embeddings(limit))

async def update_journalist_embeddings(limit: int = 100):
    """Update embeddings for Journalists that don't have them"""
    try:
        journalists = await sync_to_async(list)(
            Journalist.objects.filter(
                embedding__isnull=True
            ).prefetch_related('categories')[:limit]
        )

        if not journalists:
            logger.info("No journalists found needing embeddings")
            return

        # Prepare texts for embedding
        texts = [
            truncate_text_for_embeddings(
                f"{j.name}\n{j.description or ''}\n{' '.join(j.categories.values_list('name', flat=True))}",
                max_tokens=8000
            ) 
            for j in journalists
        ]
        
        # Generate embeddings in batches of 20
        batch_size = 20
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = await generate_embeddings(batch_texts)
            all_embeddings.extend(batch_embeddings)

        # Update journalists with embeddings
        @sync_to_async
        def save_embeddings():
            with transaction.atomic():
                for journalist, embedding in zip(journalists, all_embeddings):
                    journalist.embedding = embedding
                    journalist.save(update_fields=['embedding'])
        
        await save_embeddings()
        logger.info(f"Updated embeddings for {len(journalists)} journalists")

    except Exception as e:
        logger.error(f"Error updating journalist embeddings: {str(e)}")
        raise

def update_journalist_embeddings_sync(limit: int = 100):
    """Sync wrapper for updating journalist embeddings"""
    loop = asyncio.get_event_loop()
    loop.run_until_complete(update_journalist_embeddings(limit))

# Replace the signal handlers at the bottom of the file
@receiver(post_save, sender=NewsPage)
def update_newspage_embedding_on_change(sender, instance, **kwargs):
    """Update embedding when NewsPage content changes"""
    # Only proceed if this is a news article
    if not instance.is_news_article:
        return
        
    if instance.content and instance.title:
        # Skip if this save was triggered by an embedding update
        if kwargs.get('update_fields') == {'embedding'}:
            return
            
        # Prepare text for embedding
        text = truncate_text_for_embeddings(
            f"{instance.title}\n\n{instance.content}",
            max_tokens=8000
        )
        
        try:
            # Generate embedding synchronously
            client = AzureOpenAI(
                azure_endpoint=os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT"),
                api_version="2023-05-15",
                api_key=os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")
            )
            
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=[text]
            )
            
            # Update the embedding directly
            instance.embedding = response.data[0].embedding
            instance.save()
            
        except Exception as e:
            logger.error(f"Error updating embedding for NewsPage {instance.id}: {str(e)}")

@receiver(post_save, sender=Journalist)
def update_journalist_embedding_on_change(sender, instance, **kwargs):
    """Update embedding when Journalist data changes"""
    # Skip if this save was triggered by an embedding update
    if kwargs.get('update_fields') == {'embedding'}:
        return
        
    # Prepare text for embedding
    text = truncate_text_for_embeddings(
        instance.get_text_for_embedding(),
        max_tokens=8000
    )
    
    try:
        # Generate embedding synchronously
        client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT"),
            api_version="2023-05-15",
            api_key=os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")
        )
        
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=[text]
        )
        
        # Update the embedding directly
        instance.embedding = response.data[0].embedding
        instance.save()
        
    except Exception as e:
        logger.error(f"Error updating embedding for Journalist {instance.id}: {str(e)}")

@receiver(m2m_changed, sender=Journalist.categories.through)
def update_journalist_embedding_on_categories_change(sender, instance, **kwargs):
    """Update embedding when Journalist categories change"""
    # Only update on post_add and post_remove actions
    if kwargs['action'] not in ("post_add", "post_remove"):
        return
    
    update_journalist_embedding_on_change(sender, instance)



def find_single_email_with_hunter_io(name: str, domain: str) -> Optional[str]:
    """Find a single email with Hunter.io"""
    try:
        # Initialize cached session (expires after 1 week)
        session = requests_cache.CachedSession(
            'hunter_cache',
            expire_after=604800  # 7 days in seconds
        )

        # Split name into first and last
        name_parts = name.strip().split()
        if len(name_parts) < 2:
            logger.warning(f"Name '{name}' doesn't contain both first and last name")
            return None

        first_name = name_parts[0]
        last_name = ' '.join(name_parts[1:])  # Handle multi-word last names

        # Clean domain (remove www. and any paths)
        domain = domain.replace('www.', '').split('/')[0]

        # Make request to Hunter.io
        response = session.get(
            'https://api.hunter.io/v2/email-finder',
            params={
                'domain': domain,
                'first_name': first_name,
                'last_name': last_name,
                'api_key': os.getenv('HUNTER_API_KEY')
            }
        )

        # Log raw response for debugging
        logger.info(f"Raw Hunter.io response for {name} at {domain}: {response.text}")

        if response.status_code == 200:
            data = response.json()
            if data.get('data', {}).get('email'):
                return data['data']['email']
            else:
                return None
        else:
            logger.error(f"Hunter.io API error: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        logger.error(f"Error finding email for {name} at {domain}: {str(e)}")
        return None


def find_emails_with_hunter_io(limit: int = 1):
    """Find emails for journalists using Hunter.io until we find the requested number of emails"""
    try:
        emails_found = 0
        batch_size = 10  # Process journalists in batches to avoid loading too many at once
        
        while emails_found < limit:
            # Get next batch of journalists without email addresses
            journalists = Journalist.objects.filter(
                email_address__isnull=True,  # No email yet
                email_search_with_hunter_tried=False,  # Haven't tried Hunter.io yet
                sources__isnull=False  # Must have at least one source
            ).prefetch_related('sources')[:batch_size]
            
            # Break if no more journalists to process
            if not journalists:
                logger.info("No more journalists to process")
                break
                
            logger.info(f"Processing batch of {len(journalists)} journalists. Found {emails_found}/{limit} emails so far")

            for journalist in journalists:
                # Get the first source's domain to try
                first_source = journalist.sources.first()
                if not first_source:
                    continue

                # Extract domain from source URL
                domain = first_source.url.split('//')[1].split('/')[0]
                
                # Try to find email
                email = find_single_email_with_hunter_io(journalist.name, domain)
                
                if email:
                    logger.info(f"Found email {email} for {journalist.name}")
                    # Use update() to avoid triggering signals
                    Journalist.objects.filter(id=journalist.id).update(
                        email_address=email,
                        email_status='guessed_by_third_party',
                        email_search_with_hunter_tried=True
                    )
                    emails_found += 1
                    if emails_found >= limit:
                        logger.info(f"Found requested number of emails ({limit})")
                        return
                else:
                    logger.info(f"No email found for {journalist.name} at {domain}")
                    # Use update() to avoid triggering signals
                    Journalist.objects.filter(id=journalist.id).update(
                        email_search_with_hunter_tried=True
                    )

        logger.info(f"Finished processing. Found {emails_found} emails (requested: {limit})")

    except Exception as e:
        logger.error(f"Error in find_emails_with_hunter_io: {str(e)}")
        raise


def clean_url(url: str) -> str:
    """Remove query parameters and fragments from URL"""
    if not url:
        return url
    parsed = urlparse(url)
    # Reconstruct URL without query parameters or fragments
    clean = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        '',  # params
        '',  # query
        ''   # fragment
    ))
    return clean 

def truncate_text_for_embeddings(text: str, max_tokens: int = 8000) -> str:
    """
    Truncate text to fit within token limit for embeddings.
    Uses tiktoken for accurate token counting.
    """
    try:
        # Initialize tokenizer for text-embedding-3-small
        encoding = tiktoken.get_encoding("cl100k_base")
        
        # Get token count
        tokens = encoding.encode(text)
        
        if len(tokens) <= max_tokens:
            return text
            
        # If text is too long, truncate tokens and decode back to text
        truncated_tokens = tokens[:max_tokens]
        truncated_text = encoding.decode(truncated_tokens)
        
        return truncated_text
        
    except Exception as e:
        logger.error(f"Error truncating text: {str(e)}")
        # If tokenization fails, do a rough character-based truncation
        # Assuming average of 4 characters per token
        char_limit = max_tokens * 4
        return text[:char_limit]

async def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for a batch of texts.
    Uses retry logic and handles rate limits.
    """
    try:
        # Create Azure OpenAI client
        client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT"),
            api_version="2023-05-15",
            api_key=os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")
        )
        
        # Use the retry decorator for the actual API call
        @retry(
            retry=retry_if_exception_type((APIError, APIConnectionError, RateLimitError)),
            wait=wait_exponential(multiplier=1, min=4, max=60),
            stop=stop_after_attempt(5)
        )
        async def _generate_batch_embeddings(batch_texts):
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=batch_texts
            )
            return [data.embedding for data in response.data]
        
        # Generate embeddings
        embeddings = await _generate_batch_embeddings(texts)
        return embeddings
        
    except Exception as e:
        logger.error(f"Error generating embeddings: {str(e)}")
        raise


@shared_task(bind=True)
def crawl_single_page_task(self, url, source_id):
    """Process a single page from a crawl"""
    try:
        news_source = NewsSource.objects.get(id=source_id)
        
        # Skip if page already exists
        if NewsPage.objects.filter(url=url).exists():
            return
            
        # Create website instance for single page
        website = (
            Website(url)
            .with_user_agent("Mozilla/5.0")
            .with_request_timeout(30000)
            .with_respect_robots_txt(False)
            .with_depth(0)  # Only this page
        )
        
        website.scrape()
        pages = website.get_pages()
        
        if not pages:
            logger.warning(f"No content found for {url}")
            return
            
        page = pages[0]
        cleaned_content = clean_html(page.content)
        
        with transaction.atomic():
            news_page = NewsPage.objects.create(
                url=url,
                title=str(page.title()),
                content=cleaned_content,
                source=news_source
            )
            
        # Trigger journalist processing for this page
        process_journalist_task.delay(news_page.id)
        
    except Exception as e:
        logger.error(f"Error processing page {url}: {str(e)}")
        raise

@shared_task(bind=True)
def crawl_single_source_task(self, source_id, page_limit=None):
    """Crawl a single news source"""
    try:
        news_source = NewsSource.objects.get(id=source_id)
        logger.info(f"Starting crawl for {news_source.url}")
        
        # Configure website crawler
        website = (
            Website(news_source.url)
            .with_user_agent("Mozilla/5.0")
            .with_request_timeout(30000)
            .with_respect_robots_txt(False)
            .with_depth(3)
        )
        
        if page_limit:
            website = website.with_budget({"*": page_limit})
        
        # Get list of URLs
        website.scrape()
        pages = website.get_pages()
        
        # Create tasks for each page
        for page in pages[:page_limit] if page_limit else pages:
            crawl_single_page_task.delay(page.url, source_id)
            
        # Update source last crawled time
        with transaction.atomic():
            news_source.last_crawled = timezone.now()
            news_source.save()
            
    except Exception as e:
        logger.error(f"Error crawling source {source_id}: {str(e)}")
        raise

@shared_task
def crawl_news_sources_task(domain_limit=None, page_limit=None):
    """Distribute crawling tasks across workers"""
    try:
        # Get sources to crawl
        news_sources = NewsSource.objects.filter(
            Q(last_crawled__lt=timezone.now() - timezone.timedelta(days=7)) |
            Q(last_crawled__isnull=True)
        ).order_by(
            '-priority',
            'last_crawled'
        )[:domain_limit]
        
        # Log start of crawl
        message = f"[{timezone.now()}] Starting crawl of {len(news_sources)} sources..."
        logger.info(message)
        slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        if slack_webhook_url:
            requests.post(slack_webhook_url, json={"text": message})
        
        # Create tasks for each source
        for source in news_sources:
            crawl_single_source_task.delay(source.id, page_limit)
            
    except Exception as e:
        logger.error(f"Error starting crawl: {str(e)}")
        raise

@shared_task(
        bind=True, name='continuous_crawl',
        max_retries=3,
        default_retry_delay=300,  # 5 minutes
        autoretry_for=(openai.APIConnectionError,)
        )
def continuous_crawl_task(self):
    """Orchestrate the continuous crawling process"""
    try:
        # Validate OpenAI connection first
        client = openai.AzureOpenAI(
            azure_endpoint=os.getenv('OPENAI_API_BASE'),
            api_key=os.getenv('OPENAI_API_KEY'),
            api_version=os.getenv('OPENAI_API_VERSION')
        )
        
        # Test the connection with a simple completion
        try:
            test_response = client.chat.completions.create(
                model=os.getenv('OPENAI_MODEL_NAME'),
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5
            )
            logger.info("OpenAI connection test successful")
        except Exception as e:
            logger.error(f"OpenAI connection test failed: {str(e)}")
            # Log detailed configuration (without sensitive data)
            logger.error(f"OpenAI Configuration: endpoint={os.getenv('OPENAI_API_BASE')}, "
                        f"version={os.getenv('OPENAI_API_VERSION')}, "
                        f"model={os.getenv('OPENAI_MODEL_NAME')}")
            raise

        # Continue with regular task if connection test passes
        newspage_count_before = NewsPage.objects.count()
        journalist_count_before = Journalist.objects.count()
        
        # Chain the crawling tasks
        chain(
            crawl_news_sources_task.s(domain_limit=1, page_limit=2000),
            process_journalists_task.s(limit=1000),
            categorize_pages_task.s(limit=1000),
            update_page_embeddings_task.s(limit=1000),
            update_journalist_embeddings_task.s(limit=500)
        ).delay()
        
        # Log results
        newspage_count_after = NewsPage.objects.count()
        journalist_count_after = Journalist.objects.count()
        
        message = f"Crawl completed. {newspage_count_after - newspage_count_before} pages, {journalist_count_after - journalist_count_before} journalists added."
        logger.info(message)
        
    except Exception as e:
        logger.error(f"Error in continuous crawl: {str(e)}")
        self.retry(countdown=300)


@shared_task(bind=True)
def process_journalist_task(self, page_id):
    """Process journalists for a single page"""
    try:
        page = NewsPage.objects.get(id=page_id)
        journalists_data = extract_journalists_with_gpt(page.content)
        
        with transaction.atomic():
            page.is_news_article = journalists_data.get('content_is_full_news_article', False)
            
            published_date_str = journalists_data.get('article_published_date')
            if published_date_str:
                try:
                    published_date = datetime.strptime(published_date_str, '%Y-%m-%d').date()
                    page.published_date = published_date
                except ValueError:
                    pass
            
            if journalists_data and 'journalists' in journalists_data:
                for journalist_dict in journalists_data['journalists']:
                    if 'name' in journalist_dict:
                        name = journalist_dict['name']
                        profile_url = clean_url(journalist_dict.get('profile_url', ''))
                        image_url = clean_url(journalist_dict.get('image_url', ''))
                        journalist_slug = slugify(name)
                        
                        journalist, _ = Journalist.objects.get_or_create(
                            name=name,
                            slug=journalist_slug,
                            defaults={
                                'profile_url': profile_url,
                                'image_url': image_url
                            }
                        )
                        page.journalists.add(journalist)
            
            page.processed = True
            page.save()
            
    except Exception as e:
        logger.error(f"Error processing page {page_id}: {str(e)}")
        raise

@shared_task
def process_journalists_task(limit=10):
    """Distribute journalist processing tasks"""
    pages = NewsPage.objects.exclude(content='').filter(processed=False)[:limit]
    
    for page in pages:
        process_journalist_task.delay(page.id)

@shared_task(bind=True)
def categorize_page_task(self, page_id):
    """Categorize a single news page"""
    try:
        page = NewsPage.objects.get(id=page_id)
        categorize_news_page_with_gpt(page)
    except Exception as e:
        logger.error(f"Error categorizing page {page_id}: {str(e)}")
        raise

@shared_task
def categorize_pages_task(limit=1000):
    """Distribute categorization tasks"""
    pages = NewsPage.objects.filter(
        categories__isnull=True, 
        journalists__isnull=False,
        is_news_article=True
    ).distinct()[:limit]
    
    for page in pages:
        categorize_page_task.delay(page.id)

@shared_task(bind=True)
def update_single_page_embedding_task(self, page_id):
    """Update embedding for a single page"""
    try:
        page = NewsPage.objects.get(id=page_id)
        if not page.is_news_article:
            return
            
        text = truncate_text_for_embeddings(
            f"{page.title}\n\n{page.content}",
            max_tokens=8000
        )
        
        client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT"),
            api_version="2023-05-15",
            api_key=os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")
        )
        
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=[text]
        )
        
        with transaction.atomic():
            page.embedding = response.data[0].embedding
            page.save(update_fields=['embedding'])
            
    except Exception as e:
        logger.error(f"Error updating page embedding {page_id}: {str(e)}")
        raise

@shared_task
def update_page_embeddings_task(limit=100):
    """Distribute page embedding updates"""
    pages = NewsPage.objects.filter(
        embedding__isnull=True,
        content__isnull=False,
        is_news_article=True
    )[:limit]
    
    for page in pages:
        update_single_page_embedding_task.delay(page.id)

@shared_task(bind=True)
def update_single_journalist_embedding_task(self, journalist_id):
    """Update embedding for a single journalist"""
    try:
        journalist = Journalist.objects.get(id=journalist_id)
        text = truncate_text_for_embeddings(
            journalist.get_text_for_embedding(),
            max_tokens=8000
        )
        
        client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT"),
            api_version="2023-05-15",
            api_key=os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")
        )
        
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=[text]
        )
        
        with transaction.atomic():
            journalist.embedding = response.data[0].embedding
            journalist.save(update_fields=['embedding'])
            
    except Exception as e:
        logger.error(f"Error updating journalist embedding {journalist_id}: {str(e)}")
        raise

@shared_task
def update_journalist_embeddings_task(limit=100):
    """Distribute journalist embedding updates"""
    journalists = Journalist.objects.filter(
        embedding__isnull=True
    )[:limit]
    
    for journalist in journalists:
        update_single_journalist_embedding_task.delay(journalist.id)
