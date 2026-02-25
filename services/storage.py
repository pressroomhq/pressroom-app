"""Storage abstraction — local disk in dev, Tigris (S3-compatible) in prod.

Usage:
    from services.storage import storage

    # Write bytes
    url = await storage.put("footage/script_1.mp4", data, content_type="video/mp4")

    # Read bytes
    data = await storage.get("footage/script_1.mp4")

    # Get a public/presigned URL
    url = storage.url("renders/script_1.mp4")

    # Delete
    await storage.delete("footage/script_1.mp4")

Set these env vars for Tigris (Fly injects them automatically when you attach Tigris):
    BUCKET_NAME          — Tigris bucket name
    AWS_ACCESS_KEY_ID    — Tigris access key
    AWS_SECRET_ACCESS_KEY — Tigris secret key
    AWS_ENDPOINT_URL_S3  — https://fly.storage.tigris.dev
    AWS_REGION           — auto (Tigris default)
"""

import asyncio
import logging
import os
from pathlib import Path

log = logging.getLogger("pressroom")

# Detect Tigris — Fly injects these automatically when you run `fly storage create`
_BUCKET = os.getenv("BUCKET_NAME", "")
_ENDPOINT = os.getenv("AWS_ENDPOINT_URL_S3", "https://fly.storage.tigris.dev")
_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "")
_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

# Local fallback directory
_LOCAL_DIR = Path(os.getenv("STORAGE_LOCAL_DIR", "/tmp/pressroom-storage"))


def _use_tigris() -> bool:
    return bool(_BUCKET and _ACCESS_KEY and _SECRET_KEY)


def _s3_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=_ENDPOINT,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name=os.getenv("AWS_REGION", "auto"),
    )


class Storage:
    """Thin async wrapper around local disk or Tigris S3."""

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store bytes at key. Returns a URL/path string."""
        if _use_tigris():
            return await asyncio.get_event_loop().run_in_executor(
                None, self._put_s3, key, data, content_type
            )
        else:
            return self._put_local(key, data)

    def _put_s3(self, key: str, data: bytes, content_type: str) -> str:
        client = _s3_client()
        client.put_object(
            Bucket=_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        log.info("storage: uploaded s3://%s/%s (%d bytes)", _BUCKET, key, len(data))
        return self.url(key)

    def _put_local(self, key: str, data: bytes) -> str:
        path = _LOCAL_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        log.info("storage: wrote local %s (%d bytes)", path, len(data))
        return str(path)

    async def get(self, key: str) -> bytes | None:
        """Fetch bytes by key. Returns None if not found."""
        if _use_tigris():
            return await asyncio.get_event_loop().run_in_executor(
                None, self._get_s3, key
            )
        else:
            return self._get_local(key)

    def _get_s3(self, key: str) -> bytes | None:
        try:
            client = _s3_client()
            resp = client.get_object(Bucket=_BUCKET, Key=key)
            return resp["Body"].read()
        except Exception as e:
            log.warning("storage: s3 get failed for %s: %s", key, e)
            return None

    def _get_local(self, key: str) -> bytes | None:
        path = _LOCAL_DIR / key
        if path.exists():
            return path.read_bytes()
        return None

    async def get_to_file(self, key: str, dest: Path) -> bool:
        """Download key to a local file path. Returns True if successful."""
        data = await self.get(key)
        if data is None:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True

    def url(self, key: str) -> str:
        """Return a public URL for a stored object."""
        if _use_tigris():
            # Tigris public URL — bucket must have public-read ACL or use presigned
            return f"{_ENDPOINT}/{_BUCKET}/{key}"
        else:
            return str(_LOCAL_DIR / key)

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        """Return a presigned URL (works even for private buckets)."""
        if _use_tigris():
            client = _s3_client()
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": _BUCKET, "Key": key},
                ExpiresIn=expires,
            )
        return str(_LOCAL_DIR / key)

    async def delete(self, key: str) -> None:
        if _use_tigris():
            await asyncio.get_event_loop().run_in_executor(
                None, self._delete_s3, key
            )
        else:
            path = _LOCAL_DIR / key
            if path.exists():
                path.unlink()

    def _delete_s3(self, key: str) -> None:
        try:
            _s3_client().delete_object(Bucket=_BUCKET, Key=key)
        except Exception as e:
            log.warning("storage: s3 delete failed for %s: %s", key, e)

    @property
    def backend(self) -> str:
        return "tigris" if _use_tigris() else "local"


# Singleton
storage = Storage()
