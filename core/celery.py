import os
from celery import Celery
from dotenv import load_dotenv
import logging
from datetime import timedelta
from celery.schedules import crontab

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

# Optimize memory and task management configurations
app.conf.update(
    # Memory management
    worker_max_memory_per_child=250000,  # Reduced to 250MB to prevent SIGKILL
    worker_max_tasks_per_child=25,       # Reduced to 25 tasks for more frequent recycling
    
    # Task execution
    task_time_limit=900,                 # 15 minute hard timeout
    task_soft_time_limit=800,            # ~13 minute soft timeout
    worker_prefetch_multiplier=1,        # Process one task at a time
    task_acks_late=True,                 # Acknowledge after completion
    
    # Concurrency and pooling
    worker_concurrency=2,                # Limit concurrent tasks
    worker_pool_restarts=True,           # Enable pool restarts
    
    # Task routing
    task_default_queue='default',        # Default queue name
    task_routes={
        'core.tasks.continuous_crawl_task': {'queue': 'crawl'},
        'core.tasks.process_journalist_task': {'queue': 'process'},
        'core.tasks.categorize_page_task': {'queue': 'categorize'},
    },
    
    # Error handling
    task_reject_on_worker_lost=True,     # Requeue tasks from lost workers
    task_remote_tracebacks=True,         # Include remote tracebacks in errors
)

# Load task modules from all registered Django app configs
app.config_from_object('django.conf:settings', namespace='CELERY')

# Update beat schedule with queue routing
app.conf.beat_schedule = {
    'continuous-crawl': {
        'task': 'continuous_crawl',
        'schedule': timedelta(minutes=15),
        'options': {'queue': 'crawl'}
    },
}

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

# Make sure tasks are imported when Celery starts
import core.tasks  # Add this import at the bottom