import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, '').strip().lower()
    if not value:
        return default
    if value in ('true', '1', 'yes', 'on'):
        return True
    if value in ('false', '0', 'no', 'off'):
        return False
    raise ImproperlyConfigured(f'{name} должен быть True или False, получено: {value!r}')


DEBUG = env_bool('DJANGO_DEBUG')

ALLOWED_HOSTS = [h for h in os.getenv('DJANGO_ALLOWED_HOSTS', '').split(',') if h]


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'bot',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

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

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'simple': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'}},
    'root': {'handlers': ['console'], 'level': os.getenv('LOG_LEVEL', 'INFO')},
}


# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')

# --- Транспортные компании ---
CARRIER_HTTP_TIMEOUT = float(os.getenv('CARRIER_HTTP_TIMEOUT', '25'))

# Деловые Линии: https://dev.dellin.ru
DELLIN_APPKEY = os.getenv('DELLIN_APPKEY', '')

# СДЭК: https://api-docs.cdek.ru
CDEK_API_URL = os.getenv('CDEK_API_URL') or 'https://api.cdek.ru/v2'
CDEK_CLIENT_ID = os.getenv('CDEK_CLIENT_ID', '')
CDEK_CLIENT_SECRET = os.getenv('CDEK_CLIENT_SECRET', '')

# DPD: https://www.dpd.ru/ru/integration (ws.dpd.ru — боевой, wstest.dpd.ru — тестовый)
DPD_API_URL = os.getenv('DPD_API_URL') or 'https://ws.dpd.ru/services'
DPD_CLIENT_NUMBER = os.getenv('DPD_CLIENT_NUMBER', '')
DPD_CLIENT_KEY = os.getenv('DPD_CLIENT_KEY', '')

# Байкал Сервис: https://www.baikalsr.ru/dev/api/ (тестовый контур — https://test-api.baikalsr.ru)
BAIKAL_API_URL = os.getenv('BAIKAL_API_URL') or 'https://api.baikalsr.ru'
BAIKAL_API_KEY = os.getenv('BAIKAL_API_KEY', '')

# ТК КИТ: https://tk-kit.ru/services/api
KIT_API_TOKEN = os.getenv('KIT_API_TOKEN', '')

# ПЭК: публичный калькулятор ключа не требует
