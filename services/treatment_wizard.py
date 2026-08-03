"""État et journal du wizard de traitement fiscal."""
import json
from datetime import datetime

from models import FiscalTreatment

WIZARD_STEPS = [
    {'num': 1, 'key': 'setup', 'title': 'Paramètres', 'subtitle': 'Nouveau traitement'},
    {'num': 2, 'key': 'sector', 'title': 'Déclarations', 'subtitle': 'Import des fichiers'},
    {'num': 3, 'key': 'consolidated', 'title': 'Consolidation', 'subtitle': 'TCD & fusion'},
    {'num': 4, 'key': 'online', 'title': 'En ligne', 'subtitle': 'RECHERCHEV statuts'},
    {'num': 5, 'key': 'sectors', 'title': 'Secteurs', 'subtitle': 'RECHERCHEV Secteur CIME'},
    {'num': 6, 'key': 'ca', 'title': 'Chiffre d\'affaires', 'subtitle': 'CA par sous-secteur'},
    {'num': 7, 'key': 'results', 'title': 'Résultats', 'subtitle': 'TCD & export'},
]


def create_treatment(db, name, period, user='admin'):
    t = FiscalTreatment(
        name=name.strip() or 'Traitement fiscal',
        period=(period or '').strip() or datetime.utcnow().strftime('%Y'),
        user=user,
        status='en_cours',
        current_step=2,
        log_json='[]',
        errors_json='[]',
    )
    db.add(t)
    db.flush()
    log_step(db, t, 'setup', 'Traitement créé', f'{t.name} — période {t.period}')
    db.commit()
    return t


def get_treatment(db, treatment_id):
    if not treatment_id:
        return None
    return db.query(FiscalTreatment).filter_by(id=treatment_id).first()


def log_step(db, treatment, step_key, title, detail='', level='info', commit=False):
    if treatment is None:
        return
    try:
        log = json.loads(treatment.log_json or '[]')
    except (json.JSONDecodeError, TypeError):
        log = []
    log.append({
        'at': datetime.utcnow().strftime('%d/%m/%Y %H:%M:%S'),
        'step': step_key,
        'title': title,
        'detail': detail,
        'level': level,
    })
    treatment.log_json = json.dumps(log[-200:], ensure_ascii=False)
    if level == 'error':
        try:
            errs = json.loads(treatment.errors_json or '[]')
        except (json.JSONDecodeError, TypeError):
            errs = []
        errs.append({'at': datetime.utcnow().isoformat(), 'step': step_key, 'message': detail or title})
        treatment.errors_json = json.dumps(errs[-50:], ensure_ascii=False)
    if commit:
        db.commit()


def set_step(db, treatment, step_num, commit=True):
    if treatment:
        treatment.current_step = max(1, min(int(step_num), 7))
        if commit:
            db.commit()


def finish_treatment(db, treatment):
    if treatment:
        treatment.status = 'termine'
        treatment.finished_at = datetime.utcnow()
        treatment.current_step = 7
        log_step(db, treatment, 'results', 'Traitement terminé', commit=False)
        db.commit()


def load_log(treatment):
    if not treatment:
        return []
    try:
        return json.loads(treatment.log_json or '[]')
    except (json.JSONDecodeError, TypeError):
        return []


def sector_kpi_rows_for_export(db):
    """
    TCD par Secteur CIME — même structure que le tableau Excel manuel :
    DECLARANT | Taux décl. | DEFAIL | Taux DEFAIL | NEANT | Taille fichier
    """
    from services.excel_pipeline import safe_int
    from services.stats import get_taux_declaration_by_secteur

    rows = []
    for b in get_taux_declaration_by_secteur(db):
        declarant = safe_int(b.get('declarants', 0), 0)
        defaillants = safe_int(b.get('defaillants', 0), 0)
        neants = safe_int(b.get('neants', 0), 0)
        total = safe_int(b.get('taille_fichier', b.get('total', 0)), 0) or 0
        # RECHERCHEV : taux = (declarants montant > 10) / taille fichier × 100
        taux_decl = round(declarant / total * 100, 1) if total else 0.0
        taux_defail = round(defaillants / total * 100, 1) if total else 0.0
        rows.append({
            'SECTEUR': b.get('label', ''),
            'DECLARANT': declarant,
            'Taux de declaration': taux_decl,
            'DEFAIL': defaillants,
            'Taux de DEFAIL': taux_defail,
            'NEANT': neants,
            'Taille du fichier': total,
        })
    return rows


def sous_secteur_kpi_rows_for_export(db):
    """TCD par Sous secteur — format rapport (Taille, déclaration, def, néants, non contributeurs)."""
    from services.stats import get_taux_declaration_by_sous_secteur
    rows = []
    for b in get_taux_declaration_by_sous_secteur(db):
        rows.append({
            'SOUS SECTEUR': b.get('label', ''),
            'Taille': b.get('taille_fichier', 0),
            'declaration': b.get('declarations', 0),
            'Taux de declaration': b.get('taux_declaration', 0),
            'def': b.get('defaillants', 0),
            'NEANT': b.get('neants', 0),
            'Non contributeurs': b.get('non_contributeur', 0),
            'Taux de non contributeurs': b.get('taux_non_contributeur', 0),
        })
    return rows


def reliquataires_sous_secteur_rows_for_export(db):
    """Reliquataires / émissions par sous-secteur — format rapport & PowerPoint."""
    from services.stats import get_reliquataires_by_sous_secteur

    rows = []
    for b in get_reliquataires_by_sous_secteur(db):
        label = b.get('label', '')
        rows.append({
            'SOUS SECTEUR': label,
            'Reliquataires': b.get('reliquataires', 0),
            'Montant reliquataires': b.get('montant_reliquataires', 0),
            'Emissions': b.get('emissions', 0),
            'Ratio des reliquataires': b.get('ratio_reliquataires', 0),
            '_is_total': label == 'Total général',
        })
    return rows
