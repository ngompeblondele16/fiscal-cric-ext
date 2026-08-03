# Plateforme d'Automatisation des Statistiques Fiscales

Application web Flask pour automatiser la production des statistiques fiscales à partir de fichiers Excel/CSV.

## Fonctionnalités

### 1. Gestion des imports
- ✅ Import de fichiers Excel/CSV (déclarations, paiements, contribuables)
- ✅ Détection automatique du type de fichier
- ✅ File d'attente des imports (importer plusieurs fichiers avant lancement)
- ✅ Validation des NIU (format: P/M + 12 chiffres + 1 lettre)
- ✅ Nettoyage automatique et suppression des doublons

### 2. Comparaison de fichiers (VLOOKUP)
- ✅ Comparaison automatique entre fichier source (attendu) et fichier déclaré
- ✅ Identification des non-déclarants
- ✅ Identification des NIU non attendus
- ✅ Affichage détaillé des correspondances

### 3. Calcul des statistiques
- ✅ Statistiques globales (total, déclarants, payés, non-déclarés)
- ✅ Groupage par CDI (Centre des Impôts)
- ✅ Groupage par secteur
- ✅ Groupage par sous-secteur
- ✅ Liste détaillée des non-déclarants

### 4. Export des rapports
- ✅ Export en Excel (.xlsx) avec plusieurs feuilles
- ✅ Export en PDF avec formatage professionnel
- ✅ Recherche et export de données individuelles

### 5. Authentification
- ✅ Système de login simple (admin/admin par défaut)
- ✅ Gestion de session sécurisée

### 6. Interface utilisateur
- ✅ Interface moderne avec Bootstrap 5
- ✅ Responsive design
- ✅ Tableaux interactifs
- ✅ Historique des imports

## Installation

### Prérequis
- Python 3.9+
- pip

### Étapes

1. Créez un environnement virtuel Python:
```bash
python -m venv env
source env/Scripts/activate  # Windows: env\Scripts\activate
```

2. Installez les dépendances:
```bash
pip install -r requirements.txt
```

3. Lancez l'application:
```bash
python app.py
```

4. Accédez à l'application:
- URL: http://localhost:5000
- Login: `admin`
- Mot de passe: `admin`

## Architecture de la base de données

### Tables principales
- **contribuables**: Informations de base des contribuables
- **declarations**: Déclarations fiscales par NIU
- **paiements**: Paiements effectués
- **import_history**: Historique des imports
- **pending_imports**: File d'attente des imports en cours
- **state_history**: Historique des changements d'état

## Flux d'utilisation

### Workflow standard:
1. **Importer les fichiers**: Utilisez `/upload` pour importer les fichiers Excel/CSV
2. **Examiner la queue**: Allez dans `/pending_imports` pour voir les fichiers en attente
3. **Traiter les imports**: Cliquez sur "Traiter tous les fichiers"
4. **Calculer les stats**: Utilisez le bouton "Calculer les statistiques"
5. **Consulter les résultats**: Visualisez les tableaux et statistiques
6. **Exporter**: Téléchargez en Excel ou PDF

### Workflow de comparaison (VLOOKUP):
1. Aller dans le menu "Comparer les fichiers"
2. Charger le fichier source (attendu)
3. Charger le fichier déclaré (réalisé)
4. Analyser les résultats (correspondances, non-déclarants, non-attendus)

## Routes disponibles

| Route | Méthode | Description |
|-------|---------|-------------|
| `/login` | GET, POST | Page de connexion |
| `/logout` | GET | Déconnexion |
| `/` | GET | Tableau de bord |
| `/upload` | GET, POST | Importer un fichier |
| `/pending_imports` | GET | Voir la file d'attente |
| `/process_queue` | POST | Traiter les imports en attente |
| `/delete_pending/<id>` | GET | Supprimer un import en attente |
| `/search` | GET | Rechercher un contribuable |
| `/compare` | GET, POST | Comparer deux fichiers |
| `/compute` | POST | Calculer les statistiques |
| `/export` | GET | Exporter les données en Excel |
| `/export_stats` | GET | Exporter les statistiques en Excel |
| `/export_pdf` | GET | Exporter le rapport en PDF |

## Format des fichiers

### Colonnes attendues

**Fichier déclarations:**
- NIU (identifiant unique)
- Raison sociale / Nom du contribuable
- Montant déclaré / Somme totale déclarée
- Secteur (optionnel)
- Sous-secteur (optionnel)
- CDI / Centre des impôts (optionnel)

**Fichier paiements:**
- NIU
- Montant payé
- Date de paiement (optionnel)

**Fichier contribuables:**
- NIU
- Raison sociale
- État fiscal (0, 2, ou 3)
- Montant attendu

## Les états fiscaux

- **État 0**: Contribuable enregistré mais déclaration non soumise
- **État 2**: Déclaration faite mais paiement non effectué
- **État 3**: Déclaration faite et paiement effectué

## Dépendances principales

- **Flask**: Framework web
- **SQLAlchemy**: ORM pour la base de données
- **Pandas**: Traitement des données
- **Openpyxl**: Lecture/écriture Excel
- **ReportLab**: Génération de PDF

## Configuration

Modifiez les identifiants par défaut dans `app.py`:
```python
ADMIN_USER = 'admin'
ADMIN_PASS = 'admin'
```

## Notes de développement

- Utilisation de SQLite par défaut (sqlite:///data.db)
- Les fichiers importés sont stockés dans le répertoire `uploads/`
- Les statistiques utilisent pandas `groupby()` et agrégations SQL
- Les NIU sont stockés comme String pour préserver les formats spéciaux

## Fichiers clés

- [app.py](app.py) - Application principale Flask
- [models.py](models.py) - Modèles SQLAlchemy
- [import_utils.py](import_utils.py) - Utilitaires pour traiter les imports
- [pdf_utils.py](pdf_utils.py) - Génération de rapports PDF
- [niu.py](niu.py) - Validation des NIU
- [templates/](templates/) - Templates HTML

## Améliorations futures

- [ ] Authentification LDAP/Active Directory
- [ ] Tableau de bord avec charts/graphiques
- [ ] Export en multiple formats (CSV, JSON)
- [ ] Gestion des utilisateurs multi-niveaux
- [ ] Notifications par email
- [ ] Historique des modifications par utilisateur
- [ ] API REST

## License

Propriétaire - Tous droits réservés

## Support

Pour le support technique, contactez l'équipe de développement.

