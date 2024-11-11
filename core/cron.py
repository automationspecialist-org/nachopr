import logging
from django.utils import timezone
from dotenv import load_dotenv
import requests
import os

if 'AZURE' not in os.environ:
    load_dotenv()

logger = logging.getLogger(__name__)

def test_job():
    slack_webhook_url = "https://hooks.slack.com/services/T07M0BTS3A8/B07MLUL3QKS/eE3D3EK7BshbSS1feJ345hK"
    message = f"[{timezone.now()}] NachoPR Test job executed!"
    logger.info(message)
    response = requests.post(slack_webhook_url, json={"text": message})
    logger.info(f"Slack response: {response.status_code} {response.text}")
