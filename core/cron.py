import logging
import time
from django.utils import timezone
from dotenv import load_dotenv
import requests
import os
from core.tasks import crawl_news_sources_sync

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
    domain_limit = 10
    page_limit = 1000
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    message = f"[{timezone.now()}] NachoPR crawl starting..."
    logger.info(message)
    requests.post(slack_webhook_url, json={"text": message})
    start_time = time.time()
    pages_added, journalists_added = crawl_news_sources_sync(domain_limit=domain_limit, page_limit=page_limit)
    message = f"[{timezone.now()}] NachoPR crawl completed. Crawled {domain_limit} domains in {time.time() - start_time:.2f} seconds. {pages_added} pages added. {journalists_added} journalists added."
    logger.info(message)
    requests.post(slack_webhook_url, json={"text": message})
