import os
from celery import Celery
from dotenv import load_dotenv
import logging
from datetime import timedelta

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

# Add memory and task management configurations
app.conf.update(
    worker_max_memory_per_child=350000,  # 350MB memory limit
    worker_max_tasks_per_child=50,       # Restart worker after 50 tasks
    task_time_limit=1800,                # 30 minute timeout
    task_soft_time_limit=1500,           # Soft timeout 25 minutes
    worker_prefetch_multiplier=1,        # Process one task at a time
    task_acks_late=True                  # Acknowledge tasks after completion
)

# Load task modules from all registered Django app configs
app.config_from_object('django.conf:settings', namespace='CELERY')

# Configure the Celery beat schedule
app.conf.beat_schedule = {
    'continuous-crawl': {
        'task': 'core.tasks.continuous_crawl_task',
        'schedule': timedelta(minutes=5),
        'options': {'queue': 'celery'}
    },
}

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')