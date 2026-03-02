# CLAUDE.md — Video Assembly Service

## Description
Service API d'assemblage vidéo. Reçoit un JSON de montage via n8n,
télécharge les clips et audio depuis Supabase, assemble avec FFmpeg
(concat, speed adjust, ducking audio), et uploade la vidéo finale
vers Supabase Storage.

## Pipeline
```
POST /api/v1/assemble (JSON de montage)
  → Téléchargement clips vidéo depuis Supabase
  → FFmpeg : speed adjust → concat → audio ducking → encode H.264
  → Upload vidéo finale vers Supabase Storage
  → GET /api/v1/jobs/{id}/status → completed + output_url
```

## Stack technique
- **Backend** : Python 3.11 + FastAPI
- **Assemblage vidéo** : FFmpeg (subprocess, pas de MoviePy)
- **Storage** : Supabase Storage (clips source + vidéo finale)
- **Base de données** : SQLite (aiosqlite) — suivi statut jobs
- **Tâches async** : FastAPI BackgroundTasks
- **Déploiement** : Docker (VPS ou Coolify)

## Variables d'environnement
| Variable | Usage |
|---|---|
| `SUPABASE_URL` | URL du projet Supabase |
| `SUPABASE_SERVICE_KEY` | Clé service Supabase (accès Storage) |
| `API_KEY` | Auth header `X-Api-Key` (vide = désactivé) |
| `DATABASE_URL` | SQLite (défaut: `sqlite+aiosqlite:///./data/app.db`) |
| `APP_ENV` | `production` ou `development` |

## Structure du projet
```
video-montage-app/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + lifespan
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   ├── database.py          # SQLAlchemy async + SQLite
│   │   ├── api/
│   │   │   ├── router.py        # Routeur /api/v1
│   │   │   ├── dependencies.py  # Auth X-Api-Key
│   │   │   └── assemble.py      # Endpoints assemblage + status + SSE
│   │   ├── models/
│   │   │   ├── base.py          # DeclarativeBase
│   │   │   └── job.py           # Job (id, status, output_url, error, timestamps)
│   │   ├── schemas/
│   │   │   └── assemble.py      # Pydantic schemas (request/response)
│   │   ├── services/
│   │   │   ├── job_logger.py    # SSE pub/sub in-memory
│   │   │   ├── assembler.py     # FFmpeg : download, speed, concat, ducking
│   │   │   └── supabase.py      # Upload Supabase Storage
│   │   └── workers/
│   │       └── pipeline.py      # Orchestration pipeline assemblage
│   └── requirements.txt
├── Dockerfile
├── .env.example
└── .dockerignore
```

## Endpoints API

Base URL : `/api/v1` — Auth : header `X-Api-Key`

| Méthode | URL | Description |
|---------|-----|-------------|
| `POST` | `/assemble` | Lancer un assemblage (JSON de montage) → 202 |
| `GET` | `/jobs/{id}/status` | Statut du job (processing/completed/failed) |
| `GET` | `/jobs/{id}/logs` | Stream SSE des logs en temps réel |
| `GET` | `/health` | Health check (hors auth) |

### Format JSON `POST /assemble`
```json
{
  "job_id": "uuid",
  "output_filename": "Hotel_Bellevue_Paris.mp4",
  "resolution": "1920x1080",
  "fps": 30,
  "segments": [
    {"order": 1, "video_url": "https://xxx.supabase.co/...", "duration_seconds": 7.5}
  ],
  "audio": {
    "voiceover_url": "https://xxx.supabase.co/.../voiceover.mp3",
    "music_url": "https://xxx.supabase.co/.../music.mp3",
    "music_volume_base": 0.3
  },
  "output_storage": {
    "supabase_bucket": "outputs",
    "supabase_path": "montages/uuid/final.mp4"
  }
}
```

## FFmpeg — Ducking audio
Quand voix off + musique sont présents, le filtre `sidechaincompress`
réduit automatiquement le volume de la musique quand la voix est active.
- `music_volume_base` : volume de la musique quand la voix parle (défaut 0.3)
- Transitions douces 0.5s (attack/release du compresseur)
- Quand silence détecté, musique remonte à son niveau de base

## Conventions de développement
- Toujours travailler en mode plan d'abord
- Ne créer/modifier aucun fichier sans validation explicite
- Avancer module par module
- SQLite uniquement (pas de PostgreSQL)
- BackgroundTasks FastAPI (pas de Celery)
- Commandes dangereuses — toujours demander confirmation manuelle :
  - `rm -rf`
  - `git push`, `git push --force`
  - `git reset --hard`
  - Toute commande SQL `DROP` ou `TRUNCATE`
