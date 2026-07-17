"""Retrait du packshot en fin de video SANS recompresser le film.

Symetrique de packshot_append : on coupe le film juste avant le packshot en
`-c copy` (stream copy) -> le film est copie tel quel, aucune perte, quelques
secondes de traitement au lieu d'un rendu complet.

Pourquoi ce n'est pas juste "duree_totale - duree_packshot" :
le packshot concatene n'est PAS le mp4 brut de packshots/{id}.mp4, c'est une
version RENORMALISEE aux params du film (cf. packshot_append.append_packshot :
scale/crop, -r fps du film, piste audio silencieuse). Sa duree derive donc de
quelques images par rapport au brut, et couper a l'estimation laisserait un
bout de packshot ou mangerait la fin du film.

Parade : le concat pose forcement une IMAGE-CLE au raccord (chaque segment
concatene demarre sur une keyframe). On cherche donc la keyframe la plus proche
de l'estimation et on coupe exactement dessus -> raccord exact a l'image pres,
quelle que soit la derive.
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path

from app.services.assembler import download_file, run_ffmpeg, get_duration

logger = logging.getLogger("uvicorn.error")

# Fenetre de recherche de la keyframe autour de l'estimation. Large assez pour
# absorber la derive de renormalisation (quelques images) sans risquer
# d'attraper la keyframe du GOP precedent/suivant (GOP typique 2-10 s ici).
KEYFRAME_WINDOW_S = 3.0


async def _keyframes_between(path: Path, start: float, end: float) -> list[float]:
    """Timestamps des images-cles du flux video dans [start, end].

    -skip_frame nokey + -show_entries frame=pts_time : ffprobe ne decode que
    les keyframes -> rapide meme sur un film d'une heure. -read_intervals borne
    la lecture a la fenetre utile.
    """
    start = max(0.0, start)
    result = await asyncio.to_thread(
        subprocess.run,
        [
            "ffprobe", "-v", "quiet",
            "-select_streams", "v:0",
            "-skip_frame", "nokey",
            "-show_entries", "frame=pts_time",
            "-read_intervals", f"{start:.3f}%{end:.3f}",
            "-print_format", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    try:
        frames = json.loads(result.stdout or "{}").get("frames", [])
    except json.JSONDecodeError:
        return []
    out = []
    for f in frames:
        ts = f.get("pts_time")
        if ts is None:
            continue
        try:
            v = float(ts)
        except (TypeError, ValueError):
            continue
        if start <= v <= end:
            out.append(v)
    return sorted(out)


async def strip_packshot(video_url: str, packshot_url: str, work_dir: Path) -> Path:
    """Telecharge film+packshot, coupe le packshot de la fin en -c copy.
    Retourne le mp4 du film nu."""
    film = work_dir / "film.mp4"
    packshot = work_dir / "packshot.mp4"
    await download_file(video_url, film)
    await download_file(packshot_url, packshot)

    total_dur = await get_duration(film)
    packshot_dur = await get_duration(packshot)
    if total_dur <= 0:
        raise RuntimeError("Duree du film source illisible")
    if packshot_dur <= 0:
        raise RuntimeError("Duree du packshot illisible")

    estimate = total_dur - packshot_dur
    if estimate <= 1.0:
        raise RuntimeError(
            f"Film ({total_dur:.1f}s) pas plus long que le packshot "
            f"({packshot_dur:.1f}s) : rien a couper. Le film porte-t-il "
            f"vraiment ce packshot ?"
        )

    # Calage sur la keyframe du raccord.
    cut_at = estimate
    kfs = await _keyframes_between(
        film, estimate - KEYFRAME_WINDOW_S, estimate + KEYFRAME_WINDOW_S
    )
    if kfs:
        cut_at = min(kfs, key=lambda k: abs(k - estimate))
        logger.info(
            f"strip_packshot: estimation {estimate:.3f}s -> keyframe {cut_at:.3f}s "
            f"(derive {abs(cut_at - estimate) * 1000:.0f} ms, "
            f"{len(kfs)} keyframes dans la fenetre)"
        )
    else:
        # Pas de keyframe trouvee : on coupe a l'estimation. Le -c copy
        # s'alignera sur le paquet le plus proche, a quelques images pres.
        logger.warning(
            f"strip_packshot: aucune keyframe dans +/-{KEYFRAME_WINDOW_S}s de "
            f"{estimate:.3f}s, coupe a l'estimation"
        )

    out = work_dir / "film_nu.mp4"
    await run_ffmpeg(
        ["-i", str(film), "-to", f"{cut_at:.3f}", "-c", "copy",
         "-movflags", "+faststart", str(out)],
        desc="strip packshot (-c copy, no recompress)",
    )

    # Sanity : la sortie doit exister, ne pas etre vide, et durer a peu pres
    # l'estimation (jamais la duree totale = packshot pas retire).
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError("sortie -c copy vide")
    out_dur = await get_duration(out)
    if out_dur >= total_dur - 0.5:
        raise RuntimeError(
            f"le packshot n'a pas ete retire (total {total_dur:.1f}s, "
            f"sortie {out_dur:.1f}s)"
        )
    if abs(out_dur - cut_at) > 1.0:
        raise RuntimeError(
            f"duree de sortie inattendue ({out_dur:.1f}s, attendu ~{cut_at:.1f}s)"
        )
    logger.info(
        f"strip_packshot: OK ({total_dur:.1f}s -> {out_dur:.1f}s, "
        f"packshot {packshot_dur:.1f}s retire)"
    )
    return out
