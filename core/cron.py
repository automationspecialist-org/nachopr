import logging
import time
from django.utils import timezone
from dotenv import load_dotenv
import requests
import os
from core.tasks import crawl_news_sources_sync
import psutil

if 'AZURE' not in os.environ:
    load_dotenv()

logger = logging.getLogger(__name__)

def test_job():
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    message = f"[{timezone.now()}] NachoPR Test job executed! (used env var)"
    logger.info(message)
    response = requests.post(slack_webhook_url, json={"text": message})
    logger.info(f"Slack response: {response.status_code} {response.text}")


def crawl_job():
    # Get the current process
    process = psutil.Process(os.getpid())
    
    domain_limit = 10
    page_limit = 1000
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    
    # Initial memory usage
    initial_memory = process.memory_info().rss / 1024 / 1024  # Convert to MB
    max_memory = initial_memory
    max_cpu = 0.0
    
    message = f"[{timezone.now()}] NachoPR crawl starting..."
    logger.info(message)
    requests.post(slack_webhook_url, json={"text": message})
    
    start_time = time.time()
    
    try:
        pages_added, journalists_added = crawl_news_sources_sync(domain_limit=domain_limit, page_limit=page_limit)
        
        # Track max resource usage during execution
        max_memory = max(max_memory, process.memory_info().rss / 1024 / 1024)
        max_cpu = max(max_cpu, process.cpu_percent())
        
        message = (
            f"[{timezone.now()}] NachoPR crawl completed.\n"
            f"Crawled {domain_limit} domains in {time.time() - start_time:.2f} seconds.\n"
            f"{pages_added} pages added. {journalists_added} journalists added.\n"
            f"Peak Memory Usage: {max_memory:.1f}MB\n"
            f"Peak CPU Usage: {max_cpu:.1f}%"
        )
    except Exception as e:
        message = f"[{timezone.now()}] NachoPR crawl failed: {str(e)}"
        raise
    finally:
        logger.info(message)
        requests.post(slack_webhook_url, json={"text": message})
