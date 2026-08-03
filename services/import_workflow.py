"""Orchestration des traitements d'import (Phase 1 / Phase 2)."""
import os

from models import PendingImport
from import_utils import run_phase1_consolidation, safe_remove_file
from services.notifications import add_notification


def run_phase1_and_notify(db, user):
    """Consolide les fichiers sectoriels en attente, nettoie la file et notifie."""
    pendings = db.query(PendingImport).filter(
        (PendingImport.import_phase == 1) | (PendingImport.import_phase.is_(None))
    ).all()
    if not pendings:
        return None

    filepaths = [p.filepath for p in pendings if p.filepath and os.path.exists(p.filepath)]
    result = run_phase1_consolidation(filepaths, user=user, db_session=db)

    if not result.get('success'):
        return result

    for pending in pendings:
        if pending.filepath:
            try:
                safe_remove_file(pending.filepath)
            except OSError:
                pass
        db.delete(pending)

    add_notification(
        db,
        result.get('notification') or f"Consolidation terminée — {result['nb_contribuables']} contribuable(s).",
        level='success',
        source='import',
    )
    db.commit()
    return result
