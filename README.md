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

Les identifiants et chemins se configurent via variables d'environnement (voir [.env.example](.env.example)) :

| Variable | Description | Défaut |
|----------|-------------|--------|
| `APP_SECRET` | Clé secrète Flask | `change-me` |
| `ADMIN_USER` / `ADMIN_PASS` | Login admin | `admin` / `admin` |
| `DATABASE_URL` | Connexion SQLAlchemy | SQLite locale |
| `DATA_DIR` | Racine données persistantes | répertoire projet |
| `UPLOAD_DIR` | Fichiers en attente d'import | `{DATA_DIR}/uploads` |

## Déploiement Render (production)

Le dépôt inclut [render.yaml](render.yaml) pour le **déploiement automatique** à chaque push sur `main`.

### Première mise en place

1. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**
2. Connecter le dépôt GitHub `ngompeblondy-cpu/fiscal-cric-ext`
3. Renseigner `ADMIN_USER` et `ADMIN_PASS` (variables marquées `sync: false`)
4. Valider le déploiement

### Service déjà créé manuellement

Si un Web Service existe déjà sans Blueprint, mettre à jour dans le dashboard :

| Paramètre | Valeur |
|-----------|--------|
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn -c gunicorn.conf.py app:app` |
| **Health Check Path** | `/health` |
| **Auto-Deploy** | Activé (branche `main`) |
| **Disque persistant** | 1 Go monté sur `/var/data` |

Variables d'environnement recommandées :

```
DATA_DIR=/var/data
UPLOAD_DIR=/var/data/uploads
DATABASE_URL=sqlite:////var/data/data.db
GUNICORN_TIMEOUT=600
APP_SECRET=<générer une clé aléatoire>
ADMIN_USER=<votre login>
ADMIN_PASS=<votre mot de passe>
```

### Consolidation bloquée sur « Traitement en cours… »

Ce spinner disparaît quand le serveur termine le POST et redirige. S'il tourne indéfiniment :

1. **Timeout Gunicorn** — le traitement Excel dépasse 30 s par défaut ; `gunicorn.conf.py` fixe 600 s
2. **Disque persistant** — sans `/var/data`, les fichiers uploadés disparaissent au redémarrage
3. **Logs Render** — vérifier 502/504 ou `Worker timeout` au moment du clic sur « Lancer la consolidation »

Commande locale équivalente à Render :

```bash
gunicorn -c gunicorn.conf.py app:app
```

## Mot de passe oublié

Deux méthodes disponibles :

### 1. Code de secours (recommandé — fonctionne sans email)

Sur Render, définir la variable :

```
ADMIN_RECOVERY_CODE=CRIC-EXT-2026
```

*(Changez cette valeur après la première utilisation.)*

Sur la page « Mot de passe oublié » :
1. Saisir le **code de secours**
2. Choisir un **nouveau mot de passe** (min. 8 caractères)
3. Se reconnecter avec le nouveau mot de passe

### 2. Par email OTP (optionnel)

Flux : **Email → code 6 chiffres (15 min) → nouveau mot de passe**.

Variables à configurer sur Render :

| Variable | Exemple (SendGrid) |
|----------|-------------------|
| `ADMIN_EMAIL` | `admin@votre-domaine.com` |
| `SMTP_HOST` | `smtp.sendgrid.net` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `apikey` |
| `SMTP_PASSWORD` | clé API SendGrid |
| `MAIL_FROM` | `noreply@votre-domaine.com` |

Services SMTP compatibles : SendGrid, Brevo, Mailgun, Gmail (compte app).

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

