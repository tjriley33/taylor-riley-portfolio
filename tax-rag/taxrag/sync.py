"""S3 sync for the index and raw PDFs, so an ECS task (or your laptop) can pull a built index
and an ingestion task can push one. Layout in the bucket:
  s3://<bucket>/<prefix>/taxrag.sqlite          the structured store (single file)
  s3://<bucket>/<prefix>/raw/<sha256>.pdf        immutable originals (content-addressed)
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .config import settings


def _bucket_prefix() -> tuple[str, str]:
    bucket = os.environ.get("TAXRAG_S3_BUCKET")
    if not bucket:
        raise RuntimeError("set TAXRAG_S3_BUCKET (and optionally TAXRAG_S3_PREFIX)")
    return bucket, os.environ.get("TAXRAG_S3_PREFIX", "taxrag").strip("/")


def push(include_raw: bool = True) -> dict:
    import boto3
    s3 = boto3.client("s3")
    bucket, prefix = _bucket_prefix()
    snap = settings.data_dir / "taxrag.snapshot.sqlite"
    src = sqlite3.connect(settings.sqlite_path)
    dst = sqlite3.connect(snap)
    src.backup(dst)                      # consistent copy even while ingestion writes
    dst.close(); src.close()
    s3.upload_file(str(snap), bucket, f"{prefix}/taxrag.sqlite")
    snap.unlink()
    n = 0
    if include_raw:
        existing = set()
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"{prefix}/raw/"):
            existing |= {o["Key"].rsplit("/", 1)[-1] for o in page.get("Contents", [])}
        for p in settings.raw_dir.glob("*.pdf"):
            if p.name not in existing:
                s3.upload_file(str(p), bucket, f"{prefix}/raw/{p.name}")
                n += 1
    return {"bucket": bucket, "prefix": prefix, "raw_uploaded": n}


def pull(include_raw: bool = True) -> dict:
    import boto3
    s3 = boto3.client("s3")
    bucket, prefix = _bucket_prefix()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    tmp = settings.sqlite_path.with_suffix(".download")
    s3.download_file(bucket, f"{prefix}/taxrag.sqlite", str(tmp))
    tmp.replace(settings.sqlite_path)
    n = 0
    if include_raw:
        settings.raw_dir.mkdir(parents=True, exist_ok=True)
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"{prefix}/raw/"):
            for o in page.get("Contents", []):
                name = o["Key"].rsplit("/", 1)[-1]
                dest = settings.raw_dir / name
                if not dest.exists():
                    s3.download_file(bucket, o["Key"], str(dest))
                    n += 1
    return {"bucket": bucket, "prefix": prefix, "raw_downloaded": n}
