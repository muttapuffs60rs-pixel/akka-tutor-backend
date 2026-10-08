"""Download only images from this application's Supabase storage bucket."""

from urllib.parse import unquote, urlsplit

import requests
from fastapi import HTTPException

MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def validate_image_url(url: str, supabase_url: str) -> str:
    source = urlsplit(supabase_url)
    try:
        target = urlsplit(url)
        valid_origin = (
            source.scheme == target.scheme == "https"
            and source.hostname is not None
            and target.hostname == source.hostname
            and target.port in (None, 443)
            and target.username is None
            and target.password is None
        )
        path = unquote(target.path)
        prefix = "/storage/v1/object/public/chat-images/chat_uploads/"
        valid_path = (
            path.startswith(prefix)
            and len(path) > len(prefix)
            and not any(part in (".", "..") for part in path.split("/"))
            and "\\" not in path
            and "%" not in path
        )
    except ValueError:
        valid_origin = valid_path = False
    if not valid_origin or not valid_path or target.query or target.fragment:
        raise HTTPException(status_code=400, detail="Use an image uploaded through the app")
    return url


def download_chat_image(url: str, supabase_url: str) -> tuple[bytes, str]:
    url = validate_image_url(url, supabase_url)
    try:
        # Redirects could escape the approved storage origin. Never follow them.
        with requests.get(url, timeout=(5, 15), stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Uploaded image is unavailable")
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime not in IMAGE_TYPES:
                raise HTTPException(status_code=400, detail="Upload a JPEG, PNG, or WebP image")
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    raise HTTPException(status_code=413, detail="Image must be 5 MB or smaller")
                chunks.append(chunk)
            if not size:
                raise HTTPException(status_code=400, detail="Uploaded image is empty")
            return b"".join(chunks), mime
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail="Could not download the uploaded image") from exc
