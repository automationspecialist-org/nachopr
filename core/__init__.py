from __future__ import absolute_import, unicode_literals

__all__ = ('celery_app',)

def get_celery_app():
    from .celery import app as celery_app
    return celery_app

celery_app = get_celery_app()