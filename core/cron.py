import logging
from django.utils import timezone
from dotenv import load_dotenv
import requests
import os
from core.tasks import crawl_news_sources_sync, process_all_journalists_sync

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
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    message = f"[{timezone.now()}] NachoPR crawl starting..."
    logger.info(message)
    requests.post(slack_webhook_url, json={"text": message})
    crawl_news_sources_sync(domain_limit=1, page_limit=1000)
    process_all_journalists_sync()
    logger.info(f"[{timezone.now()}] NachoPR crawl completed.")
    message = f"[{timezone.now()}] NachoPR crawl completed."
    requests.post(slack_webhook_url, json={"text": message})
