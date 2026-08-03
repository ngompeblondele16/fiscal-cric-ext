import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_utils import merge_phase1_consolidated_parts


def test_declatvaa_monthly_snapshot_is_kept_over_cumulative_sources():
    target = {}
    monthly = {
        'M001': {
            'raison': 'Société A',
            'montant_declare': 100.0,
            'montant_paye': 10.0,
            'etat': 3,
            'etat_display': '3',
        }
    }
    cumulative_2025 = {
        'M001': {
            'raison': 'Société A',
            'montant_declare': 200.0,
            'montant_paye': 20.0,
            'etat': 3,
            'etat_display': '3',
        }
    }
    cumulative_2026 = {
        'M001': {
            'raison': 'Société A',
            'montant_declare': 300.0,
            'montant_paye': 30.0,
            'etat': 3,
            'etat_display': '3',
        }
    }

    merge_phase1_consolidated_parts(
        target,
        sector_parts=[],
        declatvaa_parts=[
            ('DECLATVAA JUIN.xlsx', monthly),
            ('DECLATVAA Janv Juin 2025.xlsx', cumulative_2025),
            ('DECLATVAA Janv Juin 2026.xlsx', cumulative_2026),
        ],
    )

    assert target['M001']['montant_declare'] == 100.0
    assert target['M001']['montant_paye'] == 10.0
