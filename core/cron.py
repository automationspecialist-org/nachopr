import logging
from django.utils import timezone
from dotenv import load_dotenv
import requests
import os
from core.tasks import crawl_news_sources_sync, process_all_journalists_sync
from core.models import Journalist, NewsPage

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
    newspage_count_before = NewsPage.objects.count()
    journalist_count_before = Journalist.objects.count()

    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    message = f"[{timezone.now()}] NachoPR crawl starting..."
    logger.info(message)
    requests.post(slack_webhook_url, json={"text": message})
    crawl_news_sources_sync(domain_limit=10, page_limit=1000)
    process_all_journalists_sync()

    newspage_count_after = NewsPage.objects.count()
    journalist_count_after = Journalist.objects.count()
    message = f"[{timezone.now()}] NachoPR crawl completed. {newspage_count_after - newspage_count_before} pages, {journalist_count_after - journalist_count_before} journalists added."
    logger.info(message)
    requests.post(slack_webhook_url, json={"text": message})
