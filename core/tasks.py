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
from typing import Optional
import requests_cache
from urllib.parse import urlparse, urlunparse
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from openai import APIError, APIConnectionError, RateLimitError
from celery import chain
from core.celery import app  # Import the Celery app instance
from celery import shared_task
from core.typesense_config import get_typesense_client
from core.utils.typesense_utils import sync_recent_journalists
import time
import socket


load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

lunary.config(app_id=os.getenv('LUNARY_PUBLIC_KEY'))

# Initialize Azure OpenAI client with proper configuration
azure_openai_client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/").strip('"').strip("'"),  # Remove trailing slash and quotes
    api_version="2024-02-15-preview",
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    max_retries=5,      # Increased from 3
    timeout=60.0,       # Increased from 30
    default_headers={   # Add custom headers
        "User-Agent": "NachoPR/1.0",
        "Connection": "keep-alive"
    }
)

def validate_azure_endpoint():
    """Validate Azure OpenAI endpoint format"""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    if not endpoint:
        logger.error("AZURE_OPENAI_ENDPOINT environment variable is not set")
        return False
        
    try:
        # Remove any trailing slashes and quotes
        endpoint = endpoint.rstrip("/").strip('"').strip("'")
        
        # Parse URL to validate format
        parsed = urlparse(endpoint)
        if not all([parsed.scheme, parsed.netloc]):
            logger.error(f"Invalid endpoint format: {endpoint}")
            return False
            
        # Test DNS resolution
        hostname = parsed.netloc
        try:
            socket.gethostbyname(hostname)
            logger.info(f"Successfully resolved {hostname}")
            return True
        except socket.gaierror as e:
            logger.error(f"DNS resolution failed for {hostname}: {str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"Error validating endpoint: {str(e)}")
        return False

# Add validation check on startup
if not validate_azure_endpoint():
    logger.error("Failed to validate Azure OpenAI endpoint")

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
            ).filter(
                url__isnull=False
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


@retry(
    retry=retry_if_exception_type((APIError, APIConnectionError, RateLimitError)),
    wait=wait_exponential(multiplier=2, min=4, max=120),  # Increased max wait time
    stop=stop_after_attempt(8)  # Increased retry attempts
)
def extract_journalists_with_gpt(content: str) -> dict:
    """
    Extract journalist information from the HTML content using GPT-4 on Azure.
    """
    try:
        run_id = str(uuid.uuid4())
        logger.info(f"Starting journalist extraction for run {run_id}")

        clean_content = clean_html(content)
        
        lunary.monitor(azure_openai_client)

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

        # Add request ID to headers for tracing
        azure_openai_client.default_headers['X-Request-ID'] = run_id
        
        # Log API request details
        logger.info(f"Making API call for run {run_id}")
        logger.debug(f"API endpoint: {os.getenv('AZURE_OPENAI_ENDPOINT')}")
        logger.debug(f"Content length: {len(clean_content)} characters")

        start_time = time.time()
        response = azure_openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a html to json extractor."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            n=1,
            stop=None,
            temperature=0.3,
            response_format={"type": "json_object"},
            timeout=90  # Increased timeout to 90 seconds
        )
        elapsed_time = time.time() - start_time

        # Log response timing and details
        logger.info(f"API call completed for run {run_id} in {elapsed_time:.2f}s")
        logger.debug(f"Response tokens: {response.usage.total_tokens if hasattr(response, 'usage') else 'unknown'}")

        result = response.choices[0].message.content
        journalists_data = json.loads(result)
        logger.info(f"Successfully extracted journalists for run {run_id}")
        return journalists_data

    except RateLimitError as e:
        logger.error(f"Rate limit exceeded for run {run_id if 'run_id' in locals() else 'unknown'}")
        logger.error(f"Rate limit details: {str(e)}")
        # Log headers and response for debugging
        if hasattr(e, 'response'):
            logger.error(f"Response headers: {e.response.headers if e.response else 'No headers'}")
        raise

    except APIConnectionError as e:
        logger.error(f"Connection error in run {run_id if 'run_id' in locals() else 'unknown'}")
        logger.error(f"Connection error details: {str(e)}")
        # Log network diagnostics
        try:
            import socket
            import urllib.parse
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            parsed_url = urllib.parse.urlparse(endpoint)
            hostname = parsed_url.hostname
            logger.error(f"Attempting to resolve {hostname}")
            ip = socket.gethostbyname(hostname)
            logger.error(f"DNS resolution: {hostname} -> {ip}")
        except Exception as dns_error:
            logger.error(f"DNS diagnostic failed: {str(dns_error)}")
        raise

    except APIError as e:
        logger.error(f"API error in run {run_id if 'run_id' in locals() else 'unknown'}")
        logger.error(f"API error details: {str(e)}")
        if hasattr(e, 'response'):
            logger.error(f"Response status: {e.response.status_code if e.response else 'No status'}")
            logger.error(f"Response body: {e.response.text if e.response else 'No body'}")
        raise

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in run {run_id if 'run_id' in locals() else 'unknown'}")
        logger.error(f"Raw response: {result if 'result' in locals() else None}")
        logger.error(f"JSON error details: {str(e)}")
        return {}

    except Exception as e:
        logger.error(f"Unexpected error in run {run_id if 'run_id' in locals() else 'unknown'}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error details: {str(e)}", exc_info=True)
        raise


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



