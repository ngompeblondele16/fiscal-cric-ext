"""Services métier — logique de traitement et persistance."""
from services.consolidation import (  # noqa: F401
    clear_consolidation,
    consolidated_is_ready,
    ensure_monthly_recu_cached,
    get_consolidated_export_rows,
    load_consolidated_dict,
    load_consolidated_meta,
    load_monthly_recu_dict,
    save_consolidation,
    save_consolidation_meta,
)
