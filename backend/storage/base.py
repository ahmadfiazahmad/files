"""
Storage interface. save_file() is the ONLY function callers use - its
internals switch between local filesystem (dev) and Supabase Storage (prod)
based on settings.storage_backend, so no calling code needs to change when
you deploy.
"""
import os
import uuid
from pathlib import Path
from config import settings


async def save_file(investigation_id: str, filename: str, contents: bytes) -> str:
    if settings.storage_backend == "supabase":
        return await _save_to_supabase(investigation_id, filename, contents)
    return _save_to_local(investigation_id, filename, contents)


def _save_to_local(investigation_id: str, filename: str, contents: bytes) -> str:
    upload_dir = Path(settings.local_upload_dir) / investigation_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(filename).suffix
    unique_name = f"{uuid.uuid4()}{ext}"
    file_path = upload_dir / unique_name

    with open(file_path, "wb") as f:
        f.write(contents)

    return str(file_path)


async def _save_to_supabase(investigation_id: str, filename: str, contents: bytes) -> str:
    """
    Production path. Requires SUPABASE_URL / SUPABASE_SERVICE_KEY / SUPABASE_BUCKET
    to be set. Implemented separately so local dev never needs the supabase client
    installed until deployment.
    """
    from supabase import create_client  # imported lazily - only needed in prod

    supabase = create_client(settings.supabase_url, settings.supabase_service_key)
    ext = Path(filename).suffix
    unique_name = f"{investigation_id}/{uuid.uuid4()}{ext}"

    supabase.storage.from_(settings.supabase_bucket).upload(unique_name, contents)
    return unique_name
