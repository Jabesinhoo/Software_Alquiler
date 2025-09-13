"""
Django settings for proyecto_alquiler project.
"""
from decouple import config
from pathlib import Path
import os
from dotenv import load_dotenv
from celery.schedules import crontab

# Load environment variables
load_dotenv()

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Security
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')

DEBUG = config('DEBUG', default=False, cast=bool)
USE_LOCAL = config('USE_LOCAL', default=True, cast=bool)

# CONFIGURACIÓN DE HOSTS SEGÚN ENTORNO
if USE_LOCAL:
    # Desarrollo local - usar siempre HTTP
    ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
    DEBUG = True  # Forzar DEBUG=True en desarrollo local
elif DEBUG:
    ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
else:
    ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='').split(',')

# Apps
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'alquiler',
    'django_crontab',
    'rest_framework',
    'django_ckeditor_5',
    'django.contrib.humanize',
    'django_select2',
    'corsheaders',
    'crispy_forms',
    'crispy_bootstrap5',
    'widget_tweaks',

]


LOGIN_URL = '/guanabanazo/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/guanabanazo/'

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

SELECT2_CACHE_BACKEND = 'default'
CELERY_BEAT_SCHEDULE = {
    'cancelar_reservas_vencidas': {
        'task': 'alquiler.tasks.cancelar_reservas_vencidas',
        'schedule': crontab(hour=3, minute=0),
    },
}

# CONFIGURACIÓN DE SEGURIDAD SOLO PARA PRODUCCIÓN REAL
if not DEBUG and not USE_LOCAL:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
else:
    # Desarrollo: NO forzar HTTPS
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_SSL_REDIRECT = False

CKEDITOR_UPLOAD_PATH = "uploads/"
CKEDITOR_CONFIGS = {
    'default': {
        'toolbar': 'Custom',
        'toolbar_Custom': [
            ['Bold', 'Italic', 'Underline'],
            ['NumberedList', 'BulletedList', '-', 'Outdent', 'Indent', '-', 'JustifyLeft', 'JustifyCenter', 'JustifyRight', 'JustifyBlock'],
            ['Link', 'Unlink'],
            ['RemoveFormat', 'Source']
        ],
        'height': 300,
        'width': '100%',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

CRONJOBS = [
    ('*/5 * * * *', 'myapp.cron.my_scheduled_job'),
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
}

# Middleware - Configuración diferente según entorno
if USE_LOCAL or DEBUG:
    # Desarrollo: SIN WhiteNoise para evitar conflictos
    MIDDLEWARE = [
        'django.middleware.security.SecurityMiddleware',
        'django.contrib.sessions.middleware.SessionMiddleware',
        'corsheaders.middleware.CorsMiddleware',
        'django.middleware.common.CommonMiddleware',
        'django.middleware.csrf.CsrfViewMiddleware',
        'alquiler.middleware.AuditMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'django.contrib.messages.middleware.MessageMiddleware',
        'django.middleware.clickjacking.XFrameOptionsMiddleware',
    ]
else:
    # Producción: CON WhiteNoise
    MIDDLEWARE = [
        'django.middleware.security.SecurityMiddleware',
        'whitenoise.middleware.WhiteNoiseMiddleware',
        'django.contrib.sessions.middleware.SessionMiddleware',
        'corsheaders.middleware.CorsMiddleware',
        'django.middleware.common.CommonMiddleware',
        'django.middleware.csrf.CsrfViewMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'django.contrib.messages.middleware.MessageMiddleware',
        'django.middleware.clickjacking.XFrameOptionsMiddleware',
    ]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

ROOT_URLCONF = 'proyecto_alquiler.urls'

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'alquiler.context_processors.empresa_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'proyecto_alquiler.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT'),
    }
}



# Authentication
AUTH_USER_MODEL = 'alquiler.Usuario'

# File upload settings
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB.
FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB
FILE_UPLOAD_ALLOWED_MIME_TYPES = ['image/jpeg', 'image/png', 'image/gif']

# Email configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
EMAIL_REPLY_TO = os.getenv('EMAIL_REPLY_TO')

# Internationalization
LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/Bogota'  
USE_TZ = True  
USE_I18N = True
USE_L10N = True


# ===============================
# CONFIGURACIÓN DE ARCHIVOS ESTÁTICOS Y MEDIA
# ===============================

# URLs para archivos estáticos y media
STATIC_URL = '/static/'
MEDIA_URL = '/media/'

if DEBUG or USE_LOCAL:
    STATICFILES_DIRS = [
        BASE_DIR / 'alquiler' / 'static',
    ]
    STATIC_ROOT = BASE_DIR / 'staticfiles' # <--- Define una ruta para desarrollo
    MEDIA_ROOT = BASE_DIR / 'alquiler' / 'static' / 'media'
else:
    STATICFILES_DIRS = [
        BASE_DIR / 'alquiler' / 'static',
    ]
    STATIC_ROOT = BASE_DIR / 'staticfiles'
    MEDIA_ROOT = BASE_DIR / 'media'
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


CKEDITOR_UPLOAD_PATH = "uploads/"

# Default primary key
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Cron jobs
CRONJOBS = [
    ('0 8 * * *', 'alquiler.views.tareas_cron.enviar_alertas_vencimiento'),
]

# Logging solo para producción
if not DEBUG and not USE_LOCAL:
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'file': {
                'level': 'INFO',
                'class': 'logging.FileHandler',
                'filename': BASE_DIR / 'logs' / 'django.log',
            },
        },
        'loggers': {
            'django': {
                'handlers': ['file'],
                'level': 'INFO',
                'propagate': True,
            },
        },
    }