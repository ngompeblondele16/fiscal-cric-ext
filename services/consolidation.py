"""Persistance Phase 1 — source de vérité : base SQLite (Excel = export à la demande)."""
import json
from datetime import datetime

from sqlalchemy import func

from models import ConsolidatedLine, ConsolidationMeta, ImportHistory, MonthlyRecu, SectorielImportLine


def _line_to_dict(line):
    return {
        'raison': line.raison or '',
        'montant_declare': float(line.montant_declare or 0),
        'montant_paye': line.montant_paye,
        'etat': line.etat,
        'etat_display': line.etat_display or '',
    }


def load_consolidated_dict(db):
    rows = db.query(ConsolidatedLine).all()
    return {r.niu: _line_to_dict(r) for r in rows}


def load_consolidated_meta(db):
    meta = db.query(ConsolidationMeta).order_by(ConsolidationMeta.id.desc()).first()
    if meta and meta.controls_json:
        try:
            return json.loads(meta.controls_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def recompute_monthly_recu_from_sectoriel_lines(db):
    q = db.query(
        SectorielImportLine.date_creation_year,
        SectorielImportLine.date_creation_month,
        func.coalesce(func.sum(SectorielImportLine.montant_recu), 0.0),
    ).filter(
        SectorielImportLine.date_creation_year.isnot(None),
        SectorielImportLine.date_creation_month.isnot(None),
        SectorielImportLine.montant_recu.isnot(None),
        SectorielImportLine.montant_recu > 0,
    ).group_by(
        SectorielImportLine.date_creation_year,
        SectorielImportLine.date_creation_month,
    )
    out = {}
    for year, month, total in q.all():
        out.setdefault(str(int(year)), {})[str(int(month))] = float(total or 0)
    return out


def _persist_monthly_recu_dict(db, data):
    db.query(MonthlyRecu).delete()
    mappings = []
    for year_str, months in (data or {}).items():
        try:
            y = int(year_str)
        except (TypeError, ValueError):
            continue
        for month_str, amount in months.items():
            try:
                m = int(month_str)
            except (TypeError, ValueError):
                continue
            mappings.append({'year': y, 'month': m, 'montant': float(amount or 0)})
    _bulk_insert_mappings(db, MonthlyRecu, mappings)
    db.commit()


def load_monthly_recu_dict(db):
    rows = db.query(MonthlyRecu).all()
    if rows:
        out = {}
        for r in rows:
            out.setdefault(str(int(r.year)), {})[str(int(r.month))] = float(r.montant or 0)
        return out
    recomputed = recompute_monthly_recu_from_sectoriel_lines(db)
    if recomputed:
        _persist_monthly_recu_dict(db, recomputed)
    return recomputed


def consolidated_is_ready(db):
    return db.query(ConsolidatedLine).count() > 0


def ensure_monthly_recu_cached(db):
    if db.query(MonthlyRecu).count() > 0:
        return
    if db.query(SectorielImportLine).count() == 0:
        return
    recomputed = recompute_monthly_recu_from_sectoriel_lines(db)
    if recomputed:
        _persist_monthly_recu_dict(db, recomputed)


def get_consolidated_export_rows(db):
    from import_utils import _consolidated_rows_for_export
    return _consolidated_rows_for_export(load_consolidated_dict(db))


def clear_consolidation(db):
    from services.secteur_cime import clear_secteur_cime_catalog
    db.query(SectorielImportLine).delete()
    db.query(MonthlyRecu).delete()
    db.query(ConsolidatedLine).delete()
    db.query(ConsolidationMeta).delete()
    clear_secteur_cime_catalog(db, commit=False)
    db.commit()


def save_consolidation_meta(db, controls, user=None, commit=True):
    db.query(ConsolidationMeta).delete()
    db.add(ConsolidationMeta(
        date_run=datetime.utcnow(),
        user=user,
        controls_json=json.dumps(controls, ensure_ascii=False),
    ))
    if commit:
        db.commit()


def _bulk_insert_mappings(db, model, mappings, chunk_size=2000):
    if not mappings:
        return
    for i in range(0, len(mappings), chunk_size):
        db.bulk_insert_mappings(model, mappings[i:i + chunk_size])


def save_consolidation(db, consolidated, all_rows, controls, monthly_recu,
                       user='admin', source_filenames=None):
    source_filenames = source_filenames or []
    default_source = source_filenames[0] if len(source_filenames) == 1 else ''

    db.query(SectorielImportLine).delete()
    db.query(MonthlyRecu).delete()
    db.query(ConsolidatedLine).delete()
    db.flush()

    now = datetime.utcnow()

    consolidated_mappings = []
    for niu, data in consolidated.items():
        mp = data.get('montant_paye')
        consolidated_mappings.append({
            'niu': niu,
            'raison': data.get('raison', ''),
            'montant_declare': float(data.get('montant_declare', 0) or 0),
            'montant_paye': float(mp) if mp is not None else None,
            'etat': data.get('etat'),
            'etat_display': data.get('etat_display', ''),
            'updated_at': now,
        })
    _bulk_insert_mappings(db, ConsolidatedLine, consolidated_mappings)

    sectoriel_mappings = []
    for rec in all_rows:
        dt = rec.get('date_creation')
        year = month = None
        if dt:
            year, month = dt
        mp = rec.get('montant_paye')
        sectoriel_mappings.append({
            'niu': rec['niu'],
            'raison': rec.get('raison', ''),
            'montant_declare': float(rec.get('montant') or 0),
            'montant_recu': float(mp) if mp is not None else None,
            'etat': rec.get('etat'),
            'etat_display': rec.get('etat_display', ''),
            'date_creation_year': year,
            'date_creation_month': month,
            'source_filename': rec.get('source_filename') or default_source,
            'imported_at': now,
        })
    _bulk_insert_mappings(db, SectorielImportLine, sectoriel_mappings)

    monthly_mappings = []
    for year_str, months in (monthly_recu or {}).items():
        try:
            y = int(year_str)
        except (TypeError, ValueError):
            continue
        for month_str, amount in months.items():
            try:
                m = int(month_str)
            except (TypeError, ValueError):
                continue
            monthly_mappings.append({'year': y, 'month': m, 'montant': float(amount or 0)})
    _bulk_insert_mappings(db, MonthlyRecu, monthly_mappings)

    save_consolidation_meta(db, controls, user=user, commit=False)

    label = ', '.join(source_filenames[:3]) if source_filenames else 'Consolidation sectorielle'
    if source_filenames and len(source_filenames) > 3:
        label += f' (+{len(source_filenames) - 3})'
    db.add(ImportHistory(
        filename=label,
        user=user,
        nb_lignes=int(controls.get('nb_lignes') or len(all_rows) or 0),
        file_type='sectoriel',
        status='consolide',
        errors='',
    ))
    db.commit()
