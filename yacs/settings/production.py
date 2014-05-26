from yacs.settings.base import *
import os
import json
import dj_database_url

DEBUG = False
TEMPLATE_DEBUG = DEBUG
COURSES_WARN_EXTRA_QUERIES = not DEBUG and not RUNNING_TESTS
STATICFILES_STORAGE = 'pipeline.storage.PipelineCachedStorage'

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
ALLOWED_HOSTS = ['*']

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
        'LOCATION': '127.0.0.1:11211',
        'VERSION': CACHE_VERSION,
    },
}

LOGGING['handlers']['file']['filename'] = '/www/yacs/logs/django.log'


def debug_toolbar_callback(request):
    return False

DEBUG_TOOLBAR_CONFIG = {
    'INTERCEPT_REDIRECTS': False,
    'SHOW_TOOLBAR_CALLBACK': debug_toolbar_callback,
    'HIDE_DJANGO_SQL': DEBUG
}

STATIC_URL = '/static/'

SECRET_KEY = os.environ['YACS_SECRET_KEY']

TEMPLATE_LOADERS = (
    ('django.template.loaders.cached.Loader', (
        'django.template.loaders.filesystem.Loader',
        'django.template.loaders.app_directories.Loader',
    )),
)

DEBUG_TOOLBAR_PANELS = (
    'debug_toolbar.panels.versions.VersionsPanel',
    'debug_toolbar.panels.timer.TimerPanel',
    'debug_toolbar.panels.settings.SettingsPanel',
    'debug_toolbar.panels.headers.HeadersPanel',
    'debug_toolbar.panels.request.RequestPanel',
    # 'debug_toolbar.panels.sql.SQLPanel',
    'debug_toolbar.panels.staticfiles.StaticFilesPanel',
    'debug_toolbar.panels.templates.TemplatesPanel',
    'debug_toolbar.panels.cache.CachePanel',
    'debug_toolbar.panels.signals.SignalsPanel',
    'debug_toolbar.panels.logging.LoggingPanel',
    'debug_toolbar.panels.redirects.RedirectsPanel',
)

#EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
#FROM_EMAIL = os.environ.get('YACS_EMAIL_FROM', 'robot@yacs.me')
#EMAIL_USE_TLS = os.environ.get('YACS_EMAIL_USE_TLS', 'yes').lower() in ['y', 'yes', 'true', 't', 'on']
#EMAIL_HOST = os.environ['YACS_EMAIL_HOST']
#EMAIL_USER = os.environ['YACS_EMAIL_USER']
#EMAIL_PASS = os.environ['YACS_EMAIL_PASS']
#EMAIL_PORT = int(os.environ.get('YACS_EMAIL_PORT', 587))
