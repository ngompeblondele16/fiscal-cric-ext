"""Modèles SQLAlchemy — structure des données persistées."""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Contribuable(Base):
    __tablename__ = 'contribuables'
    id = Column(Integer, primary_key=True)
    niu = Column(String(32), unique=True, index=True, nullable=False)
    raison = Column(String(255))
    etat = Column(Integer, default=0)
    montant_attendu = Column(Float, default=0.0)
    montant_declare = Column(Float, default=0.0)
    montant_paye = Column(Float, default=0.0)
    secteur = Column(String(128))
    sous_secteur = Column(String(128))
    cdi = Column(String(64))
    declarations = relationship('Declaration', back_populates='contribuable')
    paiements = relationship('Paiement', back_populates='contribuable')


class Declaration(Base):
    __tablename__ = 'declarations'
    id = Column(Integer, primary_key=True)
    niu = Column(String(32), ForeignKey('contribuables.niu'))
    raison = Column(String(255))
    secteur = Column(String(128))
    sous_secteur = Column(String(128))
    cdi = Column(String(64))
    somme_totale_declaree = Column(Float, default=0.0)
    date_import = Column(DateTime, default=datetime.utcnow)
    contribuable = relationship('Contribuable', back_populates='declarations')


class Paiement(Base):
    __tablename__ = 'paiements'
    id = Column(Integer, primary_key=True)
    niu = Column(String(32), ForeignKey('contribuables.niu'))
    montant_paye = Column(Float, default=0.0)
    date_paiement = Column(String(64))
    contribuable = relationship('Contribuable', back_populates='paiements')


class ImportHistory(Base):
    __tablename__ = 'import_history'
    id = Column(Integer, primary_key=True)
    filename = Column(String(255))
    user = Column(String(64))
    date_import = Column(DateTime, default=datetime.utcnow)
    nb_lignes = Column(Integer, default=0)
    file_type = Column(String(32))
    status = Column(String(32), default='traite')
    errors = Column(Text)


class StateHistory(Base):
    __tablename__ = 'state_history'
    id = Column(Integer, primary_key=True)
    niu = Column(String(32))
    old_state = Column(Integer)
    new_state = Column(Integer)
    date = Column(DateTime, default=datetime.utcnow)


class PendingImport(Base):
    __tablename__ = 'pending_imports'
    id = Column(Integer, primary_key=True)
    filename = Column(String(255))
    filepath = Column(String(512))
    user = Column(String(64))
    date_added = Column(DateTime, default=datetime.utcnow)
    file_type = Column(String(32))
    import_phase = Column(Integer, default=1)
    nb_rows = Column(Integer, default=0)
    status = Column(String(32), default='en_attente')
    errors = Column(Text, default='')
    analysis_json = Column(Text, default='')


class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    message = Column(Text, nullable=False)
    level = Column(String(16), default='info')
    source = Column(String(64), default='system')
    is_read = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ConsolidatedLine(Base):
    """Résultat TCD Phase 1 — une ligne par NIU."""
    __tablename__ = 'consolidated_lines'
    niu = Column(String(32), primary_key=True)
    raison = Column(String(255))
    montant_declare = Column(Float, default=0.0)
    montant_paye = Column(Float, nullable=True)
    etat = Column(Integer, nullable=True)
    etat_display = Column(String(64))
    updated_at = Column(DateTime, default=datetime.utcnow)


class ConsolidationMeta(Base):
    """Métadonnées du dernier traitement Phase 1 (contrôles KPI)."""
    __tablename__ = 'consolidation_meta'
    id = Column(Integer, primary_key=True)
    date_run = Column(DateTime, default=datetime.utcnow)
    user = Column(String(64))
    controls_json = Column(Text)


class SecteurCimeCatalog(Base):
    """Libellés Secteur CIME autorisés — issus du fichier secteurs (RECHERCHEV étape 5)."""
    __tablename__ = 'secteur_cime_catalog'
    id = Column(Integer, primary_key=True)
    label = Column(String(128), unique=True, nullable=False)
    sort_order = Column(Integer, default=0)


class SousSecteurRef(Base):
    """Référence NIU → sous-secteur issue du fichier secteurs (dénominateur TCD Taille)."""
    __tablename__ = 'sous_secteur_ref'
    niu = Column(String(32), primary_key=True)
    sous_secteur = Column(String(128), nullable=False, index=True)
    secteur_cime = Column(String(128))


class MonthlyRecu(Base):
    """TCD mensuel : montants reçus par (année, mois) selon date_creation."""
    __tablename__ = 'monthly_recu'
    year = Column(Integer, primary_key=True)
    month = Column(Integer, primary_key=True)
    montant = Column(Float, default=0.0)


