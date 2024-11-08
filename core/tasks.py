import asyncio
import json
import os
from django.utils import timezone
from core.models import NewsPage, NewsSource, Journalist
from spider_rs import Website 
from django.db import close_old_connections, IntegrityError
from asgiref.sync import sync_to_async
from django.utils.text import slugify
from openai import AzureOpenAI
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

async def crawl_news_sources(limit: int = None, max_concurrent_tasks: int = 10):
    try:
        logger.info(f"Starting crawl at {timezone.now()}")
        
        news_sources = await sync_to_async(list)(
            NewsSource.objects.filter(
                last_crawled__lt=timezone.now() - timezone.timedelta(days=1)
            )
        )
        
        logger.info(f"Found {len(news_sources)} news sources to crawl")
        
        semaphore = asyncio.Semaphore(max_concurrent_tasks)
        
        tasks = []
        for news_source in news_sources:
            tasks.append(crawl_single_news_source(news_source, limit, semaphore))
        
        await asyncio.gather(*tasks)
                
    except Exception as e:
        logger.error(f"Critical error in crawl_news_sources: {str(e)}")
        raise

async def crawl_single_news_source(news_source, limit, semaphore):
    async with semaphore:
        try:
            logger.info(f"Starting crawl for {news_source.url}")
            start_time = timezone.now()
            
            await fetch_website(news_source.url, limit=limit)
            
            end_time = timezone.now()
            duration = end_time - start_time
            logger.info(f"Finished crawling {news_source.url} in {duration}")
            
            news_source.last_crawled = end_time
            await sync_to_async(news_source.save)()
            close_old_connections()
        except Exception as e:
            logger.error(f"Error crawling {news_source.url}: {str(e)}")


def crawl_news_sources_sync(limit : int = None):
    loop = asyncio.get_event_loop()
    loop.run_until_complete(crawl_news_sources(limit))


async def fetch_website(url: str, limit: int = 1000_000, depth: int = 3) -> Website:
    try:
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
        logger.info(f"Fetched {len(pages)} pages from {url}")
        
        news_source = await sync_to_async(NewsSource.objects.get)(url=url)
        
        for page in pages:
            try:
                slug = slugify(page.title)
                
                news_page, created = await sync_to_async(NewsPage.objects.get_or_create)(
                    url=page.url,
                    slug=slug,
                    defaults={
                        'title': page.title,
                        'content': page.content,
                        'source': news_source,
                        'slug': slug
                    }
                )
                #await process_single_page_journalists(news_page)
                logger.info(f"Successfully processed page: {page.url}")
            except IntegrityError as e:
                logger.warning(f"Skipping duplicate page: {page.url} - {str(e)}")
                continue
            except Exception as e:
                logger.error(f"Error processing page {page.url}: {str(e)}")
                continue
            
            close_old_connections()
    except Exception as e:
        logger.error(f"Error in fetch_website for {url}: {str(e)}")
        raise


def extract_journalists_with_gpt(content: str) -> dict:
    """
    Extract journalist information from the HTML content using GPT-4 on Azure.
    """
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_deployment="gpt-4o-mini",
        api_version="2024-08-01-preview",
        api_key=os.getenv("AZURE_OPENAI_API_KEY")
    )
    journalist_json = { "journalists": [
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
    
    HTML content:
    ```
    {content[:10000]}
    ```

    Use the following JSON schema:
    ```
    {journalist_json}
    ```
    If you cannot find any journalists, return an empty JSON object. Never output the example JSON objects such as 'John Doe' and 'Jane Smith'.
    """

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

    # Parse the response
    result = response.choices[0].message.content
    try:
        journalists_data = json.loads(result)
    except json.JSONDecodeError:
        print('error:', result)
        journalists_data = {}

    return journalists_data


async def process_single_page_journalists(page: NewsPage):
    """Process journalists for a single news page using GPT"""
    journalists_data = extract_journalists_with_gpt(page.content)
    
    if journalists_data and 'journalists' in journalists_data:
        for journalist_dict in journalists_data['journalists']:
            if 'name' in journalist_dict:
                name = journalist_dict['name']
                profile_url = journalist_dict.get('profile_url')
                image_url = journalist_dict.get('image_url')
                
                # Generate a slug from the journalist's name
                journalist_slug = slugify(name)
                
                try:
                    journalist, created = await sync_to_async(Journalist.objects.get_or_create)(
                        name=name,
                        slug=journalist_slug,
                        defaults={
                            'profile_url': profile_url,
                            'image_url': image_url
                        }
                    )
                    print('created:' if created else 'existing:', journalist_dict)
                    
                    # Associate the journalist with the news page
                    await sync_to_async(page.journalists.add)(journalist)
                except IntegrityError:
                    print('skipping (integrity error):', journalist_dict)
    
    page.processed = True
    await sync_to_async(page.save)()

async def process_all_pages_journalists(limit: int = 10):
    """Process journalists for multiple pages using GPT"""
    pages = await sync_to_async(list)(NewsPage.objects.filter(processed=False)[:limit])
    for page in pages:
        await process_single_page_journalists(page)

def extract_all_journalists_with_gpt(limit: int = 1000_000):
    """Sync wrapper for processing multiple pages"""
    asyncio.run(process_all_pages_journalists(limit))

