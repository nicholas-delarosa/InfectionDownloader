"""InfectionDownloader - descarga videos y audio de casi cualquier sitio web."""

import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
WORK_DIR = Path(tempfile.gettempdir()) / "infection-downloader"
WORK_DIR.mkdir(parents=True, exist_ok=True)

MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
MAX_DURATION = int(os.getenv("MAX_DURATION_SECONDS", str(3 * 60 * 60)))
JOB_TTL = int(os.getenv("JOB_TTL_SECONDS", str(30 * 60)))
AUDIO_BITRATES = [128, 192, 256, 320]

download_slots = threading.Semaphore(MAX_CONCURRENT)
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def _cookie_file() -> str | None:
    """Permite pasar cookies (formato Netscape) por variable de entorno YTDLP_COOKIES."""
    content = os.getenv("YTDLP_COOKIES", "").strip()
    if not content:
        return None
    path = WORK_DIR / "cookies.txt"
    if not path.exists():
        path.write_text(content + "\n", encoding="utf-8")
    return str(path)


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    cookies = _cookie_file()
    if cookies:
        opts["cookiefile"] = cookies
    return opts


def _clean_error(exc: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
    msg = msg.replace("ERROR: ", "").strip()
    msg = re.sub(r"^\[[^\]]+\]\s*[^:]*:\s*", "", msg)
    if "No video could be found" in msg or "no video" in msg.lower():
        return "No se encontró ningún video en ese enlace."
    if "Sign in to confirm" in msg or "not a bot" in msg:
        return ("YouTube bloqueó la petición desde este servidor. "
                "Intenta de nuevo más tarde o configura cookies (ver README).")
    if "Unsupported URL" in msg:
        return "Ese enlace no es compatible o no contiene un video."
    if "Private" in msg or "private" in msg:
        return "El video es privado o requiere iniciar sesión."
    return msg[:300] or "No se pudo procesar el enlace."


def _safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name or "video")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] or "video"


def _cleanup_loop() -> None:
    while True:
        time.sleep(60)
        now = time.time()
        with jobs_lock:
            expired = [jid for jid, j in jobs.items() if now - j["created"] > JOB_TTL]
            for jid in expired:
                shutil.rmtree(jobs[jid]["dir"], ignore_errors=True)
                del jobs[jid]


threading.Thread(target=_cleanup_loop, daemon=True).start()

app = FastAPI(title="InfectionDownloader", docs_url=None, redoc_url=None)


class InfoRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2000)


class DownloadRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2000)
    type: Literal["mp4", "mp3"]
    quality: int = Field(gt=0, le=4320)


def _validate_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        raise HTTPException(400, "Pega un enlace válido que empiece con http:// o https://")
    return url


def _extract(url: str) -> dict:
    try:
        with yt_dlp.YoutubeDL(_base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise HTTPException(422, _clean_error(exc)) from exc
    if info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if not entries:
            raise HTTPException(422, "No se encontró ningún video en ese enlace.")
        info = entries[0]
    return info


@app.post("/api/info")
def get_info(req: InfoRequest):
    url = _validate_url(req.url)
    info = _extract(url)

    heights = sorted(
        {
            int(f["height"])
            for f in info.get("formats") or []
            if f.get("height") and f.get("vcodec") not in (None, "none")
        },
        reverse=True,
    )
    if not heights and info.get("height"):
        heights = [int(info["height"])]

    has_video = bool(heights) or info.get("vcodec") not in (None, "none")
    max_abr = max(
        [f.get("abr") or 0 for f in info.get("formats") or []] + [info.get("abr") or 0]
    )

    return {
        "url": info.get("webpage_url") or url,
        "title": info.get("title") or "Sin título",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "site": info.get("extractor_key") or info.get("extractor") or "",
        "video_heights": heights,
        "has_video": has_video,
        "audio_bitrates": AUDIO_BITRATES,
        "source_audio_kbps": round(max_abr) if max_abr else None,
    }


def _run_job(job_id: str, url: str, kind: str, quality: int) -> None:
    job = jobs[job_id]
    out_dir = Path(job["dir"])

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            job["status"] = "downloading"
            job["progress"] = round(done / total * 100, 1) if total else None
            job["speed"] = d.get("speed")
            job["eta"] = d.get("eta")
        elif d["status"] == "finished":
            job["progress"] = 100

    def pp_hook(d):
        if d["status"] == "started":
            job["status"] = "processing"

    opts = _base_opts() | {
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "match_filter": yt_dlp.utils.match_filter_func(f"duration <=? {MAX_DURATION}"),
    }

    if kind == "mp4":
        opts |= {
            "format": "bv*+ba/b",
            "format_sort": [f"res:{quality}", "vcodec:h264", "acodec:aac", "ext:mp4:m4a"],
            "merge_output_format": "mp4",
            "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        }
    else:
        opts |= {
            "format": "ba/b",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                 "preferredquality": str(quality)},
                {"key": "FFmpegMetadata"},
            ],
        }

    job["status"] = "queued"
    with download_slots:
        job["status"] = "starting"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            if info.get("_type") == "playlist":
                info = next(e for e in info["entries"] if e)

            files = [p for p in out_dir.iterdir() if p.suffix.lower() == f".{kind}"]
            if not files:
                if info.get("duration") and info["duration"] > MAX_DURATION:
                    raise RuntimeError("El video es demasiado largo para este servidor.")
                raise RuntimeError("No se generó el archivo. Prueba otra calidad.")

            suffix = f" ({quality}p)" if kind == "mp4" else f" ({quality}kbps)"
            job["file"] = str(files[0])
            job["filename"] = _safe_filename(info.get("title")) + suffix + f".{kind}"
            job["size"] = files[0].stat().st_size
            job["status"] = "done"
            job["progress"] = 100
        except Exception as exc:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = _clean_error(exc)


@app.post("/api/download")
def start_download(req: DownloadRequest):
    url = _validate_url(req.url)
    if req.type == "mp3" and req.quality not in AUDIO_BITRATES:
        raise HTTPException(400, "Calidad de audio no válida.")

    job_id = uuid.uuid4().hex
    job_dir = WORK_DIR / job_id
    job_dir.mkdir()
    with jobs_lock:
        jobs[job_id] = {
            "created": time.time(), "dir": str(job_dir), "status": "queued",
            "progress": 0, "speed": None, "eta": None, "error": None,
            "file": None, "filename": None, "size": None,
        }
    threading.Thread(target=_run_job, args=(job_id, url, req.type, req.quality),
                     daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/progress/{job_id}")
def progress(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Descarga no encontrada o expirada.")
    return {k: job[k] for k in ("status", "progress", "speed", "eta", "error", "filename", "size")}


@app.get("/api/file/{job_id}")
def get_file(job_id: str):
    job = jobs.get(job_id)
    if not job or job["status"] != "done" or not job["file"]:
        raise HTTPException(404, "Archivo no disponible.")
    media = "video/mp4" if job["file"].endswith(".mp4") else "audio/mpeg"
    return FileResponse(job["file"], media_type=media, filename=job["filename"])


@app.get("/api/health")
def health():
    return {"ok": True, "yt_dlp": yt_dlp.version.__version__}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
