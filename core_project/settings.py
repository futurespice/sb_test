"""
Django settings for core_project project.
"""

import os
from pathlib import Path
from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(os.path.join(BASE_DIR, '.env'))

import sentry_sdk
sentry_dsn = os.environ.get('SENTRY_DSN')
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        # 100% sampling kills performance at 1000+ users (5-15ms overhead per request).
        # Default 0.1 = 10% sample rate. Override via env per environment.
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.1')),
        profiles_sample_rate=float(os.environ.get('SENTRY_PROFILES_SAMPLE_RATE', '0.1')),
    )

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured('SECRET_KEY environment variable is not set.')
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1')
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',  # FIXED: enables JWT logout
    'corsheaders',
    'django_filters',
    'drf_spectacular',

    # Local apps
    'apps.users',
    'apps.exams',
    'apps.proctoring',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core_project.wsgi.application'

# Database — PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'sb_db'),
        'USER': os.environ.get('DB_USER', 'sb_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', '12345678'),
        'HOST': os.environ.get('DB_HOST', 'db'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        # CONN_MAX_AGE=60: персистентные соединения.
        # WARN: при горизонтальном масштабировании (10+ реплик) кол-во соединений =
        # workers(4) * threads(2) * replicas * CONN_MAX_AGE → может исчерпать
        # PostgreSQL max_connections (default=100). Добавьте pgbouncer перед
        # масштабированием > 3 реплик или снизьте CONN_MAX_AGE=0.
        'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Asia/Bishkek'
USE_I18N = True
USE_TZ = True

# Static & Media files
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Primary key type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User model
AUTH_USER_MODEL = 'users.User'

# DRF
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day',
        'burst': '60/minute',
        'login': '10/minute',      # Custom scope for login endpoint
        'pdf_export': '10/minute', # PDF generation blocks a gunicorn worker ~2-5s
        'register': '5/hour',
        'exam_submit': '5/minute',
        'recording_upload': '10/minute',
    },
    # FIXED: global pagination — no more unbounded list responses
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# JWT — FIXED: blacklist enabled, short lived access token
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),  # was 1 day — security risk
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
}

# Swagger / OpenAPI
SPECTACULAR_SETTINGS = {
    'TITLE': 'Prüfung Proctor API',
    'DESCRIPTION': 'Backend API for Proctoring Exam Platform',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# CORS
CORS_ALLOW_ALL_ORIGINS = os.environ.get('CORS_ALLOW_ALL_ORIGINS', 'False').lower() in ('true', '1')
cors_origins_env = os.environ.get('CORS_ALLOWED_ORIGINS', '')
if cors_origins_env and not CORS_ALLOW_ALL_ORIGINS:
    CORS_ALLOWED_ORIGINS = cors_origins_env.split(',')

# ──────────────────────────────────────────────────────────────
# Security headers (production)
# ──────────────────────────────────────────────────────────────
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_HSTS_SECONDS = 31536000          # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ──────────────────────────────────────────────────────────────
# AI / External service timeouts
# ──────────────────────────────────────────────────────────────
# Читается в apps/exams/services.py через os.environ.
# Здесь документируем значение по умолчанию.
# GEMINI_REQUEST_TIMEOUT — макс. время ожидания AI-ответа (сек). Default=45.

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
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
        'apps': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
