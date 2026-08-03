"""Configuration centralisée — TaxStats AI / Fiscal CRIC EXT."""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Base relationnelle (source de vérité)
DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(BASE_DIR, "data.db")}')

# Dossier temporaire : fichiers en attente d'import uniquement (supprimés après traitement)
UPLOAD_DIR = os.environ.get('UPLOAD_DIR', os.path.join(BASE_DIR, 'uploads'))

# Auth (à externaliser en production)
SECRET_KEY = os.environ.get('APP_SECRET', 'change-me')
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS', 'admin')

ORGANISATION_NAME = os.environ.get('ORGANISATION_NAME', 'CRIC EXT')
ORGANISATION_SHORT = os.environ.get('ORGANISATION_SHORT', 'CRIC EXT')
