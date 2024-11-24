import os
from celery import Celery
from dotenv import load_dotenv
from celery.signals import celeryd_after_setup
import logging

load_dotenv()

# Configure Celery logging
logger = logging.getLogger('celery')
logger.setLevel(logging.DEBUG)

sas_policy_name = os.getenv('AZURE_QUEUE_POLICY_NAME')
sas_key = os.getenv('AZURE_QUEUE_POLICY_KEY')
namespace = os.getenv('AZURE_QUEUE_HOST')

# Set the default Django settings module BEFORE any Django imports
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nachopr.settings')

# Create the Celery app
app = Celery(
    "nacho_pr",
    broker_url=f"azureservicebus://{sas_policy_name}:{sas_key}@{namespace}",
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "wait_time_seconds": 5,
        "peek_lock_seconds": 60,
        "uamqp_keep_alive_interval": 30,
        "retry_total": 3,
        "retry_backoff_factor": 0.8,
        "retry_backoff_max": 120,
        "debug": True
    }
)

# Load task modules from all registered Django app configs
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

@celeryd_after_setup.connect
def setup_periodic_tasks(sender, instance, **kwargs):
    """Start continuous tasks when Celery worker starts"""
    # Import tasks here to avoid circular imports
    from core.tasks import continuous_crawl_task
    continuous_crawl_task.delay()