# Video Montage App — Documentation

Application web de génération automatisée de montages vidéo à partir de photos. Chaque photo est analysée par IA, animée en clip vidéo, puis assemblée avec voix off et musique de fond.

---

## Architecture

```
video-montage-app/
├── backend/                     # API FastAPI + pipeline de traitement
│   ├── app/
│   │   ├── api/
│   │   │   ├── router.py        # Router principal /api/v1 + auth middleware
│   │   │   ├── dependencies.py  # Vérification API key (header X-Api-Key)
│   │   │   ├── jobs.py          # Endpoints CRUD + workflow des jobs
│   │   │   └── photos.py        # Upload/list/delete des photos
│   │   ├── models/
│   │   │   ├── base.py          # Base SQLAlchemy déclarative
│   │   │   ├── job.py           # Modèle Job (SQLAlchemy)
│   │   │   └── photo.py         # Modèle Photo (SQLAlchemy)
│   │   ├── schemas/
│   │   │   ├── job.py           # Pydantic: JobCreate, JobResponse, CostEstimate
│   │   │   └── photo.py         # Pydantic: PhotoResponse
│   │   ├── services/
│   │   │   ├── cost_estimator.py   # Calcul des coûts avant lancement
│   │   │   ├── photo_analyzer.py   # Google Cloud Vision → labels, objets, description
│   │   │   ├── kie_animator.py     # Kie.ai → animation photo en clip vidéo (5-10s)
│   │   │   ├── voice_generator.py  # ElevenLabs → voix off TTS
│   │   │   ├── music_generator.py  # Suno via Kie.ai → musique instrumentale
│   │   │   ├── job_logger.py       # Système de logs SSE en temps réel
│   │   │   └── video_assembler.py  # MoviePy/FFmpeg → assemblage final
│   │   ├── workers/
│   │   │   └── video_pipeline.py   # Worker d'orchestration du pipeline complet
│   │   ├── config.py            # Configuration Pydantic (variables .env)
│   │   ├── database.py          # Engine SQLAlchemy async + session maker
│   │   └── main.py              # App FastAPI, CORS, router
│   ├── alembic/                 # Migrations de base de données
│   ├── uploads/                 # Photos uploadées (par job_id/)
│   ├── outputs/                 # Résultats (clips/, voiceover.mp3, music.mp3, final.mp4)
│   └── data/                    # Base SQLite (app.db)
├── frontend/                    # Interface React
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts        # Instance Axios (baseURL configurable)
│   │   │   ├── jobs.ts          # Fonctions API jobs
│   │   │   └── photos.ts        # Fonctions API photos
│   │   ├── stores/
│   │   │   └── jobStore.ts      # Zustand store (wizard state)
│   │   ├── components/
│   │   │   ├── Layout.tsx       # Header + container principal
│   │   │   ├── PhotoUploader.tsx    # Drag & drop upload (react-dropzone)
│   │   │   ├── ProgressTracker.tsx  # Barre de progression animée
│   │   │   ├── CostEstimateView.tsx # Affichage breakdown des coûts
│   │   │   └── VideoPlayer.tsx      # Lecteur vidéo + bouton téléchargement
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx    # Liste des jobs avec badges de statut
│   │   │   └── JobWizard.tsx    # Wizard 5 étapes (create → upload → estimate → processing → result)
│   │   ├── types/index.ts       # Types TypeScript (Job, Photo, CostEstimate)
│   │   ├── App.tsx              # BrowserRouter + routes
│   │   └── main.tsx             # Point d'entrée React
│   └── index.html
└── .env.example                 # Modèle des variables d'environnement
```

### Stack technique

| Composant | Technologie |
|-----------|-------------|
| Backend | FastAPI 0.115, Python 3.12, Uvicorn |
| Base de données | SQLite + SQLAlchemy 2.0 (async) + Alembic |
| Frontend | React 19, TypeScript, Vite 6, Tailwind CSS 4 |
| State management | Zustand 5 |
| Animation IA | Kie.ai (proxy Kling 2.6, image → vidéo 5-10s) |
| Analyse photo | Google Cloud Vision (labels + objets), auto à l'upload |
| Voix off | ElevenLabs TTS (modèle eleven_multilingual_v2) |
| Musique IA | Suno via Kie.ai (instrumental, modèle V4_5) |
| Montage vidéo | MoviePy 2.1 + FFmpeg |
| Authentification | API Key via header `X-Api-Key` |

---

## Endpoints API

Base URL : `http://localhost:8000/api/v1`

