import logging
from django.db import connection
from django.utils import timezone
from dotenv import load_dotenv
import requests
import os
from core.tasks import categorize_news_pages_with_gpt, crawl_news_sources_sync, create_social_sharing_image, find_digital_pr_examples, guess_journalist_email_addresses, process_all_journalists_sync, process_journalist_descriptions_sync
from core.models import Journalist, NewsPage, NewsSource, sync_journalist_categories
from django.conf import settings
from django.core.management import call_command


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
    crawl_news_sources_sync(domain_limit=1, page_limit=2000, max_concurrent_tasks=20)
    process_all_journalists_sync(limit=1000)

    newspage_count_after = NewsPage.objects.count()
    journalist_count_after = Journalist.objects.count()
    message = f"[{timezone.now()}] NachoPR crawl completed. {newspage_count_after - newspage_count_before} pages, {journalist_count_after - journalist_count_before} journalists added."
    logger.info(message)
    requests.post(slack_webhook_url, json={"text": message})


def send_slack_alert(message: str):
    """
    Send alert to Slack webhook if configured
    """
    try:
        if hasattr(settings, 'SLACK_WEBHOOK_URL') and settings.SLACK_WEBHOOK_URL:
            payload = {
                "text": f"🚨 Database Alert: {message}"
            }
            requests.post(settings.SLACK_WEBHOOK_URL, json=payload)
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {str(e)}")


def check_database_integrity():
    """
    Run SQLite database integrity check.
    Returns True if database is healthy, False otherwise.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA integrity_check;')
            result = cursor.fetchone()[0]
            
            if result == 'ok':
                logger.info("Database integrity check passed")
                return True
            else:
                error_msg = f"Database integrity check failed: {result}"
                logger.error(error_msg)
                send_slack_alert(error_msg)
                return False
    except Exception as e:
        error_msg = f"Error running database integrity check: {str(e)}"
        logger.error(error_msg)
        send_slack_alert(error_msg)
        return False
    

def categorize_job():
    newspage_with_categories_count_before = NewsPage.objects.filter(categories__isnull=False).count()
    categorize_news_pages_with_gpt()
    newspage_with_categories_count_after = NewsPage.objects.filter(categories__isnull=False).count()
    message = f"[{timezone.now()}] NachoPR categorize completed. {newspage_with_categories_count_after - newspage_with_categories_count_before} pages categorized."
    logger.info(message)
    requests.post(settings.SLACK_WEBHOOK_URL, json={"text": message})


def process_journalist_profiles_job():
    process_journalist_descriptions_sync(limit=1000)


def guess_emails_job():
    guess_journalist_email_addresses(limit=100_000)


def generate_social_share_image_job():
    create_social_sharing_image()
    call_command('collectstatic', '--noinput')
    

def find_digital_pr_examples_job():
    find_digital_pr_examples()


def sync_journalist_categories_job():
    """Bulk sync categories for all journalists"""
    for journalist in Journalist.objects.all():
        journalist.sync_categories()
    
    for source in NewsSource.objects.all():
        source.sync_categories()
