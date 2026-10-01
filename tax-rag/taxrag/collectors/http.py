"""Polite HTTP client shared by collectors."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import httpx

from ..config import settings

_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            follow_redirects=True,
            timeout=settings.http_timeout,
            headers={"User-Agent": settings.http_user_agent, "Accept": "*/*"},
        )
    return _client


def get_text(url: str, retries: int = 3) -> str:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = client().get(url)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def download(url: str, dest_dir: Path, retries: int = 3) -> tuple[Path, str]:
    """Download to a content-addressed path. Returns (path, sha256)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = client().get(url)
            r.raise_for_status()
            data = r.content
            ctype = r.headers.get("content-type", "")
            if not data.startswith(b"%PDF") and "pdf" not in ctype:
                raise RuntimeError(f"not a PDF (content-type={ctype}, {len(data)} bytes)")
            sha = hashlib.sha256(data).hexdigest()
            path = dest_dir / f"{sha}.pdf"
            if not path.exists():
                tmp = path.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(path)
            return path, sha
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"download {url} failed: {last}")


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