Authentification : header `X-Api-Key: <votre_clé>` (optionnel en dev si `API_KEY` est vide).

### Health Check

```
GET /health
```

Réponse : `{"status": "ok"}`

> Note : cet endpoint est hors du préfixe `/api/v1`, accessible directement à la racine.

---

### Jobs

#### Créer un job

```
POST /api/v1/jobs/
```

**Body (JSON)** :

| Champ | Type | Défaut | Description |
|-------|------|--------|-------------|
| `title` | string \| null | null | Titre du montage |
| `description` | string \| null | null | Description optionnelle |
| `webhook_url` | string \| null | null | URL webhook n8n (notifié à la fin) |
| `voiceover_text` | string \| null | null | Texte lu en voix off |
| `music_prompt` | string \| null | null | Prompt pour génération musicale Suno (via Kie.ai) |
| `include_music` | boolean | true | Inclure une musique de fond |
| `transition_type` | string | "crossfade" | Type de transition : `crossfade` ou `cut` |

**Réponse (201)** : `JobResponse`

#### Lister les jobs

```
GET /api/v1/jobs/?status=<status>
```

**Query params** :

| Param | Type | Description |
|-------|------|-------------|
| `status` | string (optionnel) | Filtrer par statut : `pending`, `awaiting_approval`, `processing`, `completed`, `failed` |

**Réponse (200)** : `JobResponse[]` (triés par date de création décroissante)

#### Récupérer un job

```
GET /api/v1/jobs/{job_id}
```

**Réponse (200)** : `JobResponse`

#### Supprimer un job

```
DELETE /api/v1/jobs/{job_id}
```

**Réponse (204)** : pas de body

#### Estimer le coût

```
POST /api/v1/jobs/{job_id}/estimate
```

Pré-requis : job en statut `pending` avec au moins 1 photo uploadée.

Passe le statut du job à `awaiting_approval`.

**Réponse (200)** :

```json
{
  "job_id": "uuid",
  "photo_count": 5,
  "voiceover_chars": 250,
  "include_music": true,
  "breakdown": {
    "kie_animation": 0.625,
    "google_vision": 0.0075,
    "elevenlabs_voiceover": 0.075,
    "kie_suno_music": 0.06
  },
  "total": 0.7675,
  "currency": "USD"
}
```

#### Approuver / Rejeter

```
POST /api/v1/jobs/{job_id}/approve
```

Pré-requis : job en statut `awaiting_approval`.

**Body (JSON)** :

| Champ | Type | Description |
|-------|------|-------------|
| `approved` | boolean | `true` → statut passe à `processing`, `false` → statut passe à `failed` |

**Réponse (200)** : `JobResponse`

#### Lancer le traitement

```
POST /api/v1/jobs/{job_id}/process
```

Pré-requis : job en statut `processing` (après approbation).

Lance le pipeline en arrière-plan via `BackgroundTasks`.

**Réponse (200)** : `JobResponse`

#### Streamer les logs en temps réel (SSE)

```
GET /api/v1/jobs/{job_id}/logs
```

Stream Server-Sent Events (SSE) du pipeline en cours. Chaque événement contient :

```json
{
  "timestamp": "2026-02-21T20:30:00",
  "source": "kie",
  "level": "info",
  "message": "Animation photo 1/3 — prompt : \"gentle waves...\""
}
```

Sources possibles : `pipeline`, `vision`, `kie`, `elevenlabs`, `music`, `ffmpeg`.
Niveaux : `info`, `success`, `warning`, `error`.

Un keepalive (`: keepalive\n\n`) est envoyé toutes les 15 secondes si aucun événement.

---

### Musique custom

#### Uploader un fichier audio

```
POST /api/v1/jobs/{job_id}/music
Content-Type: multipart/form-data
```

| Champ | Type | Description |
|-------|------|-------------|
| `file` | File | Fichier MP3 ou WAV (max 50 Mo) |

Pré-requis : job en statut `pending`.

Remplace le fichier audio précédent s'il en existait un. Met `include_music=true` et `custom_music_path` automatiquement.

**Réponse (201)** : `JobResponse`

> La musique custom est **prioritaire** sur la génération Suno (`music_prompt`). Si les deux sont renseignés, le fichier custom est utilisé.

#### Supprimer la musique custom

```
DELETE /api/v1/jobs/{job_id}/music
```

Supprime le fichier audio custom du job. Retombe sur la génération Suno si `music_prompt` est renseigné.

**Réponse (204)** : pas de body

---

### Photos