@app.task(
    bind=True,
    name='categorize_news_page_with_gpt'
)
def categorize_news_page_with_gpt(self, page: NewsPage):
    """Add this transaction wrapper and explicit category sync"""
    available_categories = NewsPageCategory.objects.all()
    
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
    response = azure_openai_client.chat.completions.create(
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
        raise self.retry()
    except Exception as e:
        logger.error(f'Error in categorize_news_page_with_gpt: {str(e)}')
        raise self.retry()


@app.task(
    name='categorize_pages_task'
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
                
                prompt = f"""
                Extract a professional description of the journalist from their profile page.
                Return a JSON object with a single 'description' field containing a 2-3 sentence summary.
                
                Profile content:
                {clean_html(content)}
                """

                response = azure_openai_client.chat.completions.create(
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

@app.task(
    bind=True, 
    name='nachopr.crawl_single_page',
    track_started=True, 
    ignore_result=False
)
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

@app.task(
    bind=True, 
    name='nachopr.crawl_single_source',
    track_started=True, 
    ignore_result=False
)
def crawl_single_source_task(self, source_id, page_limit=None):
    """Crawl a single news source"""
    try:
        news_source = NewsSource.objects.get(id=source_id)
        start_message = f"🚀 Starting crawl for {news_source.url}"
        logger.info(start_message)
        slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        if slack_webhook_url:
            requests.post(slack_webhook_url, json={"text": start_message})
        
        # Get initial page count
        pages_before = NewsPage.objects.filter(source=news_source).count()
        
        # Use spider_rs for the full crawl
        website = (
            Website(news_source.url)
            .with_user_agent("Mozilla/5.0")
            .with_request_timeout(30000)
            .with_respect_robots_txt(False)
            .with_depth(3)
        )
        
        if page_limit:
            website = website.with_budget({"*": page_limit})
        
        # Get pages with content
        website.scrape()
        pages = website.get_pages()
        logger.info(f"Found {len(pages)} pages for {news_source.url}")
        
        # Process pages in bulk
        with transaction.atomic():
            for page in pages:
                # Skip if page already exists
                if NewsPage.objects.filter(url=page.url).exists():
                    continue
                    
                cleaned_content = clean_html(page.content)
                news_page = NewsPage.objects.create(
                    url=page.url,
                    title=str(page.title()),
                    content=cleaned_content,
                    source=news_source
                )
                
                # Queue journalist extraction for this page
                process_journalist_task.delay(news_page.id)
            
            # Update source last crawled time
            news_source.last_crawled = timezone.now()
            news_source.save()
            
        # After crawling, get final count and send completion message
        pages_after = NewsPage.objects.filter(source=news_source).count()
        new_pages = pages_after - pages_before
        
        end_message = f"✅ Finished crawl for {news_source.url}\n• Found {new_pages:,} new pages\n• Total pages: {pages_after:,}"
        logger.info(end_message)
        if slack_webhook_url:
            requests.post(slack_webhook_url, json={"text": end_message})
            
    except Exception as e:
        error_message = f"❌ Error crawling {news_source.url if 'news_source' in locals() else 'source'}: {str(e)}"
        logger.error(error_message)
        if slack_webhook_url:
            requests.post(slack_webhook_url, json={"text": error_message})
        raise

@app.task(
    name='nachopr.crawl_news_sources',
    track_started=True,
    ignore_result=False
)
def crawl_news_sources_task(domain_limit=None, page_limit=None):
    """Distribute crawling tasks across workers"""
    try:
        # Get sources to crawl
        news_sources = NewsSource.objects.filter(
            #Q(last_crawled__lt=timezone.now() - timezone.timedelta(days=7)) |
            Q(last_crawled__isnull=True)
        ).order_by(
            '-priority',
            'last_crawled'
        )[:domain_limit]
        
        pages_before = NewsPage.objects.count()

        # Log start of crawl
        message = f"[{timezone.now()}] Starting crawl of {len(news_sources)} sources..."
        logger.info(message)
        slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        if slack_webhook_url:
            requests.post(slack_webhook_url, json={"text": message})
        
        # Create tasks for each source
        for source in news_sources:
            crawl_single_source_task.delay(source.id, page_limit)

        message = f"[{timezone.now()}] Finished crawl of {len(news_sources)} sources. Found {NewsPage.objects.count() - pages_before} new pages"
        logger.info(message)
        if slack_webhook_url:
            requests.post(slack_webhook_url, json={"text": message})
            
    except Exception as e:
        logger.error(f"Error starting crawl: {str(e)}")
        raise

@app.task(
    bind=True,
    name='nachopr.continuous_crawl',  # Use consistent naming pattern
    max_retries=3,
    default_retry_delay=300,
    retry_backoff=True,
    retry_backoff_max=3600,
    retry_jitter=True,
    track_started=True,
    ignore_result=False
)
def continuous_crawl_task(self):
    """Orchestrate the continuous crawling process"""
    try:
        newspage_count_before = NewsPage.objects.count()
        journalist_count_before = Journalist.objects.count()
        
        # Chain the crawling tasks with error handling
        chain(
            crawl_news_sources_task.si(domain_limit=1, page_limit=2000),
            #process_journalists_task.si(limit=1000),
            #categorize_pages_task.si(limit=1000)
        ).apply_async(link_error=handle_chain_error.s())
        
        # Log results
        newspage_count_after = NewsPage.objects.count()
        journalist_count_after = Journalist.objects.count()
        
        message = f"Crawl completed. {newspage_count_after - newspage_count_before} pages, {journalist_count_after - journalist_count_before} journalists added."
        logger.info(message)
        
    except Exception as e:
        logger.error(f"Error in continuous crawl: {str(e)}", exc_info=True)
        
        # Only retry for specific exceptions that might be temporary
        if isinstance(e, (openai.APIConnectionError, requests.exceptions.RequestException)):
            # Use countdown instead of retry_delay for immediate retries
            try:
                self.retry(
                    exc=e,
                    countdown=self.default_retry_delay * (2 ** self.request.retries)
                )
            except self.MaxRetriesExceededError:
                logger.error("Max retries exceeded for continuous crawl task")
                raise
        else:
            # For other exceptions, log and fail permanently
            logger.critical(f"Fatal error in continuous crawl: {str(e)}")
            raise

@app.task
def handle_chain_error(request, exc, traceback):
    """Handle errors in the task chain"""
    logger.error(f"Task chain error: {exc}", exc_info=True)
    # Notify admins or take other error handling actions as needed

@app.task(bind=True, name='process_journalist_task', track_started=True, ignore_result=False)
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

@app.task(name='process_journalists_task', track_started=True, ignore_result=False)
def process_journalists_task(limit=2):
    """Distribute journalist processing tasks"""
    pages = NewsPage.objects.exclude(content='').filter(processed=False)[:limit]
    
    for page in pages:
        process_journalist_task.delay(page.id)

@app.task(bind=True, name='categorize_page_task', track_started=True, ignore_result=False)
def categorize_page_task(self, page_id):
    """Categorize a single news page"""
    try:
        page = NewsPage.objects.get(id=page_id)
        categorize_news_page_with_gpt(page)
    except Exception as e:
        logger.error(f"Error categorizing page {page_id}: {str(e)}")
        raise

@app.task(name='categorize_pages_task', track_started=True, ignore_result=False)
def categorize_pages_task(limit=1000):
    """Distribute categorization tasks"""
    pages = NewsPage.objects.filter(
        categories__isnull=True, 
        journalists__isnull=False,
        is_news_article=True
    ).distinct()[:limit]
    
    for page in pages:
        categorize_page_task.delay(page.id)



def send_slack_notification(message, blocks=None):
    """Send a notification to Slack"""
    webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set, skipping notification")
        return
    
    try:
        payload = {'text': message}
        if blocks:
            payload['blocks'] = blocks
            
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Error sending Slack notification: {str(e)}")

@shared_task(bind=True)
def migrate_to_typesense_task(self):
    """Run Typesense migration as a background task"""
    try:
        # First check if migration is needed
        client = get_typesense_client()
        
        try:
            collection_stats = client.collections['journalists'].retrieve()
            current_docs = collection_stats.get('num_documents', 0)
        except Exception as e:
            logger.warning(f"Could not get collection stats, assuming empty: {str(e)}")
            current_docs = 0
            
        total_journalists = Journalist.objects.count()
        
        if current_docs >= total_journalists:
            logger.info(f"Typesense collection already has {current_docs} documents, no migration needed")
            return
            
        logger.info(f"Starting Typesense migration in background for {total_journalists} journalists")
        send_slack_notification(f"🔄 Starting Typesense migration for {total_journalists} journalists...")
        
        # Run migration in batches
        batch_size = 100
        processed = 0
        
        # Get all journalists ordered by ID to ensure consistent batching
        while processed < total_journalists:
            batch = Journalist.objects.all().order_by('id')[processed:processed + batch_size]
            for journalist in batch:
                try:
                    # Force update even if document exists
                    journalist.update_typesense(force=True)
                    logger.debug(f"Migrated journalist {journalist.id}: {journalist.name}")
                except Exception as e:
                    logger.error(f"Error migrating journalist {journalist.id}: {str(e)}")
            
            processed += batch_size
            logger.info(f"Migrated {min(processed, total_journalists)}/{total_journalists} journalists")
        
        # Verify the migration
        try:
            collection_stats = client.collections['journalists'].retrieve()
            final_docs = collection_stats.get('num_documents', 0)
            
            # Create a formatted message for Slack
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "✅ *Typesense Migration Complete*"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Total Documents:*\n{final_docs}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*DB Count:*\n{total_journalists}"
                        }
                    ]
                }
            ]
            
            send_slack_notification("Typesense migration completed", blocks)
            logger.info(f"Typesense collection stats after migration: {collection_stats}")
            
        except Exception as e:
            logger.error(f"Error verifying migration: {str(e)}")
            
    except Exception as e:
        error_msg = f"❌ Error during Typesense migration: {str(e)}"
        send_slack_notification(error_msg)
        logger.error(error_msg, exc_info=True)
        raise

@app.task(name='core.tasks.sync_typesense_index')
def sync_typesense_index():
    """
    Periodic task to sync Typesense index with database.
    Runs every hour to ensure Typesense stays in sync with the database.
    """
    try:
        logger.info("Starting Typesense sync")
        count = sync_recent_journalists()
        
        # Verify the sync
        client = get_typesense_client()
        collection_stats = client.collections['journalists'].retrieve()
        
        if count > 0:
            # Only send notification if there were updates
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "✅ *Typesense Sync Complete*"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Journalists Updated:*\n{count}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Total Documents:*\n{collection_stats.get('num_documents', 0)}"
                        }
                    ]
                }
            ]
            send_slack_notification("Typesense sync completed", blocks)
        
        logger.info(f"Typesense collection stats after sync: {collection_stats}")
        logger.info(f"Synced {count} journalists")
    except Exception as e:
        error_msg = f"❌ Error during Typesense sync: {str(e)}"
        send_slack_notification(error_msg)
        logger.error(error_msg, exc_info=True)
        raise