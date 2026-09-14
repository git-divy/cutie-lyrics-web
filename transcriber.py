import json
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from song_downloader import download_song

load_dotenv()

app = FastAPI(title="Audio Transcription API")
DOWNLOAD_DIR = Path(
    os.getenv(
        "DOWNLOAD_DIR",
        "/tmp/lyric-glow-downloads"
        if os.getenv("VERCEL")
        else Path(__file__).parent / "downloads",
    )
)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_MEDIA_TYPES = {
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


class SongSearch(BaseModel):
    query: str


def create_client() -> ElevenLabs:
    """Create an authenticated ElevenLabs client from the environment."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    return ElevenLabs(api_key=api_key)


async def transcribe(audio: BytesIO) -> dict:
    """Send an in-memory audio file to ElevenLabs without blocking the API loop."""
    try:
        client = create_client()
        transcription = await run_in_threadpool(
            client.speech_to_text.convert,
            file=audio,
            model_id="scribe_v2",
            tag_audio_events=False,
            language_code=None,
            diarize=False,
        )
        return json.loads(transcription.json())
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="The transcription provider could not process the audio."
        ) from exc


@app.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(..., description="Audio file to transcribe"),
) -> JSONResponse:
    """Upload audio and receive the ElevenLabs Scribe transcription JSON."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="An audio file is required.")

    audio = BytesIO(await file.read())
    # The SDK uses the filename extension to help identify the uploaded format.
    audio.name = file.filename

    try:
        return JSONResponse(content=await transcribe(audio))
    finally:
        await file.close()


@app.post("/search-and-transcribe")
async def search_and_transcribe(search: SongSearch) -> JSONResponse:
    """Download the first matching song, then return its timed lyrics and audio URL."""
    query = search.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Enter a song name to search.")
    if len(query) > 200:
        raise HTTPException(status_code=400, detail="Keep the song search under 200 characters.")

    destination = DOWNLOAD_DIR / uuid4().hex
    try:
        song = await run_in_threadpool(download_song, query, destination)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Unable to find or download audio for that song."
        ) from exc

    audio = BytesIO(await run_in_threadpool(song.path.read_bytes))
    audio.name = song.path.name
    payload = await transcribe(audio)
    payload["track"] = {
        "title": song.title,
        "audio_url": f"/downloads/{song.path.name}",
    }
    return JSONResponse(content=payload)


def stream_file_range(path: Path, start: int, length: int):
    """Yield a bounded section of a file for an HTTP byte-range response."""
    with path.open("rb") as audio_file:
        audio_file.seek(start)
        remaining = length
        while remaining:
            chunk = audio_file.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def parse_byte_range(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Return the inclusive start and end offsets for a single valid byte range."""
    if not range_header.startswith("bytes="):
        return None

    requested_range = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
    try:
        start_text, end_text = requested_range.split("-", 1)
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
    except ValueError:
        return None

    if start < 0 or start >= file_size or end < start:
        return None
    return start, min(end, file_size - 1)


@app.get("/downloads/{filename}")
async def stream_downloaded_audio(filename: str, request: Request) -> Response:
    """Serve generated audio with byte ranges, which enables browser seeking."""
    path = DOWNLOAD_DIR / Path(filename).name
    media_type = DOWNLOAD_MEDIA_TYPES.get(path.suffix.lower())
    if not media_type or not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found.")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    common_headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    if not range_header:
        return StreamingResponse(
            stream_file_range(path, 0, file_size),
            media_type=media_type,
            headers={**common_headers, "Content-Length": str(file_size)},
        )

    byte_range = parse_byte_range(range_header, file_size)
    if byte_range is None:
        return Response(
            status_code=416,
            headers={**common_headers, "Content-Range": f"bytes */{file_size}"},
        )

    start, end = byte_range
    content_length = end - start + 1
    return StreamingResponse(
        stream_file_range(path, start, content_length),
        status_code=206,
        media_type=media_type,
        headers={
            **common_headers,
            "Content-Length": str(content_length),
            "Content-Range": f"bytes {start}-{end}/{file_size}",
        },
    )


# The UI is served by this same FastAPI process, so its requests stay on the
# same origin and do not require a separate frontend build server.
app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="frontend",
)