Toutes les routes photos sont sous `/api/v1/jobs/{job_id}/photos`.

#### Uploader une photo

```
POST /api/v1/jobs/{job_id}/photos/
Content-Type: multipart/form-data
```

| Champ | Type | Description |
|-------|------|-------------|
| `file` | File | Image JPG, PNG ou WebP (max 10 Mo) |

Pré-requis : job en statut `pending`.

L'analyse Google Vision est exécutée automatiquement à l'upload (labels, objets, description). Si l'analyse échoue, l'upload reste valide.

**Réponse (201)** :

```json
{
  "id": "uuid",
  "job_id": "uuid",
  "filename": "generated-uuid.jpg",
  "original_filename": "photo1.jpg",
  "position": 0,
  "vision_labels": [{"description": "Sky", "score": 0.98}, ...],
  "vision_description": "Sky, Landscape, Mountain. Objets: Tree, Building",
  "vision_objects": [{"name": "Tree", "score": 0.95}, ...],
  "created_at": "2026-01-01T00:00:00"
}
```

#### Lister les photos d'un job

```
GET /api/v1/jobs/{job_id}/photos/
```

**Réponse (200)** : `PhotoResponse[]` (triées par position)

#### Supprimer une photo

```
DELETE /api/v1/jobs/{job_id}/photos/{photo_id}
```

**Réponse (204)** : pas de body

---

### Analyse photos (pour n8n)

#### Récupérer les analyses Vision de toutes les photos

```
GET /api/v1/jobs/{job_id}/photos/analysis
```

Retourne les données Google Vision de chaque photo du job, ordonnées par position. Utile pour n8n afin de construire le plan de montage.

**Réponse (200)** :

```json
[
  {
    "photo_id": "uuid",
    "filename": "salon.jpg",
    "vision_labels": [{"description": "Living room", "score": 0.97}, ...],
    "vision_description": "Living room, Interior design. Objets: Couch, Table",
    "vision_objects": [{"name": "Couch", "score": 0.93}, ...]
  }
]
```

---

### Plan de montage (pour n8n)

#### Soumettre un plan de montage

```
POST /api/v1/jobs/{job_id}/montage-plan
```

Reçoit le plan de montage depuis n8n, le stocke dans le job, et lance automatiquement le pipeline.

**Body (JSON)** : tableau de segments

```json
[
  {
    "photo_id": "uuid-photo-1",
    "segment_text": "Voici le salon lumineux avec vue sur le jardin",
    "duration_seconds": 7.5,
    "music_volume": 0.3
  },
  {
    "photo_id": "uuid-photo-2",
    "segment_text": "La cuisine moderne entièrement équipée",
    "duration_seconds": 5.0,
    "music_volume": 0.8
  }
]
```

| Champ | Type | Défaut | Contraintes | Description |
|-------|------|--------|-------------|-------------|
| `photo_id` | string | — | Doit exister dans le job | ID de la photo pour ce segment |
| `segment_text` | string | — | — | Texte descriptif du segment (pour la voix off ou le contexte) |
| `duration_seconds` | float | 5.0 | 2.0 – 10.0 | Durée cible du segment en secondes |
| `music_volume` | float | 0.8 | 0.0 – 1.0 | Volume de la musique pour ce segment (0 = muet, 1 = plein volume) |

Validation :
- Tous les `photo_id` doivent exister dans le job (sinon 400)
- `duration_seconds` doit être entre 2.0 et 10.0
- `music_volume` doit être entre 0.0 et 1.0

