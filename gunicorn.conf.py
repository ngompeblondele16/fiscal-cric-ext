"""Configuration Gunicorn — production (Render, etc.)."""
import multiprocessing
import os

# Render injecte PORT ; consolidation Excel peut dépasser 30 s (défaut Gunicorn).
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '600'))
graceful_timeout = 30
keepalive = 5

# SQLite : un seul worker évite les verrous « database is locked ».
workers = int(os.environ.get('WEB_CONCURRENCY', '1'))
threads = int(os.environ.get('GUNICORN_THREADS', '2'))

worker_class = 'gthread'
preload_app = False

accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('LOG_LEVEL', 'info')
