import asyncio
import json
import os
import random
from django.utils import timezone
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
import dns.exception
from datetime import datetime
import requests


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
        
        news_sources = await sync_to_async(list)(
            NewsSource.objects.filter(
                Q(last_crawled__lt=timezone.now() - timezone.timedelta(days=7)) |
                Q(last_crawled__isnull=True)
            ).order_by(
                '-priority',  # Priority sources first
                'last_crawled'  # Then by least recently crawled
            )[:domain_limit]
        )
        
        logger.info(f"Found {len(news_sources)} news sources to crawl")
        
        semaphore = asyncio.Semaphore(max_concurrent_tasks)
        
        tasks = []
        for news_source in news_sources:
            tasks.append(crawl_single_news_source(news_source, limit=page_limit, semaphore=semaphore))
        
        await asyncio.gather(*tasks)
                
    except Exception as e:
        logger.error(f"Critical error in crawl_news_sources: {str(e)}")
        raise

async def crawl_single_news_source(news_source, limit, semaphore):
    async with semaphore:
        try:
            logger.info(f"Starting crawl for {news_source.url}")
            
            await fetch_website(news_source.url, limit=limit)
            
            # Move database operation inside sync_to_async wrapper
            @sync_to_async
            def update_news_source():
                news_source.refresh_from_db()
                news_source.last_crawled = timezone.now()
                news_source.save()
                
            await update_news_source()
            
        except Exception as e:
            logger.error(f"Error crawling {news_source.url}: {str(e)}")
        finally:
            close_old_connections()


def crawl_news_sources_sync(domain_limit: int = None, page_limit: int = None, max_concurrent_tasks: int = 2):
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
                                    profile_url = journalist_dict.get('profile_url', '')
                                    image_url = journalist_dict.get('image_url', '')
                                    journalist_slug = slugify(name)
                                    
                                    # Log field lengths
                                    logger.info(f"Field lengths - name: {len(name)}, profile_url: {len(profile_url)}, image_url: {len(image_url)}, slug: {len(journalist_slug)}")
                                    
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
                                    except IntegrityError as e:
                                        logger.error(f"Integrity error for journalist: {name}")
                                        logger.error(f"Field values and lengths:")
                                        logger.error(f"name ({len(name)}): {name}")
                                        logger.error(f"slug ({len(journalist_slug)}): {journalist_slug}")
                                        logger.error(f"profile_url ({len(profile_url)}): {profile_url}")
                                        logger.error(f"image_url ({len(image_url)}): {image_url}")
                                        raise e
                        
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
        print('categories:', categories_data)
        for category_name in categories_data['categories']:
            category, created = NewsPageCategory.objects.get_or_create(name=category_name)
            page.categories.add(category)
    except json.JSONDecodeError:
        print('error:', result)
        categories_data = {}


def categorize_news_pages_with_gpt(limit: int = 1000_000):
    print("Categorizing news pages with GPT")
    pages = NewsPage.objects.filter(categories__isnull=True, journalists__isnull=False).distinct()[:limit]
    for page in tqdm(pages):
        categorize_news_page_with_gpt(page)


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
        
        # Paste logo on left side with padding
        logo_x = 100
        logo_y = (height - logo_height) // 2
        image.paste(logo, (logo_x, logo_y), logo if logo.mode == 'RGBA' else None)

        # Add text on right side
        try:
            font_path = os.path.join(settings.STATIC_ROOT, 'fonts', 'SpaceMono-Bold.ttf')
            logger.debug(f"Loading font from: {font_path}")
            font = ImageFont.truetype(font_path, 60)
            logger.info("Successfully loaded custom font")
        except Exception as e:
            logger.warning(f"Failed to load custom font, falling back to default: {str(e)}")
            font = ImageFont.load_default()

        text = f"Connect with\n{journalists_count:,} Journalists\nfrom {media_outlets_count:,}\nMedia Outlets"
        text_x = logo_x + logo_width + 100
        text_y = height // 2 - 100
        
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


