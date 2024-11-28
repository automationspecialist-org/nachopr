from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.signals import task_postrun, task_prerun
from django.db import close_old_connections

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nachopr.settings')

app = Celery('nachopr')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Configure Celery to use Django-DB as result backend
app.conf.update(
    result_backend='django-db',
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    result_extended=True,
    task_store_errors_even_if_ignored=True,
)

@task_prerun.connect
def task_prerun_handler(task_id, task, *args, **kwargs):
    """Ensure task name is stored."""
    from django_celery_results.models import TaskResult
    TaskResult.objects.store_result(
        task_id=task_id,
        task_name=task.name,
        status='STARTED',
        content_type='application/json',
        content_encoding='utf-8'
    )

@task_postrun.connect
def close_db_connections(sender=None, task_id=None, task=None, args=None, kwargs=None,
                        retval=None, state=None, **kwds):
    """Close database connections after each task."""
    close_old_connections()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
