"""Connexion et initialisation de la base de données."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL
from models import Base


def get_engine(db_url=None):
    return create_engine(db_url or DATABASE_URL, echo=False, future=True)


def _migrate_columns(engine):
    """Ajoute les colonnes manquantes sur une base SQLite existante."""
    migrations = [
        ("contribuables", "montant_declare", "REAL DEFAULT 0.0"),
        ("contribuables", "montant_paye", "REAL DEFAULT 0.0"),
        ("contribuables", "secteur", "VARCHAR(128)"),
        ("contribuables", "sous_secteur", "VARCHAR(128)"),
        ("contribuables", "cdi", "VARCHAR(64)"),
        ("import_history", "file_type", "VARCHAR(32)"),
        ("import_history", "status", "VARCHAR(32) DEFAULT 'traite'"),
        ("pending_imports", "status", "VARCHAR(32) DEFAULT 'en_attente'"),
        ("pending_imports", "import_phase", "INTEGER DEFAULT 1"),
        ("pending_imports", "analysis_json", "TEXT DEFAULT ''"),
        ("treatment_snapshots", "neants", "INTEGER DEFAULT 0"),
        ("treatment_snapshots", "sum_montant_recu", "REAL DEFAULT 0.0"),
        ("en_ligne_meta", "sectors_applied", "INTEGER DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in migrations:
            try:
                conn.execute(text(f"SELECT {col} FROM {table} LIMIT 1"))
            except Exception:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    conn.commit()
                except Exception:
                    pass


def init_db(db_url=None):
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    _migrate_columns(engine)
    return sessionmaker(bind=engine)


SessionLocal = init_db()


def bootstrap_app_data(session_factory=None):
    """Tâches au démarrage (cache TCD mensuel, etc.)."""
    factory = session_factory or SessionLocal
    db = factory()
    try:
        from services.consolidation import ensure_monthly_recu_cached
        ensure_monthly_recu_cached(db)
    finally:
        db.close()
