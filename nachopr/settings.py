"""
Django settings for nachopr project.

Generated by 'django-admin startproject' using Django 5.1.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.1/ref/settings/
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import sentry_sdk

load_dotenv()

if 'AZURE' in os.environ:
    PROD = True
    print("Running on Azure")
else:
    PROD = False

if PROD:
    sentry_sdk.init(
        dsn="https://88a3438a82d94bd107685fc631757884@o4508348122464256.ingest.us.sentry.io/4508348123709441",
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
        _experiments={
            # Set continuous_profiling_auto_start to True
            # to automatically start the profiler on when
            # possible.
            "continuous_profiling_auto_start": True,
        },
    )

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-tawj(49n0_32tx5l%&bufs^)!n1^-(%_$9bm^%*p4maxiwa#%y'

# SECURITY WARNING: don't run with debug turned on in production!
if 'AZURE' in os.environ or 'CAPROVER' in os.environ:
    DEBUG = False
else:
    DEBUG = True


# Application definition

INSTALLED_APPS = [
    'core',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'whitenoise',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'django_crontab',
    'django.contrib.humanize',
    'tailwind',
    'theme',
    #'django_cotton',
    'django_browser_reload',
    'crispy_forms',
    'crispy_tailwind',
    'allauth_theme',
    'algoliasearch_django',
    'djstripe',
    'pgvector',
    'django_celery_results',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "django_browser_reload.middleware.BrowserReloadMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = 'nachopr.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'allauth_theme.context_processors.welcome_text',
            ],
        },
    },
]

WSGI_APPLICATION = 'nachopr.wsgi.application'

ASGI_APPLICATION = 'nachopr.asgi.application'

class AzureInternalNetworkValidator:
    def __contains__(self, host):
        if not host.startswith('169.254.'):
            return False
        try:
            # Split the IP and verify the last two octets
            parts = host.split('.')
            if len(parts) != 4:
                return False
            return (parts[0] == '169' and 
                   parts[1] == '254' and 
                   0 <= int(parts[2]) <= 255 and 
                   0 <= int(parts[3]) <= 255)
        except (ValueError, IndexError):
            return False

ALLOWED_HOSTS = [
    '0.0.0.0', 
    '127.0.0.1', 
    'nachopr.apps.innermaps.org',
    'nachoapp-ekewd4f3gdbwcxcu.eastus-01.azurewebsites.net',
    'nachopr.com',
    AzureInternalNetworkValidator(),
]

# Add CSRF trusted origins for your domains
CSRF_TRUSTED_ORIGINS = [
    'https://nachopr.apps.innermaps.org',
    'https://nachoapp-ekewd4f3gdbwcxcu.eastus-01.azurewebsites.net',
    'https://nachopr.com'
]

# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

# Database settings
if PROD:
    # Use Azure Database for PostgreSQL in production
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('PGDATABASE'),
            'USER': os.environ.get('PGUSER'),
            'PASSWORD': os.environ.get('PGPASSWORD'),
            'HOST': os.environ.get('PGHOST'),
            'PORT': os.environ.get('PGPORT'),
            'OPTIONS': {
                'sslmode': 'require',  # Azure PostgreSQL requires SSL
            },
        }
    }
else:
    # Use local PostgreSQL in development
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'postgres',  # default database name
            'USER': 'postgres',  # default postgres user
            'PASSWORD': 'postgres',  # change this to your local password
            'HOST': 'localhost',
            'PORT': '5434',
        }
    }


STATIC_ROOT = BASE_DIR / 'static'
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]




# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Add these settings for whitenoise
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

TAILWIND_APP_NAME = 'theme'

INTERNAL_IPS = [
    "127.0.0.1",
]

#CRON_LOG_FILE = '/persistent/cron.log'

DJSTRIPE_FOREIGN_KEY_TO_FIELD = 'djstripe_id'
DJSTRIPE_WEBHOOK_VALIDATION='retrieve_event'
POLAR_SERVER = os.environ.get("POLAR_SERVER")

if POLAR_SERVER == "sandbox":
    POLAR_ACCESS_TOKEN = os.environ.get("POLAR_TEST_ACCESS_TOKEN")
    POLAR_ORGANIZATION_ID = os.environ.get("POLAR_TEST_ORGANIZATION_ID")
else:
    POLAR_ACCESS_TOKEN = os.environ.get("POLAR_ACCESS_TOKEN")
    POLAR_ORGANIZATION_ID = os.environ.get("POLAR_ORGANIZATION_ID")
ALGOLIA = {
  'APPLICATION_ID': 'SXW045HL4C',
  'API_KEY': 'b03fb3d30fde244903b39447833aa615',
  'INDEX_PREFIX': '_dev' if not PROD else '_prod'
}

SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"
CRISPY_TEMPLATE_PACK = "tailwind"

DAT_WELCOME_TITLE = 'NachoPR'  # title
DAT_WELCOME_TITLE_MOBILE = 'NachoPR'  # mobile title
DAT_WELCOME_TEXT = 'NachoPR is a platform for finding relevant journalists for your PR campaigns.'  # text for your project
DAT_GOOGLE_ENABLE_ONETAP_LOGIN = True  # decide if you want to show the google one tap login
DAT_GOOGLE_CLIENT_ID = ''  # google client id , e.g. XXXXXXXXXX39-62ckbbeXXXXXXXXXXXXXXXXXXXXXm1.apps.googleusercontent.com
DAT_BASE_URL = ''  # e.g. http://localhost:8000
DAT_TOS_MESSAGE = 'By registering, you agree to our <a href="/terms-of-service/">Terms of Service</a> and <a href="/privacy-policy/">Privacy Policy.</a>'  # optional



if PROD:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.memcached.PyMemcacheCache",
            "LOCATION": "unix:/tmp/memcached.sock",  # Using Unix socket for better performance
            "OPTIONS": {
                "no_delay": True,
                "ignore_exc": True,
                "max_pool_size": 4,
                "use_pooling": True,
            }
        }
    }

AUTH_USER_MODEL = 'core.CustomUser'

LOGIN_REDIRECT_URL = '/app/'
ACCOUNT_LOGIN_BY_CODE_ENABLED = True



ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}



#CRONJOBS = [
    #('*/20 * * * *', 'core.cron.crawl_job', '>> /tmp/cron.log 2>&1'),
    #('*/30 * * * *', 'core.cron.categorize_job', '>> /tmp/cron_categorize.log 2>&1'),
    #('*/30 * * * *', 'core.cron.process_journalist_profiles_job', '>> /tmp/cron_process_journalist_profiles.log 2>&1'),
    #('*/30 * * * *', 'core.cron.guess_emails_job', '>> /tmp/cron_guess_emails.log 2>&1'),
    #('*/30 * * * *', 'core.cron.clean_db_job', '>> /tmp/cron_clean_db.log 2>&1'),
    #('*/30 * * * *', 'core.cron.algolia_reindex_job', '>> /tmp/cron_algolia_reindex.log 2>&1'),
    #('*/30 * * * *', 'core.cron.generate_social_share_image_job', '>> /tmp/cron_generate_social_share_image.log 2>&1'),
    #('*/30 * * * *', 'core.cron.find_digital_pr_examples_job', '>> /tmp/cron_find_digital_pr_examples.log 2>&1'),
    #('*/30 * * * *', 'core.cron.sync_journalist_categories_job', '>> /tmp/cron_sync_journalist_categories.log 2>&1'),
    #('*/15 * * * *', 'core.cron.update_embeddings_job', '>> /tmp/cron_update_embeddings.log 2>&1'),
#]

EMAIL_HOST_USER = 'support@updates.nachopr.com' 
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.resend.com'
EMAIL_PORT = 587
EMAIL_HOST_USER = 'resend'
EMAIL_HOST_PASSWORD = os.environ.get('RESEND_API_KEY')
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = 'NachoPR <support@updates.nachopr.com>'
SERVER_EMAIL = 'NachoPR <support@updates.nachopr.com>' 


# Add Celery settings
CELERY_BROKER_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_CACHE_BACKEND = 'django-cache'
CELERY_RESULT_EXTENDED = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 900  # 15 minutes
CELERY_TASK_SOFT_TIME_LIMIT = 800  # ~13 minutes
CELERY_WORKER_MAX_MEMORY_PER_CHILD = 250000  # 250MB
CELERY_WORKER_MAX_TASKS_PER_CHILD = 25
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_TASK_STORE_ERRORS_EVEN_IF_IGNORED = True
CELERY_TASK_STORE_SUCCESS = True

# Task queues configuration
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_TASK_QUEUES = {
    'default': {},
    'crawl': {},
    'process': {},
    'categorize': {},
}

CELERY_TASK_ROUTES = {
    'core.tasks.continuous_crawl_task': {'queue': 'crawl'},
    'core.tasks.crawl_single_source_task': {'queue': 'crawl'},
    'core.tasks.crawl_single_page_task': {'queue': 'crawl'},
    'core.tasks.process_journalist_task': {'queue': 'process'},
    'core.tasks.process_journalists_task': {'queue': 'process'},
    'core.tasks.categorize_page_task': {'queue': 'categorize'},
    'core.tasks.categorize_pages_task': {'queue': 'categorize'},
}

CELERY_BEAT_SCHEDULE = {
    'continuous-crawl': {
        'task': 'nachopr.continuous_crawl',
        'schedule': 60.0,  # Run every minute
        'options': {
            'queue': 'crawl',
            'acks_late': True,  # Don't ack the task until it completes
            'max_concurrency': 1  # Only allow one instance at a time
        }
    },
    'process-journalists': {
        'task': 'process_journalists_task',
        'schedule': 1800.0,  # Run every 30 minutes
    },
    'categorize-pages': {
        'task': 'categorize_pages_task',
        'schedule': 1800.0,  # Run every 30 minutes
    },
    'update-page-embeddings': {
        'task': 'update_page_embeddings_task',
        'schedule': 900.0,  # Run every 15 minutes
    },
    'update-journalist-embeddings': {
        'task': 'update_journalist_embeddings_task',
        'schedule': 1800.0,  # Run every 30 minutes
    },
}

TYPESENSE_API_KEY='local_only_key'
TYPESENSE_URL='http://localhost:8108'