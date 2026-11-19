---
title: InfectionDownloader
emoji: ☣️
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# ☣️ InfectionDownloader

Página web para descargar videos en **MP4** (eligiendo la resolución) o audio en **MP3** (eligiendo la calidad: 128, 192, 256 o 320 kbps) desde YouTube, X/Twitter, Facebook, Instagram, TikTok, Reddit, Vimeo, Twitch, SoundCloud y más de 1000 sitios.

**Stack:** FastAPI + [yt-dlp](https://github.com/yt-dlp/yt-dlp) + ffmpeg, empaquetado en Docker. Todo es gratis y de código abierto.

---

## Correr en tu PC

Requisitos: Python 3.10+ y [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) en el PATH (para YouTube también conviene [Deno](https://deno.com/)).

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app:app --port 7860
```

Abre http://localhost:7860

O con Docker:

```bash
docker build -t infection-downloader .
docker run -p 7860:7860 infection-downloader
```

---

## Desplegar gratis en Hugging Face Spaces (recomendado)

Plan gratuito: 2 vCPU, 16 GB de RAM, sin tarjeta de crédito.

1. Crea una cuenta en https://huggingface.co
2. Ve a **New → Space**, ponle de nombre `InfectionDownloader`, elige **Docker → Blank** y visibilidad **Public**.
3. Crea un token con permiso **Write** en https://huggingface.co/settings/tokens
4. En tu repo de GitHub entra a **Settings → Secrets and variables → Actions**:
   - En **Secrets** crea `HF_TOKEN` con el token.
   - En **Variables** crea `HF_SPACE` con `tu-usuario-hf/InfectionDownloader`.
5. Haz push a `main` (o corre el workflow a mano en **Actions**). GitHub sube el código al Space y este se construye solo.

Tu página queda en `https://tu-usuario-hf-infectiondownloader.hf.space`.

El workflow también se ejecuta **cada lunes** para reconstruir con la última versión de yt-dlp, porque los sitios cambian seguido y yt-dlp se actualiza para seguirles el ritmo.

## Alternativa: Render (gratis)

1. Entra a https://render.com con tu cuenta de GitHub.
2. **New → Blueprint** y elige este repo (usa `render.yaml`).

Nota: en el plan gratis el servidor se apaga tras 15 minutos sin uso y tarda unos 50 segundos en volver a encender. Tiene 512 MB de RAM, así que los videos 4K largos pueden fallar.

---

## Configuración (variables de entorno)

| Variable | Por defecto | Descripción |
|---|---|---|
| `MAX_CONCURRENT_DOWNLOADS` | `2` | Descargas simultáneas |
| `MAX_DURATION_SECONDS` | `10800` | Duración máxima del video (3 h) |
| `JOB_TTL_SECONDS` | `1800` | Tiempo que se guardan los archivos antes de borrarse |
| `YTDLP_COOKIES` | — | Contenido de un `cookies.txt` (ver abajo) |

### YouTube bloqueado ("Sign in to confirm you're not a bot")

YouTube suele bloquear las IPs de servidores en la nube. Para solucionarlo:

1. Instala en tu navegador la extensión **"Get cookies.txt LOCALLY"**.
2. Inicia sesión en YouTube con una **cuenta secundaria** (no la principal).
3. Exporta las cookies de youtube.com.
4. Pega todo el contenido del archivo como secret `YTDLP_COOKIES` en tu Space (**Settings → Variables and secrets → New secret**) o en Render (**Environment**).

---

## API

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/info` | `{ "url": "..." }` → título, miniatura y resoluciones disponibles |
| `POST` | `/api/download` | `{ "url": "...", "type": "mp4"\|"mp3", "quality": 720 }` → `job_id` |
| `GET` | `/api/progress/{job_id}` | Estado y porcentaje de la descarga |
| `GET` | `/api/file/{job_id}` | Descarga el archivo terminado |
| `GET` | `/api/health` | Estado del servidor |

---

## Aviso legal

Herramienta para uso personal. Descarga solo contenido propio, de dominio público o con permiso del autor, y respeta los términos de servicio de cada plataforma.

## Licencia

MIT
