import os
import uuid
import threading
import tempfile
import shutil
import socket
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

MODEL_SIZE = os.environ.get("WHISPER_MODEL", "large-v3")
DEVICE = os.environ.get("WHISPER_DEVICE", "auto")
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="TranscribeAI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

model = None
model_status: Dict[str, Any] = {"loaded": False, "loading": False, "error": None, "device": None, "model": MODEL_SIZE}
jobs: Dict[str, Any] = {}
executor = ThreadPoolExecutor(max_workers=2)


def load_whisper_model():
    global model, model_status
    model_status["loading"] = True
    try:
        from faster_whisper import WhisperModel
        import torch

        if DEVICE == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = DEVICE

        compute_type = "float16" if device == "cuda" else "int8"
        logger.info(f"Cargando Whisper {MODEL_SIZE} en {device} ({compute_type})...")
        model = WhisperModel(MODEL_SIZE, device=device, compute_type=compute_type)
        model_status.update({"loaded": True, "loading": False, "device": device, "error": None})
        logger.info(f"Modelo listo en {device}")
    except Exception as e:
        model_status.update({"loaded": False, "loading": False, "error": str(e)})
        logger.error(f"Error al cargar modelo: {e}")


def format_time_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(segments):
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(f"{i}\n{format_time_srt(seg['start'])} --> {format_time_srt(seg['end'])}\n{seg['text']}\n")
    return "\n".join(lines)


def run_transcription(job_id: str, file_path: str, language: Optional[str]):
    try:
        jobs[job_id].update({"status": "processing", "progress": 5, "message": "Iniciando transcripción..."})

        lang = None if language == "auto" else language
        segments_gen, info = model.transcribe(
            file_path,
            language=lang,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        detected_lang = info.language
        duration = info.duration or 1
        jobs[job_id].update({"detected_language": detected_lang, "message": f"Transcribiendo ({detected_lang.upper()})...", "progress": 10})

        full_text = []
        segments_list = []

        for segment in segments_gen:
            text = segment.text.strip()
            if text:
                full_text.append(text)
                segments_list.append({"start": round(segment.start, 2), "end": round(segment.end, 2), "text": text})
            jobs[job_id]["progress"] = min(95, int(10 + (segment.end / duration) * 85))

        jobs[job_id].update({
            "status": "done",
            "progress": 100,
            "message": "¡Transcripción completada!",
            "result": {
                "text": "\n".join(full_text),
                "segments": segments_list,
                "language": detected_lang,
                "duration": round(duration, 1),
            },
        })
        logger.info(f"Job {job_id} completado — {len(segments_list)} segmentos")

    except Exception as e:
        logger.error(f"Error en transcripción {job_id}: {e}")
        jobs[job_id].update({"status": "error", "error": str(e), "message": f"Error: {e}"})
    finally:
        try:
            os.unlink(file_path)
        except Exception:
            pass


@app.on_event("startup")
async def startup():
    threading.Thread(target=load_whisper_model, daemon=True).start()


@app.get("/api/health")
async def health():
    return model_status


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = Form("auto")):
    if not model_status["loaded"]:
        detail = "El modelo está cargando, espera un momento" if model_status["loading"] else f"Modelo no disponible: {model_status['error']}"
        raise HTTPException(503, detail)

    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=UPLOAD_DIR)
    try:
        shutil.copyfileobj(file.file, tmp)
        tmp.close()
    except Exception as e:
        tmp.close()
        os.unlink(tmp.name)
        raise HTTPException(500, f"Error al guardar archivo: {e}")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "progress": 0, "message": "En cola...", "filename": file.filename or "video"}
    executor.submit(run_transcription, job_id, tmp.name, language)
    logger.info(f"Job {job_id} creado para '{file.filename}' idioma='{language}'")
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job no encontrado")
    j = jobs[job_id]
    return {"status": j["status"], "progress": j.get("progress", 0), "message": j.get("message", ""), "detected_language": j.get("detected_language")}


@app.get("/api/result/{job_id}")
async def get_result(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job no encontrado")
    j = jobs[job_id]
    if j["status"] != "done":
        raise HTTPException(400, "Transcripción no completada")
    return j["result"]


@app.get("/api/download/{job_id}")
async def download_result(job_id: str, fmt: str = "txt"):
    if job_id not in jobs:
        raise HTTPException(404, "Job no encontrado")
    j = jobs[job_id]
    if j["status"] != "done":
        raise HTTPException(400, "Transcripción no completada")

    result = j["result"]
    stem = Path(j.get("filename", "transcripcion")).stem

    if fmt == "srt":
        content = generate_srt(result["segments"])
        filename = f"{stem}.srt"
    else:
        content = result["text"]
        filename = f"{stem}.txt"

    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "tu-ip-local"

    print(f"\n{'='*52}")
    print(f"  TranscribeAI — Servidor de Transcripción")
    print(f"{'='*52}")
    print(f"  Local :  http://localhost:8000")
    print(f"  Red   :  http://{local_ip}:8000")
    print(f"  Modelo:  {MODEL_SIZE}  |  GPU auto-detect")
    print(f"{'='*52}\n")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
