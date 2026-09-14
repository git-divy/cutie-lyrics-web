# Lyric Glow

Set `ELEVENLABS_API_KEY` in `.env`, then install the dependencies and start the server:

```powershell
pip install -r requirements.txt
uvicorn transcriber:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) to use the built-in frontend. It previews an uploaded song immediately, calls the API, and highlights each lyric word as the audio plays.

You can also search for a song in the interface. This downloads the first matching YouTube audio result in its original supported format, transcribes it, and starts its player. It does not require FFmpeg. Only download audio you have permission to use.

The API is also available at `POST /transcribe`. Send a `multipart/form-data` request with the audio in the `file` field:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/transcribe" -F "file=@C:\path\to\audio.mp3"
```

The response is the ElevenLabs Scribe transcription JSON, including `text`, `words`, `language_code`, `transcription_id`, and `audio_duration_secs`.
