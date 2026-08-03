from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from datetime import datetime
import io
from xml.sax.saxutils import escape

from fiscal_constants import ORGANISATION_NAME, ORGANISATION_SHORT


def _pdf_escape(text):
    """Échappe le texte pour les Paragraph ReportLab (XML)."""
    return escape(_pdf_text(text))


def _pdf_text(value, max_len=None):
    """Texte sûr pour cellules PDF (None, NaN, nombres)."""
    if value is None:
        s = ''
    elif isinstance(value, float) and value != value:
        s = ''
    else:
        s = str(value).strip()
        if s.lower() in ('nan', 'none', 'null'):
            s = ''
    if max_len is not None and len(s) > max_len:
        s = s[:max_len]
    return s


def _pdf_cell(value):
    """Valeur sûre pour une cellule de tableau PDF."""
    if value is None:
        return ''
    if isinstance(value, float) and value != value:
        return ''
    if isinstance(value, str):
        s = value.strip()
        if not s or s.upper() in ('N/A', 'NA', '-', '—', 'VIDE', 'NULL'):
            return s if s.upper() == 'N/A' else (s or '')
        try:
            num = float(s.replace(' ', '').replace(',', '.'))
            if num == int(num):
                return f"{int(num):,}".replace(',', ' ')
            return f"{num:,.2f}".replace(',', ' ')
        except ValueError:
            return s
    if isinstance(value, (int, float)):
        if float(value) == int(value):
            return f"{int(value):,}".replace(',', ' ')
        return f"{float(value):,.2f}".replace(',', ' ')
    return str(value)


def _pdf_amount(value, default='0'):
    """Montant formaté pour PDF (ne lève jamais d'exception)."""
    if value is None:
        return default
    if isinstance(value, str) and value.strip().upper() in ('N/A', 'NA', '-', '—'):
        return value.strip().upper()
    try:
        num = float(value or 0)
        return f"{int(round(num)):,}".replace(',', ' ')
    except (TypeError, ValueError):
        return _pdf_cell(value)


def _pdf_rows(rows):
    """Normalise les lignes du tableau (pas de None, types convertis)."""
    return [[_pdf_cell(cell) for cell in row] for row in rows]

