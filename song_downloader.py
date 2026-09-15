from dataclasses import dataclass
from pathlib import Path

import os
import yt_dlp
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class DownloadedSong:
    path: Path
    title: str


def download_song(
    query: str,
    destination: str | Path = "audio"
) -> DownloadedSong:

    output_stem = Path(destination).with_suffix("")
    output_stem.parent.mkdir(parents=True, exist_ok=True)

    cookies_file = Path(__file__).parent / "cookies.txt"

    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
        "noplaylist": True,
        "outtmpl": f"{output_stem}.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "nopart": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(
            f"ytsearch1:{query}",
            download=True,
        )

    entries = result.get("entries") if isinstance(result, dict) else None
    first_result = entries[0] if entries else result

    downloaded_files = [
        path
        for path in output_stem.parent.glob(f"{output_stem.name}.*")
        if path.is_file() and not path.name.endswith(".part")
    ]

    if not first_result or len(downloaded_files) != 1:
        raise RuntimeError("No playable audio was found for that search.")

    return DownloadedSong(
        path=downloaded_files[0],
        title=first_result.get("title") or query,
    )


if __name__ == "__main__":
    download_song("Shape of You Ed Sheeran")