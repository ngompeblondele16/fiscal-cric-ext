"""Configuration centralisée — TaxStats AI / Fiscal CRIC EXT."""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Données persistantes (Render : disque monté sur /var/data)
DATA_DIR = os.environ.get('DATA_DIR', BASE_DIR)


def _normalize_database_url(url):
    """Render PostgreSQL expose parfois postgres:// — SQLAlchemy attend postgresql://."""
    if url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url


_default_db_path = os.path.join(DATA_DIR, 'data.db').replace('\\', '/')
_default_db_url = f'sqlite:///{_default_db_path}'

# Base relationnelle (source de vérité)
DATABASE_URL = _normalize_database_url(
    os.environ.get('DATABASE_URL', _default_db_url)
)

# Dossier temporaire : fichiers en attente d'import uniquement (supprimés après traitement)
UPLOAD_DIR = os.environ.get('UPLOAD_DIR', os.path.join(DATA_DIR, 'uploads'))

# Auth (à externaliser en production)
SECRET_KEY = os.environ.get('APP_SECRET', 'change-me')
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS', 'admin')

ORGANISATION_NAME = os.environ.get('ORGANISATION_NAME', 'CRIC EXT')
ORGANISATION_SHORT = os.environ.get('ORGANISATION_SHORT', 'CRIC EXT')
