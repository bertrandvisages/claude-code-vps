# CLAUDE.md — Video Montage App

## Description
Application web de génération de montages vidéo à partir de photos animées par IA.
Les photos sont animées via Kie.ai (personnages qui bougent, eau, effets visuels),
puis assemblées avec musique et voix off en une vidéo finale.

## Pipeline de traitement vidéo
```
Photo uploadée
  → Google Vision API (auto-analyse à l'upload)
  → ElevenLabs API (voix off) + Suno/Kie.ai (musique) — en parallèle
  → Kie.ai (animation photo → clip vidéo 5-10s)
  → FFmpeg / MoviePy (assemblage clips + audio → vidéo finale)
```

## Stack technique
- **Frontend** : React + TypeScript + Vite
- **Backend** : Python 3.12 + FastAPI
- **Animation photos** : Kie.ai API (proxy Kling 2.6, clips 5 ou 10s)
- **Assemblage vidéo** : FFmpeg + MoviePy (montage final uniquement)
- **Voix off** : ElevenLabs API (TTS)
- **Musique** : Suno via Kie.ai (instrumental, modèle V4_5) OU fichier audio custom uploadé
- **Analyse photos** : Google Vision API (auto à l'upload)
- **Base de données** : SQLite (aiosqlite) — dev et prod
- **Tâches async** : FastAPI BackgroundTasks (Celery prévu si scaling nécessaire)
- **Déploiement** : VPS Ubuntu 24.04 + Docker + Nginx (Docker = prod uniquement)

## Services externes et clés API
| Service | Variable d'env | Usage | Coût |
|---|---|---|---|
| Kie.ai | `KIE_API_KEY` | Animation photo + musique Suno | Par clip / par génération |
| ElevenLabs | `ELEVENLABS_API_KEY` | Voix off TTS | Par caractère |
| Google Vision | `GOOGLE_APPLICATION_CREDENTIALS` | Analyse contenu photo | Par requête |

## Gestion des coûts
- Chaque job doit **estimer le coût total avant lancement** (nombre de photos × coût Kie.ai + voix off + musique)
- L'estimation est retournée à l'utilisateur/n8n pour validation avant traitement
- Le coût réel est enregistré à la fin du job dans la base de données

## Structure du projet
```
video-montage-app/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app
│   │   ├── config.py         # Settings (pydantic-settings)
│   │   ├── database.py       # SQLAlchemy async + SQLite
│   │   ├── api/              # Routes REST
│   │   ├── models/           # ORM SQLAlchemy
│   │   ├── schemas/          # Pydantic request/response
│   │   ├── services/         # Logique métier
│   │   │   ├── kie_animator.py      # Kie.ai — animation photos (5-10s)
│   │   │   ├── video_assembler.py   # FFmpeg/MoviePy — montage final
│   │   │   ├── voice_generator.py   # ElevenLabs — voix off TTS
│   │   │   ├── music_generator.py   # Suno via Kie.ai — musique instrumentale
│   │   │   ├── photo_analyzer.py    # Google Vision — analyse (auto à l'upload)
│   │   │   ├── cost_estimator.py    # Estimation coût avant lancement
│   │   │   └── job_logger.py        # Logs SSE en temps réel
│   │   ├── workers/          # Tâches async (BackgroundTasks)
│   │   └── utils/
│   └── tests/
├── frontend/                 # React + Vite
└── nginx/                    # Config reverse proxy (prod)
```

## Endpoints API (résumé)

Base URL : `/api/v1` — Auth : header `X-Api-Key`

### Jobs
| Méthode | URL | Description |
|---------|-----|-------------|
| `POST` | `/jobs/` | Créer un job |
| `GET` | `/jobs/?status=` | Lister les jobs (filtre optionnel) |
| `GET` | `/jobs/{id}` | Récupérer un job |
| `DELETE` | `/jobs/{id}` | Supprimer un job |
| `POST` | `/jobs/{id}/estimate` | Estimer le coût (→ awaiting_approval) |
| `POST` | `/jobs/{id}/approve` | Approuver/rejeter (`{approved: bool}`) |
| `POST` | `/jobs/{id}/process` | Lancer le pipeline |
| `GET` | `/jobs/{id}/logs` | Stream SSE des logs en temps réel |
| `POST` | `/jobs/{id}/music` | Upload musique custom (multipart, MP3/WAV, max 50 Mo) |
| `DELETE` | `/jobs/{id}/music` | Supprimer la musique custom |
| `GET` | `/jobs/{id}/photos/analysis` | Analyses Vision de toutes les photos (pour n8n) |
| `POST` | `/jobs/{id}/montage-plan` | Soumettre un plan de montage (lance le pipeline auto) |

### Photos
| Méthode | URL | Description |
|---------|-----|-------------|
| `POST` | `/jobs/{id}/photos/` | Upload photo (multipart, auto-analyse Vision) |
| `GET` | `/jobs/{id}/photos/` | Lister les photos du job |
| `DELETE` | `/jobs/{id}/photos/{photo_id}` | Supprimer une photo |

### Deux workflows
- **Simple** : create → upload photos → estimate → approve → process → poll/webhook
- **Avancé (n8n)** : create → upload photos → GET analysis → POST montage-plan → poll/webhook

## Conventions de développement
- Toujours travailler en mode plan d'abord
- Ne créer/modifier aucun fichier sans validation explicite
- Avancer module par module
- Pas de Docker en dev local — Docker uniquement pour le déploiement VPS
- SQLite uniquement (pas de PostgreSQL)
- BackgroundTasks FastAPI (pas de Celery pour l'instant)
- Commandes dangereuses — toujours demander confirmation manuelle, jamais auto-accepté :
  - `rm -rf`
  - `git push`, `git push --force`
  - `git reset --hard`
  - Toute commande SQL `DROP` ou `TRUNCATE`
  - Toute suppression de fichiers en dehors de `/tmp/`
