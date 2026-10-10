"""
Django settings for config project.

Hardened for security and production readiness on Render.
"""

import os
import sys
from pathlib import Path
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────────
# 1 & 2. DEBUG & SECRET_KEY
# ─────────────────────────────────────────────────────────────
# DEBUG defaults to False in production (Render), True in local dev
DEBUG_ENV = os.environ.get('DJANGO_DEBUG')
if DEBUG_ENV is not None:
    DEBUG = DEBUG_ENV.lower() in ('true', '1', 't', 'yes')
else:
    DEBUG = 'RENDER' not in os.environ

# SECRET_KEY loaded from DJANGO_SECRET_KEY (or fallback SECRET_KEY env)
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY environment variable must be set in production.")
    SECRET_KEY = 'django-insecure-dev-only-fallback-key-do-not-use-in-production'

# ─────────────────────────────────────────────────────────────
# 3. ALLOWED_HOSTS & CSRF_TRUSTED_ORIGINS
# ─────────────────────────────────────────────────────────────
allowed_hosts_raw = os.environ.get('ALLOWED_HOSTS')
if allowed_hosts_raw:
    ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_raw.split(',') if h.strip()]
else:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1']

render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if render_host and render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_host)

# CSRF_TRUSTED_ORIGINS
csrf_origins_raw = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
if csrf_origins_raw:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_origins_raw.split(',') if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = []

if render_host:
    render_origin = f'https://{render_host}'
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Custom Apps
    'core',
    'accounts',
    'partners',
    'leads',
    'orders',
    'support',
    'portal_content',
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
    'core.middleware.PartnerApprovalMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

if 'DATABASE_URL' in os.environ:
    DATABASES['default'] = dj_database_url.config(
        conn_max_age=600,
        conn_health_checks=True,
    )


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

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

# Test runs only: the real password hashers (PBKDF2/Argon2) are deliberately
# slow, which dominates the suite runtime. Under `manage.py test` we fall back
# to MD5 hashing — passwords created/checked by tests never leave the test
# database, so this is safe and does not affect production hashers.
if 'test' in sys.argv:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Kolkata'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (Uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Tests run without `collectstatic`, so the manifest hash lookup would fail for
# any asset. Use the plain static storage under `manage.py test` only.
if 'test' in sys.argv:
    STORAGES['staticfiles']['BACKEND'] = (
        'django.contrib.staticfiles.storage.StaticFilesStorage'
    )

# During local development don't hard-fail on a stale/absent static manifest,
# so `runserver` keeps working after a new asset is added. Production builds
# run `collectstatic`, so this never affects the deployed manifest.
if DEBUG:
    STATICFILES_MANIFEST_STRICT = False


# ─────────────────────────────────────────────────────────────
# 6. Email Configuration (Brevo HTTPS API — SMTP is blocked on Render free tier)
# ─────────────────────────────────────────────────────────────
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'Partner Portal <no-reply@example.com>')
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# With BREVO_API_KEY set, all mail goes through Brevo's HTTPS API via
# core.email_backends.BrevoAPIEmailBackend instead of SMTP.
BREVO_API_KEY = os.environ.get('BREVO_API_KEY', '')
if BREVO_API_KEY:
    EMAIL_BACKEND = 'core.email_backends.BrevoAPIEmailBackend'
else:
    EMAIL_BACKEND = os.environ.get(
        'EMAIL_BACKEND',
        'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend'
    )

EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 't', 'yes')
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False').lower() in ('true', '1', 't', 'yes')
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')

# Password reset links are valid for 1 hour
PASSWORD_RESET_TIMEOUT = 3600


# ─────────────────────────────────────────────────────────────
# 7. Notification Service (Phase 2A)
# ─────────────────────────────────────────────────────────────
# Absolute base URL used in notification emails. Falls back to the Render
# external hostname, then to the local dev server.
SITE_URL = os.environ.get('SITE_URL', '').rstrip('/')
if not SITE_URL:
    SITE_URL = f'https://{render_host}' if render_host else 'http://localhost:8000'

# Upper bound on notification emails sent per user-facing day.
NOTIFY_EMAIL_DAILY_LIMIT = int(os.environ.get('NOTIFY_EMAIL_DAILY_LIMIT', '200'))

# WhatsApp delivery (Phase 2B): outbound text only, through the Twilio
# WhatsApp sandbox. The channel stays disabled until WHATSAPP_ENABLED is
# turned on and the Twilio settings below are provided.
WHATSAPP_ENABLED = os.environ.get('WHATSAPP_ENABLED', 'False').lower() in ('true', '1', 't', 'yes')
WHATSAPP_PROVIDER = os.environ.get('WHATSAPP_PROVIDER', 'twilio').strip() or 'twilio'
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '').strip()
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM', '').strip()

# Optional comma-separated list of E.164 destinations. When set, these
# are the ONLY numbers ever sent to — protects the sandbox free quota.
WHATSAPP_ALLOWED_NUMBERS = [
    number.strip()
    for number in os.environ.get('WHATSAPP_ALLOWED_NUMBERS', '').split(',')
    if number.strip()
]

# Upper bound on WhatsApp messages sent per day (<= 0 means unlimited).
NOTIFY_WHATSAPP_DAILY_LIMIT = int(os.environ.get('NOTIFY_WHATSAPP_DAILY_LIMIT', '50'))


# ─────────────────────────────────────────────────────────────
# 9. OCR for KYC documents (Phase 3)
# ─────────────────────────────────────────────────────────────
# OCR stays completely off until OCR_ENABLED is turned on and an API key is
# provided. Uploads still work when disabled — they are just marked
# "skipped" so a reviewer can key in the details manually.
OCR_ENABLED = os.environ.get('OCR_ENABLED', 'False').lower() in ('true', '1', 't', 'yes')
OCR_PROVIDER = os.environ.get('OCR_PROVIDER', 'ocrspace').strip() or 'ocrspace'
OCRSPACE_API_KEY = os.environ.get('OCRSPACE_API_KEY', '').strip()

# Upper bound on OCR calls per day (<= 0 means unlimited).
OCR_DAILY_LIMIT = int(os.environ.get('OCR_DAILY_LIMIT', '100'))

# Files larger than this are downscaled client-side (images, via Pillow)
# instead of being uploaded verbatim to the OCR provider.
OCR_MAX_BYTES = int(os.environ.get('OCR_MAX_BYTES', str(1024 * 1024)))


# ─────────────────────────────────────────────────────────────
# 4. Production Security Hardening
# ─────────────────────────────────────────────────────────────
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1', 't', 'yes')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', 3600))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True


# ─────────────────────────────────────────────────────────────
# 8. Console Logging Configuration
# ─────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}] {message}',
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
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

from django.contrib.messages import constants as messages
MESSAGE_TAGS = {messages.ERROR: 'danger'}
