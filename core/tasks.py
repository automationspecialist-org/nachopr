import asyncio
import json
import os
import re
from bs4 import BeautifulSoup
from django.utils import timezone
from tqdm import tqdm
from core.models import NewsPage, NewsPageCategory, NewsSource, Journalist
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
from readabilipy import simple_json_from_html_string
from dotenv import load_dotenv
import uuid


load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

lunary.config(app_id=os.getenv('LUNARY_PUBLIC_KEY'))


async def crawl_news_sources(domain_limit: int = None, page_limit: int = None, max_concurrent_tasks: int = 20):
    try:
        logger.info(f"Starting crawl at {timezone.now()}")
        
        news_sources = await sync_to_async(list)(
            NewsSource.objects.filter(
                Q(last_crawled__lt=timezone.now() - timezone.timedelta(days=7)) |
                Q(last_crawled__isnull=True)
            ).order_by('last_crawled')[:domain_limit]
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


def crawl_news_sources_sync(domain_limit: int = None, page_limit: int = None):
    loop = asyncio.get_event_loop()
    loop.run_until_complete(crawl_news_sources(domain_limit=domain_limit, page_limit=page_limit))


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


def clean_html(html: str) -> str:
    cleaned_dict = simple_json_from_html_string(html, use_readability=True)

    cleaned_html = {
        "title": cleaned_dict.get("title"),
        "journalist_names": cleaned_dict.get("byline"),
        "content": cleaned_dict.get("plain_content")
    }

    
    return cleaned_html


def extract_journalists_with_gpt(content: str) -> dict:
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

    journalist_json = { 
        "content_is_full_news_article": True,
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
    
    HTML content parsed to JSON:
    ```
    {clean_content}
    ```

    Use the following JSON schema:
    ```
    {journalist_json}
    ```
    If you cannot find any journalists, return an empty JSON object. Never output the example JSON objects such as 'John Doe' and 'Jane Smith'.
    """

    # Track the start of the LLM call
    lunary.track_event(
        run_type="llm",
        event_name="start",
        run_id=run_id,
        name="gpt-4o-mini",
        input=prompt,
        params={
            "max_tokens": 2000,
            "temperature": 0.3,
            "response_format": {"type": "json_object"}
        }
    )

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

        # Track successful completion with both raw and parsed output
        lunary.track_event(
            run_type="llm",
            event_name="end",
            run_id=run_id,
            output={
                "raw_response": result,
                "parsed_data": journalists_data
            },
            token_usage=response.usage.total_tokens if hasattr(response, 'usage') else None
        )

    except (Exception, json.JSONDecodeError) as e:
        # Track error with the raw response if available
        error_data = {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "raw_response": result if 'result' in locals() else None
        }
        lunary.track_event(
            run_type="llm",
            event_name="error",
            run_id=run_id,
            error=error_data
        )
        print('error:', result if 'result' in locals() else str(e))
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

async def process_all_pages_journalists(limit: int = 10, re_process: bool = False):
    """Process journalists for multiple pages using GPT"""
    if re_process:
        pages = await sync_to_async(list)(NewsPage.objects.all()[:limit])
    else:
        pages = await sync_to_async(list)(NewsPage.objects.filter(processed=False)[:limit])
    for page in pages:
        await process_single_page_journalists(page)

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
    pages = NewsPage.objects.filter(categories__isnull=True)[:limit]
    for page in tqdm(pages):
        categorize_news_page_with_gpt(page)


def create_social_sharing_image():
    media_outlets_count = NewsSource.objects.count()
    journalists_count = Journalist.objects.count()
    
    # Create gradient background
    width = 1200
    height = 630
    image = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(image)

    # Draw gradient from dark green to light green
    for y in range(height):
        r = int(22 + (y/height) * 20)  # Slight red variation
        g = int(163 + (y/height) * 20)  # Green variation from ~163 to ~183
        b = int(74 + (y/height) * 20)   # Slight blue variation
        for x in range(width):
            draw.point((x, y), fill=(r, g, b))

    # Load and paste logo
    logo_path = os.path.join(settings.STATIC_ROOT, 'img', 'logo.png')
    logo = Image.open(logo_path)
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
        font = ImageFont.truetype(font_path, 60)
    except Exception as e:
        logger.error(f"Error loading font: {e}")
        # Fallback to default font if custom font not found
        font = ImageFont.load_default()

    text = f"Connect with\n{journalists_count:,} Journalists\nfrom {media_outlets_count:,}\nMedia Outlets"
    text_x = logo_x + logo_width + 100
    text_y = height // 2 - 100
    
    # Draw text with white color
    draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255))

    # Save the image
    output_path = os.path.join(settings.STATIC_ROOT, 'img', 'social_share.png')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    image.save(output_path, 'PNG')