class SectorielImportLine(Base):
    """Lignes brutes importées Phase 1 (audit, graphiques, recalcul TCD)."""
    __tablename__ = 'sectoriel_import_lines'
    id = Column(Integer, primary_key=True)
    niu = Column(String(32), index=True, nullable=False)
    raison = Column(String(255))
    montant_declare = Column(Float, default=0.0)
    montant_recu = Column(Float, nullable=True)
    etat = Column(Integer, nullable=True)
    etat_display = Column(String(64))
    date_creation_year = Column(Integer, nullable=True, index=True)
    date_creation_month = Column(Integer, nullable=True, index=True)
    source_filename = Column(String(255))
    imported_at = Column(DateTime, default=datetime.utcnow)


class EnLigneMeta(Base):
    """En-têtes du fichier en ligne (modèle NHR) — une entrée par traitement phase 2."""
    __tablename__ = 'en_ligne_meta'
    id = Column(Integer, primary_key=True)
    headers_json = Column(Text, nullable=False)
    source_filename = Column(String(255))
    sectors_applied = Column(Integer, default=0)
    date_run = Column(DateTime, default=datetime.utcnow)


class EnLigneLine(Base):
    """Lignes brutes du fichier en ligne (valeurs originales, ordre conservé)."""
    __tablename__ = 'en_ligne_lines'
    id = Column(Integer, primary_key=True)
    row_order = Column(Integer, index=True, nullable=False)
    niu = Column(String(32), index=True, nullable=False)
    values_json = Column(Text, nullable=False)


class FiscalTreatment(Base):
    """Session de traitement fiscal guidée (wizard Import)."""
    __tablename__ = 'fiscal_treatments'
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    period = Column(String(64))
    user = Column(String(64))
    status = Column(String(32), default='en_cours')
    current_step = Column(Integer, default=1)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    log_json = Column(Text, default='[]')
    errors_json = Column(Text, default='[]')


class TreatmentSnapshot(Base):
    """Instantané après chaque traitement complet (historique & comparaisons)."""
    __tablename__ = 'treatment_snapshots'
    id = Column(Integer, primary_key=True)
    date_run = Column(DateTime, default=datetime.utcnow)
    user = Column(String(64))
    total = Column(Integer, default=0)
    defaillants = Column(Integer, default=0)
    neants = Column(Integer, default=0)
    relicataires = Column(Integer, default=0)
    declarants = Column(Integer, default=0)
    taux_declaration = Column(Float, default=0.0)
    sum_montant_attendu = Column(Float, default=0.0)
    sum_montant_declare = Column(Float, default=0.0)
    sum_montant_recu = Column(Float, default=0.0)
    nb_fichiers = Column(Integer, default=0)
    cflp_stats_json = Column(Text)
    label = Column(String(128))


class CaAnalysisMeta(Base):
    """Métadonnées du dernier traitement CA (wizard étape 6)."""
    __tablename__ = 'ca_analysis_meta'
    id = Column(Integer, primary_key=True)
    year_current = Column(Integer)
    year_previous = Column(Integer)
    mapped_count = Column(Integer, default=0)
    excluded_na_count = Column(Integer, default=0)
    lines_current = Column(Integer, default=0)
    lines_previous = Column(Integer, default=0)
    source_json = Column(Text, default='{}')
    user = Column(String(64))
    date_run = Column(DateTime, default=datetime.utcnow)


class CaBySousSecteur(Base):
    """CA agrégé par sous-secteur (comparaison N / N-1)."""
    __tablename__ = 'ca_by_sous_secteur'
    id = Column(Integer, primary_key=True)
    sous_secteur = Column(String(128), nullable=False)
    ca_current = Column(Float, default=0.0)
    ca_previous = Column(Float, default=0.0)
    ecart_absolu = Column(Float, default=0.0)
    evolution_pct = Column(Float, nullable=True)
    is_total = Column(Integer, default=0)


class CaNiuLine(Base):
    """Consolidé + RECHERCHEV CA par NIU (export de contrôle)."""
    __tablename__ = 'ca_niu_lines'
    niu = Column(String(32), primary_key=True)
    raison = Column(String(255))
    montant_declare = Column(Float, default=0.0)
    secteur = Column(String(128))
    sous_secteur = Column(String(128))
    ca_current = Column(Float, nullable=True)
    ca_previous = Column(Float, nullable=True)
    statut_ca = Column(String(64))


class AdminAccount(Base):
    """Compte administrateur unique — mot de passe hashé en base."""
    __tablename__ = 'admin_accounts'
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PasswordResetToken(Base):
    """Code OTP à usage unique pour réinitialisation du mot de passe admin."""
    __tablename__ = 'password_reset_tokens'
    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey('admin_accounts.id'), nullable=False)
    code_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    request_ip = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)
