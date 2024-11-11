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

if 'AZURE' in os.environ:
    print("Running on Azure")

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
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'whitenoise',
    'allauth',
    'allauth.account',
    'django_crontab',
    'django.contrib.humanize',
    'tailwind',
    'theme',
    #'django_cotton',
    'django_browser_reload',
    'core',
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
            ],
        },
    },
]

WSGI_APPLICATION = 'nachopr.wsgi.application'

ASGI_APPLICATION = 'nachopr.asgi.application'

ALLOWED_HOSTS = [
    '0.0.0.0', '127.0.0.1', 'nachopr.apps.innermaps.org',
    'nachoapp-ekewd4f3gdbwcxcu.eastus-01.azurewebsites.net',
    'nachopr.com'
]

# Add CSRF trusted origins for your domains
CSRF_TRUSTED_ORIGINS = [
    'https://nachopr.apps.innermaps.org',
    'https://nachoapp-ekewd4f3gdbwcxcu.eastus-01.azurewebsites.net',
    'https://nachopr.com'
]

# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DB_PATH = Path('/home/persistent/db.sqlite3') if os.environ.get('AZURE') else (
    Path('/persistent/db.sqlite3') if os.environ.get('CAPROVER') else BASE_DIR / 'db.sqlite3'
)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DB_PATH,
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

CRONJOBS = [
    ('0 * * * *', 'core.cron.crawl_job', '>> /tmp/cron.log 2>&1')
]
ALLOW_PARALLEL_RUNS = False
