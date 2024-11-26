import asyncio
import json
import os
from django.utils import timezone
from core.models import NewsPage, NewsPageCategory, NewsSource, Journalist
from spider_rs import Website 
from django.db import close_old_connections, IntegrityError
from asgiref.sync import sync_to_async
from django.utils.text import slugify
from openai import AzureOpenAI
from dotenv import load_dotenv
import logging
from django.db.models import Q
import lunary
import uuid
from markdownify import markdownify
from django.db import transaction
from functools import lru_cache
from datetime import datetime
import requests
from celery import shared_task, chain
from urllib.parse import urlparse, urlunparse
import tiktoken


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


@shared_task(bind=True, name='crawl_single_page')
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

@shared_task(bind=True, name='crawl_single_source')
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

@shared_task(name='crawl_news_sources')
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

@shared_task(bind=True, name='continuous_crawl')
def continuous_crawl_task(self):
    """Orchestrate the continuous crawling process"""
    try:
        logger.info("Starting continuous_crawl_task")
        
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
@shared_task(bind=True, name='process_journalist')
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

@shared_task(name='process_journalists')
def process_journalists_task(limit=10):
    """Distribute journalist processing tasks"""
    pages = NewsPage.objects.exclude(content='').filter(processed=False)[:limit]
    
    for page in pages:
        process_journalist_task.delay(page.id)

@shared_task(bind=True, name='categorize_page')
def categorize_page_task(self, page_id):
    """Categorize a single news page"""
    try:
        page = NewsPage.objects.get(id=page_id)
        categorize_news_page_with_gpt(page)
    except Exception as e:
        logger.error(f"Error categorizing page {page_id}: {str(e)}")
        raise

@shared_task(name='categorize_pages')
def categorize_pages_task(limit=1000):
    """Distribute categorization tasks"""
    pages = NewsPage.objects.filter(
        categories__isnull=True, 
        journalists__isnull=False,
        is_news_article=True
    ).distinct()[:limit]
    
    for page in pages:
        categorize_page_task.delay(page.id)

@shared_task(bind=True, name='update_page_embedding')
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

@shared_task(name='update_page_embeddings')
def update_page_embeddings_task(limit=100):
    """Distribute page embedding updates"""
    pages = NewsPage.objects.filter(
        embedding__isnull=True,
        content__isnull=False,
        is_news_article=True
    )[:limit]
    
    for page in pages:
        update_single_page_embedding_task.delay(page.id)

@shared_task(bind=True, name='update_journalist_embedding')
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

@shared_task(name='update_journalist_embeddings')
def update_journalist_embeddings_task(limit=100):
    """Distribute journalist embedding updates"""
    journalists = Journalist.objects.filter(
        embedding__isnull=True
    )[:limit]
    
    for journalist in journalists:
        update_single_journalist_embedding_task.delay(journalist.id)

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