Le job passe en statut `processing` et le pipeline démarre automatiquement. L'ordre des segments dans le tableau définit l'ordre du montage (pas la position d'upload).

**Réponse (200)** : `JobResponse`

---

### Schémas de réponse

#### JobResponse

```json
{
  "id": "uuid",
  "status": "pending",
  "progress": 0,
  "title": "Mon montage",
  "description": null,
  "estimated_cost": null,
  "actual_cost": null,
  "output_url": null,
  "error_message": null,
  "webhook_url": null,
  "voiceover_text": "Texte de voix off...",
  "music_prompt": "musique douce et inspirante",
  "include_music": true,
  "custom_music_path": null,
  "transition_type": "crossfade",
  "montage_plan": null,
  "created_at": "2026-01-01T00:00:00",
  "updated_at": "2026-01-01T00:00:00",
  "photo_count": 5
}
```

**Statuts possibles** : `pending` → `awaiting_approval` → `processing` → `completed` / `failed`

#### PhotoResponse

```json
{
  "id": "uuid",
  "job_id": "uuid",
  "filename": "generated-uuid.jpg",
  "original_filename": "photo1.jpg",
  "position": 0,
  "vision_labels": [...],
  "vision_description": "...",
  "vision_objects": [...],
  "created_at": "2026-01-01T00:00:00"
}
```

#### PhotoAnalysisResponse

```json
{
  "photo_id": "uuid",
  "filename": "photo1.jpg",
  "vision_labels": [...],
  "vision_description": "...",
  "vision_objects": [...]
}
```

---

## Pipeline de traitement

Quand un job est lancé via `POST /process`, le worker exécute ces étapes :

### 1. Analyse Google Vision

Pour chaque photo du job :
- Envoi de l'image à l'API Google Cloud Vision
- Détection des labels (ex: "sunset", "beach", "person") et objets localisés
- Génération automatique d'un prompt d'animation adapté au contenu (mouvements naturels : vagues, vent, marche...)

### 2. Génération audio (en parallèle)

Deux tâches lancées simultanément via `asyncio.gather` :
- **Voix off** : envoi du `voiceover_text` à ElevenLabs TTS (modèle `eleven_multilingual_v2`, format MP3 44.1kHz 128kbps)
- **Musique** : fichier custom uploadé (prioritaire) OU génération Suno via Kie.ai (`music_prompt`, instrumental, modèle V4_5, avec retry 3× et polling timeout 5 min)

### 3. Animation Kie.ai

Pour chaque photo, séquentiellement :
- Upload de l'image en base64 vers Kie.ai → récupération d'une URL publique
- Envoi à l'API Kie.ai (`kling-2.6/image-to-video`, 5 ou 10 secondes par clip)
- Durée du clip : `"5"` si `duration_seconds < 6`, sinon `"10"` (via plan de montage)
- Authentification Bearer token (clé API unique)
- Polling du statut toutes les 5 secondes (timeout 5 minutes, 3 retries globaux)
- Téléchargement du clip MP4 résultant
- Si un plan de montage est fourni, les photos sont animées dans l'ordre du plan

### 4. Assemblage MoviePy/FFmpeg

- Chargement de tous les clips vidéo
- Redimensionnement à la résolution configurée (1920×1080 par défaut)
- Ajustement de la vitesse si durée cible ≠ durée du clip (via `MultiplySpeed`)
- Application des transitions (`crossfade` avec 0.5s de fondu, ou `cut` direct)
- Mixage audio :
  - La durée finale = max(durée vidéo, durée voix off) pour couvrir tout l'audio
  - Musique en boucle si plus courte, coupée si plus longue, fade out 3s
  - Volume musique par segment si plan de montage (sinon 20% global sous la voix off)
- Export en MP4 (codec libx264, 30 FPS par défaut)

### 5. Finalisation

- Calcul du coût réel (même formule que l'estimation)
- Mise à jour du job : `status=completed`, `progress=100`, `output_url`, `actual_cost`
- Envoi du webhook n8n si `webhook_url` est configuré

### Suivi de progression

Le champ `progress` (0-100%) est mis à jour en base à chaque sous-étape. Le frontend le récupère par polling `GET /jobs/{id}` toutes les 3 secondes.

Formule : `progress = (étape_courante / total_étapes) × 100`

Total étapes = `(photos × 2) + 3` (analyse + animation par photo, + audio + assemblage + finalisation)

### Gestion des erreurs

En cas d'échec à n'importe quelle étape :
- Une nouvelle session DB est ouverte pour garantir le commit
- Le job passe en `status=failed` avec `error_message`
- Le webhook est envoyé avec le statut `failed`

---

## Variables d'environnement

Toutes les variables sont configurées dans le fichier `.env` à la racine du dossier `backend/`.

### Application

| Variable | Défaut | Description |
|----------|--------|-------------|
| `APP_ENV` | `development` | Environnement (`development`, `production`) |
| `API_HOST` | `0.0.0.0` | Adresse d'écoute du serveur |
| `API_PORT` | `8000` | Port du serveur |
| `FRONTEND_URL` | `http://localhost:5173` | URL du frontend (CORS) |
| `API_KEY` | _(vide)_ | Clé API pour l'authentification. Si vide, l'auth est désactivée (mode dev) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/app.db` | URL de connexion SQLite |

### Services externes

| Variable | Défaut | Description |
|----------|--------|-------------|
| `KIE_API_KEY` | _(vide)_ | Clé API Kie.ai (proxy Kling 2.6) |
| `ELEVENLABS_API_KEY` | _(vide)_ | Clé API ElevenLabs |
| `ELEVENLABS_VOICE_ID` | _(vide)_ | ID de la voix à utiliser pour le TTS |
| `GOOGLE_APPLICATION_CREDENTIALS` | _(vide)_ | Chemin vers le fichier JSON du service account Google Cloud |

### Tarification

Ces valeurs servent à l'estimation des coûts avant lancement. Ajustez-les selon vos tarifs réels.

| Variable | Défaut | Description |
|----------|--------|-------------|
| `KIE_COST_PER_CLIP` | `0.125` | Coût par clip animé Kie.ai en USD |
| `ELEVENLABS_COST_PER_1K_CHARS` | `0.30` | Coût par 1000 caractères de voix off en USD |
| `KIE_SUNO_COST_PER_GENERATION` | `0.06` | Coût par génération musicale Suno (via Kie.ai) en USD |
| `GOOGLE_VISION_COST_PER_IMAGE` | `0.0015` | Coût par analyse d'image en USD |

**Formule de calcul** :
```
total = (nb_photos × KIE_COST_PER_CLIP)
      + (nb_photos × GOOGLE_VISION_COST_PER_IMAGE)
      + (nb_caractères / 1000 × ELEVENLABS_COST_PER_1K_CHARS)
      + (KIE_SUNO_COST_PER_GENERATION si musique incluse)
```

**Exemple** : 10 photos, 500 caractères de voix off, musique Suno incluse :
```
= (10 × 0.125) + (10 × 0.0015) + (0.5 × 0.30) + 0.06
= 1.25 + 0.015 + 0.15 + 0.06
= 1.475 USD
```

### Vidéo output

| Variable | Défaut | Description |
|----------|--------|-------------|
| `VIDEO_WIDTH` | `1920` | Largeur de la vidéo finale en pixels |
| `VIDEO_HEIGHT` | `1080` | Hauteur de la vidéo finale en pixels |
| `VIDEO_FPS` | `30` | Images par seconde |
| `VIDEO_CODEC` | `libx264` | Codec vidéo FFmpeg |

---

## Flux n8n recommandés

L'application est conçue pour être pilotée par n8n via l'API REST. Deux workflows possibles :

### Workflow A — Mode simple (sans plan de montage)

```
[Trigger] → [Créer Job] → [Uploader Photos] → [Estimer] → [Approuver] → [Lancer] → [Attendre] → [Résultat]
```

Les photos sont montées dans l'ordre d'upload, durée fixe 5s par clip, volume musique global.

### Workflow B — Mode avancé (avec plan de montage n8n)

```
[Trigger] → [Créer Job] → [Uploader Photos] → [Récupérer Analyses] → [Construire Plan] → [Soumettre Plan] → [Attendre] → [Résultat]
```

n8n récupère les analyses Vision, construit un plan de montage intelligent (ordre, durées, volumes), et le soumet. Le pipeline se lance automatiquement.

### Détail des nœuds

**1. Trigger** (Webhook, Schedule, ou autre)
- Déclenche le workflow avec les paramètres du montage

**2. HTTP Request — Créer le job**
```
POST http://votre-serveur:8000/api/v1/jobs/
Headers: X-Api-Key: votre_clé
Body:
{
  "title": "Montage vacances",
  "voiceover_text": "Nos plus beaux souvenirs de vacances...",
  "music_prompt": "musique douce et nostalgique",
  "include_music": true,
  "transition_type": "crossfade",
  "webhook_url": "https://votre-n8n.com/webhook/video-done"
}
```
→ Récupérer `job_id` de la réponse

**3. HTTP Request × N — Uploader les photos**
Pour chaque photo (boucle) :
```
POST http://votre-serveur:8000/api/v1/jobs/{job_id}/photos/
Headers: X-Api-Key: votre_clé
Content-Type: multipart/form-data
Body: file = <photo.jpg>
```
→ L'analyse Google Vision est exécutée automatiquement à l'upload

**4a. Mode simple — Estimer, approuver, lancer**
```
POST /api/v1/jobs/{job_id}/estimate        → CostEstimate (passe en awaiting_approval)
POST /api/v1/jobs/{job_id}/approve         → Body: {"approved": true}
POST /api/v1/jobs/{job_id}/process         → Lance le pipeline
```

**4b. Mode avancé — Récupérer les analyses Vision**
```
GET http://votre-serveur:8000/api/v1/jobs/{job_id}/photos/analysis
Headers: X-Api-Key: votre_clé
```
→ Retourne les labels, objets et descriptions Vision de chaque photo.
n8n peut utiliser ces données pour construire un plan de montage intelligent (ordre narratif, durées adaptées au contenu, volumes musicaux).

**5b. Mode avancé — Soumettre le plan de montage**
```
POST http://votre-serveur:8000/api/v1/jobs/{job_id}/montage-plan
Headers: X-Api-Key: votre_clé
Body:
[
  {"photo_id": "uuid-1", "segment_text": "Le salon lumineux", "duration_seconds": 7.5, "music_volume": 0.3},
  {"photo_id": "uuid-2", "segment_text": "La cuisine moderne", "duration_seconds": 5.0, "music_volume": 0.8}
]
```
→ Le pipeline se lance automatiquement (pas besoin d'appeler `/estimate`, `/approve`, `/process`)

**6. Attendre le résultat (deux options)**

**Option A — Webhook (recommandé)** :
- Utiliser un nœud Webhook Trigger dans un workflow séparé
- L'app envoie un POST à `webhook_url` quand le job est terminé :
```json
{
  "job_id": "uuid",
  "status": "completed",
  "output_url": "outputs/uuid/final.mp4",
  "actual_cost": 1.475,
  "error_message": null
}
```

**Option B — Polling** :
- Boucle avec Wait (10s) + HTTP Request `GET /jobs/{job_id}`
- Vérifier `status == "completed"` ou `status == "failed"`

**7. Récupérer la vidéo**
- Le champ `output_url` contient le chemin du fichier sur le serveur
- Servir le fichier via un reverse proxy ou un endpoint statique

---

## Lancer en local

### Pré-requis

- Python 3.12+
- Node.js 20+
- FFmpeg installé et dans le PATH

### Backend

```bash
cd backend

# Créer l'environnement virtuel
python -m venv .venv
source .venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt

# Copier et configurer les variables d'environnement
cp ../.env.example .env
# Éditer .env avec vos clés API

# Créer la base de données
alembic upgrade head

# Lancer le serveur
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend

# Installer les dépendances
npm install

# Lancer le serveur de développement
npm run dev
```

Le frontend est accessible sur `http://localhost:5173`, le backend sur `http://localhost:8000`.

Documentation API interactive (Swagger) : `http://localhost:8000/docs`

---

## Déploiement VPS

### 1. Pré-requis serveur

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install -y python3.12 python3.12-venv nodejs npm ffmpeg nginx certbot python3-certbot-nginx
```

### 2. Cloner le projet

```bash
cd /opt
git clone <repo-url> video-montage-app
cd video-montage-app
```

### 3. Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configurer l'environnement
cp ../.env.example .env
nano .env  # Remplir toutes les clés API + API_KEY pour la sécurité

# Initialiser la base
alembic upgrade head

# Créer les dossiers nécessaires
mkdir -p data uploads outputs
```

### 4. Frontend (build statique)

```bash
cd /opt/video-montage-app/frontend
npm install
npm run build
# Le build est dans frontend/dist/
```

### 5. Service systemd (backend)

Créer `/etc/systemd/system/video-montage.service` :

```ini
[Unit]
Description=Video Montage API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/video-montage-app/backend
Environment=PATH=/opt/video-montage-app/backend/.venv/bin:/usr/bin
ExecStart=/opt/video-montage-app/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable video-montage
sudo systemctl start video-montage
```

### 6. Configuration Nginx

Créer `/etc/nginx/sites-available/video-montage` :

```nginx
server {
    listen 80;
    server_name votre-domaine.com;

    # Frontend (fichiers statiques)
    root /opt/video-montage-app/frontend/dist;
    index index.html;

    # SPA: toutes les routes vers index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy API vers le backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 10M;
    }

    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8000;
    }

    # Servir les vidéos générées
    location /outputs/ {
        alias /opt/video-montage-app/backend/outputs/;
        add_header Content-Disposition "attachment";
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/video-montage /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 7. HTTPS avec Let's Encrypt

```bash
sudo certbot --nginx -d votre-domaine.com
```

### 8. Variables d'environnement production

Dans le `.env` du backend, modifier :

```env
APP_ENV=production
FRONTEND_URL=https://votre-domaine.com
API_KEY=une_clé_secrète_longue_et_aléatoire
```

### 9. Vérification

```bash
# Vérifier que le backend tourne
curl http://localhost:8000/health

# Vérifier le service
sudo systemctl status video-montage

# Voir les logs
sudo journalctl -u video-montage -f
```
