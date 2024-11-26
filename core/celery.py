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

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nachopr.settings')

# Create the Celery app
app = Celery("nacho_pr")

# Load task modules from all registered Django app configs
app.config_from_object('django.conf:settings', namespace='CELERY')

# Optimize memory and task management configurations
app.conf.update(
    # Broker and Backend settings
    broker_url=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    result_backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    
    # Memory management
    worker_max_memory_per_child=1000000,  # 1GB memory limit per worker
    worker_max_tasks_per_child=25,
    worker_prefetch_multiplier=1,  # Don't prefetch tasks

    
    # Task execution
    task_time_limit=900,                 # 15 minute hard timeout
    task_soft_time_limit=800,            # ~13 minute soft timeout
    task_acks_late=True,
    
    # Concurrency and pooling
    worker_concurrency=2,
    worker_pool_restarts=True,
    
    # Task routing
    task_default_queue='default',
    task_routes={
        'core.tasks.continuous_crawl_task': {'queue': 'crawl'},
        'core.tasks.process_journalist_task': {'queue': 'process'},
        'core.tasks.categorize_page_task': {'queue': 'categorize'},
    },
    
    # Error handling
    task_reject_on_worker_lost=True,
    task_remote_tracebacks=True,
)

# Update beat schedule with queue routing
app.conf.beat_schedule = {
    'continuous-crawl': {
        'task': 'core.tasks.continuous_crawl_task',
        'schedule': timedelta(minutes=15),
        'options': {'queue': 'crawl'}
    },
}

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()
@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