def generate_stats_pdf(stats_data):
    """
    Génère un rapport PDF avec les statistiques.
    stats_data: dict avec keys 'global', 'cdi', 'secteur', 'sous_secteur', 'non_declarants'
    """
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=A4,
                            rightMargin=0.5*inch,
                            leftMargin=0.5*inch,
                            topMargin=0.75*inch,
                            bottomMargin=0.75*inch)
    
    story = []
    styles = getSampleStyleSheet()
    
    # Titre
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#003399'),
        spaceAfter=30,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    story.append(Paragraph("RAPPORT DE STATISTIQUES FISCALES", title_style))
    story.append(Paragraph(
        _pdf_escape(f"{ORGANISATION_NAME} ({ORGANISATION_SHORT})"),
        ParagraphStyle(
            'OrgStyle',
            parent=styles['Normal'],
            fontSize=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#003399'),
            spaceAfter=6,
        ),
    ))
    story.append(Spacer(1, 0.2*inch))    
    # Date
    date_style = ParagraphStyle(
        'DateStyle',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER,
        textColor=colors.grey
    )
    story.append(Paragraph(f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", date_style))
    story.append(Spacer(1, 0.3*inch))
    
    # Statistiques Globales
    story.append(Paragraph(_pdf_escape("1. STATISTIQUES GLOBALES"), styles['Heading2']))
    story.append(Spacer(1, 0.2*inch))
    
    global_data = stats_data.get('global', [])
    if global_data:
        table_data = [['Métrique', 'Valeur']]
        for item in global_data:
            metric = _pdf_text(item.get('metric') or item.get('metrique', ''))
            if not metric:
                metric = 'Indicateur'
            raw_val = item.get('value', item.get('valeur', 0))
            if isinstance(raw_val, float) and raw_val != raw_val:
                raw_val = 0
            try:
                num = float(raw_val or 0)
                if num == int(num):
                    value = f"{int(num):,}".replace(',', ' ')
                else:
                    value = f"{num:,.2f}".replace(',', ' ')
            except (TypeError, ValueError):
                value = _pdf_text(raw_val)
            table_data.append([metric, value])
        
        table = Table(table_data, colWidths=[3*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003399')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        story.append(table)
    
    story.append(Spacer(1, 0.3*inch))

    def _append_metric_table(title, rows, headers, col_widths):
        if not rows:
            return
        story.append(Paragraph(_pdf_escape(title), styles['Heading2']))
        story.append(Spacer(1, 0.15*inch))
        table_data = [[_pdf_cell(h) for h in headers]]
        for item in rows:
            if isinstance(item, dict):
                table_data.append([_pdf_cell(item.get(h, '')) for h in headers])
            else:
                table_data.append([_pdf_cell(c) for c in item])
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003399')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f4f6')]),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.25*inch))

    taux_headers = [
        'Secteur / Structure', 'Taille', 'Décl.', 'Taux %',
        'Défaill.', 'Néants', 'Non contr.', 'Taux NC %',
    ]
    taux_keys = [
        'Secteur / Structure', 'Taille du fichier', 'Déclarations', 'Taux déclaration (%)',
        'Défaillants', 'Néants', 'Non contributeur', 'Taux non contributeur (%)',
    ]
    taux_widths = [1.4*inch, 0.55*inch, 0.5*inch, 0.5*inch, 0.55*inch, 0.5*inch, 0.65*inch, 0.65*inch]

    taux_secteur = stats_data.get('taux_secteur', [])
    if taux_secteur:
        rows = [[item.get(k, '') for k in taux_keys] for item in taux_secteur]
        _append_metric_table('2. TAUX DE DÉCLARATION PAR SECTEUR', rows, taux_headers, taux_widths)

    taux_structure = stats_data.get('taux_structure', [])
    if taux_structure:
        rows = [[item.get(k, '') for k in taux_keys] for item in taux_structure]
        _append_metric_table('3. TAUX DE DÉCLARATION PAR CFLP', rows, taux_headers, taux_widths)

    perf_cflp = stats_data.get('performance_cflp', [])
    if perf_cflp:
        perf_headers = ['Structure', 'Montant décl.', 'Montant reçu', 'Écart', 'Taux enc. %']
        perf_keys = ['Structure', 'Montant déclaré (FCFA)', 'Montant reçu (FCFA)', 'Écart (FCFA)', 'Taux encaissement (%)']
        rows = [[item.get(k, '') for k in perf_keys] for item in perf_cflp]
        _append_metric_table('4. PERFORMANCE PAR CENTRE (CFLP)', rows, perf_headers, [1.6*inch, 1.1*inch, 1.1*inch, 1.0*inch, 0.75*inch])

    montants_sect = stats_data.get('montants_secteur', [])
    if montants_sect:
        ms_headers = ['Secteur', 'Montant décl.', 'Montant reçu', 'Écart', 'Taux enc. %']
        ms_keys = ['Secteur', 'Montant déclaré (FCFA)', 'Montant reçu (FCFA)', 'Écart (FCFA)', 'Taux encaissement (%)']
        rows = [[item.get(k, '') for k in ms_keys] for item in montants_sect]
        _append_metric_table('5. MONTANTS DÉCLARÉS ET REÇUS PAR SECTEUR', rows, ms_headers, [1.6*inch, 1.1*inch, 1.1*inch, 1.0*inch, 0.75*inch])
    
    # Par CFLP
    story.append(Paragraph(_pdf_escape("6. STATISTIQUES PAR CFLP"), styles['Heading2']))
    story.append(Spacer(1, 0.2*inch))
    
    cflp_data = stats_data.get('cflp') or stats_data.get('cdi', [])
    if cflp_data:
        table_data = [['CFLP', 'Nombre de Déclarations', 'Montant Déclaré']]
        for item in cflp_data:
            centre = _pdf_text(item.get('cflp') or item.get('cdi') or 'N/A')
            count = _pdf_amount(item.get('count', 0))
            amount = _pdf_amount(item.get('sum_declared', 0))
            table_data.append([centre, count, amount])
        
        table = Table(table_data, colWidths=[2*inch, 1.5*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003399')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        story.append(table)
    
    story.append(Spacer(1, 0.3*inch))

    # Par État
    etat_data = stats_data.get('etat', [])
    if etat_data:
        story.append(Paragraph(_pdf_escape("7. STATISTIQUES PAR ÉTAT"), styles['Heading2']))
        story.append(Spacer(1, 0.2*inch))
        table_data = [['État', 'Nombre', 'Montant']]
        for item in etat_data:
            label = _pdf_text(item.get('Catégorie') or item.get('État') or item.get('label') or 'N/A')
            count = _pdf_amount(item.get('Nombre') or item.get('count', 0))
            amount_val = item.get('Montant déclaré') or item.get('Montant') or item.get('montant', 0)
            amount = _pdf_amount(amount_val)
            table_data.append([label, count, amount])
        table = Table(table_data, colWidths=[3*inch, 1.5*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003399')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        story.append(table)
        story.append(PageBreak())

    # Par Secteur
    story.append(Paragraph(_pdf_escape("6. STATISTIQUES PAR SECTEUR"), styles['Heading2']))
    story.append(Spacer(1, 0.2*inch))
    
    secteur_data = stats_data.get('secteur', [])
    if secteur_data:
        table_data = [['Secteur', 'Nombre de Déclarations', 'Montant Déclaré']]
        for item in secteur_data:
            secteur = _pdf_text(item.get('secteur') or 'N/A')
            count = _pdf_amount(item.get('count', 0))
            amount = _pdf_amount(item.get('sum_declared', 0))
            table_data.append([secteur, count, amount])
        
        table = Table(table_data, colWidths=[2*inch, 1.5*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003399')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        story.append(table)
    
    story.append(Spacer(1, 0.3*inch))
    
    # Par Sous-Secteur
    sous_data = stats_data.get('sous_secteur', [])
    if sous_data:
        story.append(Paragraph(_pdf_escape("4. STATISTIQUES PAR SOUS-SECTEUR"), styles['Heading2']))
        story.append(Spacer(1, 0.2*inch))
        
        table_data = [['Sous-Secteur', 'Nombre de Déclarations', 'Montant Déclaré']]
        for item in sous_data:
            sous = _pdf_text(item.get('sous_secteur') or 'N/A')
            count = _pdf_amount(item.get('count', 0))
            amount = _pdf_amount(item.get('sum_declared', 0))
            table_data.append([sous, count, amount])
        
        table = Table(table_data, colWidths=[2*inch, 1.5*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003399')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        story.append(table)
    
    story.append(PageBreak())
    
    def _append_list_section(title, items, headers, col_widths, header_color):
        if not items:
            return
        story.append(Paragraph(_pdf_escape(title), styles['Heading2']))
        story.append(Spacer(1, 0.2*inch))
        max_per_page = 30
        for idx in range(0, len(items), max_per_page):
            if idx > 0:
                story.append(PageBreak())
            chunk = items[idx:idx + max_per_page]
            table_data = [[_pdf_cell(h) for h in headers]]
            for item in chunk:
                table_data.append([_pdf_cell(cell) for cell in item])
            table = Table(table_data, colWidths=col_widths)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), header_color),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            story.append(table)
        story.append(PageBreak())

    # Défaillants
    defaillants = stats_data.get('defaillants') or stats_data.get('non_declarants', [])
    def_rows = []
    for item in defaillants:
        niu = _pdf_text(item.get('niu') or item.get('NIU'))
        raison = _pdf_text(item.get('raison') or item.get('Raison'), 40)
        cflp = _pdf_text(item.get('cflp') or item.get('CFLP') or item.get('cdi') or item.get('CDI'), 22)
        montant = item.get('montant_attendu') or item.get('Montant attendu') or 0
        def_rows.append([niu, raison, cflp, _pdf_amount(montant)])
    _append_list_section(
        f"5. LISTE DES DÉFAILLANTS — n'ont pas déclaré ({len(defaillants)} contribuables)",
        def_rows,
        ['NIU', 'Raison Sociale', 'CFLP', 'Montant attendu'],
        [1.3*inch, 2.7*inch, 1.5*inch, 1.2*inch],
        colors.HexColor('#CC0000'),
    )

    # Relicataires — ont déclaré, rien payé
    relicataires = stats_data.get('relicataires', [])
    relicataire_rows = []
    for item in relicataires:
        niu = _pdf_text(item.get('niu') or item.get('NIU'))
        raison = _pdf_text(item.get('raison') or item.get('Raison'), 40)
        cflp = _pdf_text(item.get('cflp') or item.get('CFLP') or item.get('cdi') or item.get('CDI'), 22)
        md = item.get('Montant déclaré') or item.get('montant_declare') or 0
        relicataire_rows.append([niu, raison, cflp, _pdf_amount(md), 'N/A'])
    _append_list_section(
        f"5. LISTE DES RELICATAIRES — ont déclaré, rien payé ({len(relicataires)} contribuables)",
        relicataire_rows,
        ['NIU', 'Raison Sociale', 'CFLP', 'Montant déclaré', 'Montant payé'],
        [1.1*inch, 2.2*inch, 1.3*inch, 1.2*inch, 0.9*inch],
        colors.HexColor('#ea580c'),
    )

    # Déclarants (incl. néants)
    declarants = stats_data.get('declarants', [])
    neants_count = len([d for d in declarants if (d.get('Catégorie') or d.get('Statut') or '') == 'Néant'])
    decl_rows = []
    for item in declarants:
        niu = _pdf_text(item.get('niu') or item.get('NIU'))
        raison = _pdf_text(item.get('raison') or item.get('Raison'), 40)
        cflp = _pdf_text(item.get('cflp') or item.get('CFLP') or item.get('cdi') or item.get('CDI'), 18)
        cat = _pdf_text(item.get('Catégorie') or item.get('Statut') or 'Déclarant')
        md = item.get('Montant déclaré') or item.get('montant_declare') or 0
        mp = item.get('Montant payé') or item.get('montant_paye') or 'N/A'
        decl_rows.append([
            niu, raison, cat, cflp,
            _pdf_amount(md),
            _pdf_amount(mp) if mp not in (None, 'N/A') else 'N/A',
        ])
    pct_neants = round(neants_count / len(declarants) * 100, 1) if declarants else 0
    _append_list_section(
        f"5. LISTE DES DÉCLARANTS — {len(declarants)} contribuables (dont {pct_neants}% néants)",
        decl_rows,
        ['NIU', 'Raison Sociale', 'Catégorie', 'CFLP', 'Montant déclaré', 'Montant payé'],
        [1.0*inch, 2.0*inch, 0.9*inch, 1.1*inch, 1.1*inch, 0.9*inch],
        colors.HexColor('#003399'),
    )

    # (section relicataires déjà au §5 — renuméroter si besoin)
    
    # Construire le PDF
    doc.build(story)
    bio.seek(0)
    return bio


def generate_table_pdf(title, subtitle, headers, rows, header_color=None):
    """Génère un PDF tabulaire pour les listes (défaillants, déclarants, recherche, etc.)."""
    if header_color is None:
        header_color = colors.HexColor('#003399')

    bio = io.BytesIO()
    doc = SimpleDocTemplate(
        bio, pagesize=A4,
        rightMargin=0.5 * inch, leftMargin=0.5 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        'ListTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#003399'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    )
    story.append(Paragraph(_pdf_escape(title), title_style))
    story.append(Paragraph(
        _pdf_escape(f"{ORGANISATION_NAME} ({ORGANISATION_SHORT})"),
        ParagraphStyle(
            'ListOrg', parent=styles['Normal'], fontSize=10,
            alignment=TA_CENTER, textColor=colors.HexColor('#003399'), spaceAfter=4,
        ),
    ))
    if subtitle:
        story.append(Paragraph(_pdf_escape(subtitle), ParagraphStyle(
            'ListSubtitle', parent=styles['Normal'], fontSize=10,
            alignment=TA_CENTER, textColor=colors.grey,
        )))
    story.append(Paragraph(
        f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        ParagraphStyle('ListDate', parent=styles['Normal'], fontSize=9, alignment=TA_CENTER, textColor=colors.grey),
    ))
    story.append(Spacer(1, 0.25 * inch))

    if not rows:
        story.append(Paragraph("Aucun enregistrement.", styles['Normal']))
    else:
        n_cols = len(headers)
        page_width = A4[0] - inch
        col_width = page_width / max(n_cols, 1)
        col_widths = [col_width] * n_cols
        max_per_page = 35
        for idx in range(0, len(rows), max_per_page):
            if idx > 0:
                story.append(PageBreak())
            chunk = rows[idx:idx + max_per_page]
            table_data = [[_pdf_cell(h) for h in headers]] + _pdf_rows(chunk)
            table = Table(table_data, colWidths=col_widths, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), header_color),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f4f6')]),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            story.append(table)

    doc.build(story)
    bio.seek(0)
    return bio
