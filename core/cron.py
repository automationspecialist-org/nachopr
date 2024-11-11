import logging
from django.utils import timezone
from dotenv import load_dotenv
import requests
import os

load_dotenv()

logger = logging.getLogger(__name__)

def test_job():
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    message = f"[{timezone.now()}] NachoPR Test job executed."
    logger.info(message)
    requests.post(slack_webhook_url, json={"text": message})
