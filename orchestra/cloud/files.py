"""
orchestra/cloud/files.py
--------------------------
File upload/download pipeline — S3 presigned URLs, multipart upload,
and optional CloudFront CDN delivery.
"""
from __future__ import annotations

__all__ = [
    "CloudFiles",
]

import asyncio
import logging
import mimetypes
import time
from typing import Any

try:
    import boto3
    from botocore.exceptions import ClientError
    _HAS_BOTO3 = True
except ImportError:  # pragma: no cover — optional cloud dependency
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[misc,assignment]
    _HAS_BOTO3 = False

logger = logging.getLogger("orchestra.cloud.files")

_PART_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB minimum part size for multipart


class CloudFiles:
    """
    File upload/download pipeline backed by S3 with optional CloudFront CDN.

    All files are stored under the key prefix ``files/{user_id}/{filename}``.
    """

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        cdn_domain: str = "",
    ) -> None:
        if not _HAS_BOTO3:
            raise RuntimeError(
                "boto3 is required for CloudFiles. "
                "Install it with: pip install boto3"
            )
        self._bucket = bucket
        self._region = region
        self._cdn_domain = cdn_domain.rstrip("/")
        self._s3 = boto3.client("s3", region_name=region)
        logger.info(
            "CloudFiles initialised (bucket=%s, region=%s, cdn=%s)",
            bucket,
            region,
            cdn_domain or "none",
        )

    # ------------------------------------------------------------------
    # Presigned URL helpers
    # ------------------------------------------------------------------

    async def generate_upload_url(
        self,
        user_id: str,
        filename: str,
        content_type: str,
        max_size_mb: int = 100,
    ) -> dict:
        """Generate an S3 presigned POST for direct browser upload.

        Returns a dict with ``url``, ``fields``, and ``expires_in``.
        """
        key = self._key(user_id, filename)
        max_size_bytes = max_size_mb * 1024 * 1024
        expires_in = 3600  # 1 hour

        conditions: list[Any] = [
            {"bucket": self._bucket},
            ["starts-with", "$key", f"files/{user_id}/"],
            {"Content-Type": content_type},
            ["content-length-range", 1, max_size_bytes],
        ]

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.generate_presigned_post(
                    Bucket=self._bucket,
                    Key=key,
                    Fields={
                        "Content-Type": content_type,
                    },
                    Conditions=conditions,
                    ExpiresIn=expires_in,
                ),
            )
            logger.debug("generate_upload_url: key=%s", key)
            return {
                "url": response["url"],
                "fields": response["fields"],
                "expires_in": expires_in,
                "key": key,
            }
        except ClientError as exc:
            logger.exception("generate_upload_url: S3 error for key=%s", key)
            raise

    async def generate_download_url(
        self,
        user_id: str,
        filename: str,
        expires: int = 3600,
    ) -> str:
        """Return a presigned GET URL (or CDN URL when CDN is configured)."""
        key = self._key(user_id, filename)

        if self._cdn_domain:
            # CDN URL — no expiry needed (access via signed cookies or open policy)
            return f"{self._cdn_domain}/{key}"

        try:
            url = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": key},
                    ExpiresIn=expires,
                ),
            )
            logger.debug("generate_download_url: key=%s", key)
            return url
        except ClientError:
            logger.exception("generate_download_url: S3 error for key=%s", key)
            raise

    # ------------------------------------------------------------------
    # Server-side upload
    # ------------------------------------------------------------------

    async def upload(
        self,
        user_id: str,
        filename: str,
        data: bytes,
        content_type: str = "",
    ) -> dict:
        """Upload bytes directly from the server to S3.

        Returns metadata dict with ``key``, ``size``, ``content_type``, ``etag``.
        """
        key = self._key(user_id, filename)
        if not content_type:
            content_type = self._guess_content_type(filename)

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                    Metadata={
                        "user_id": user_id,
                        "uploaded_at": str(time.time()),
                    },
                ),
            )
            etag = response.get("ETag", "").strip('"')
            logger.info("upload: key=%s size=%d", key, len(data))
            return {
                "key": key,
                "size": len(data),
                "content_type": content_type,
                "etag": etag,
            }
        except ClientError:
            logger.exception("upload: S3 error for key=%s", key)
            raise

    # ------------------------------------------------------------------
    # Multipart upload
    # ------------------------------------------------------------------

    async def upload_multipart(
        self,
        user_id: str,
        filename: str,
        file_size: int,
    ) -> dict:
        """Initiate a multipart upload for large files.

        Returns ``upload_id`` and a list of ``part_urls`` (presigned PUT URLs
        for each 5 MB chunk).
        """
        key = self._key(user_id, filename)
        content_type = self._guess_content_type(filename)

        try:
            # 1. Create the multipart upload
            create_resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.create_multipart_upload(
                    Bucket=self._bucket,
                    Key=key,
                    ContentType=content_type,
                    Metadata={"user_id": user_id},
                ),
            )
            upload_id: str = create_resp["UploadId"]

            # 2. Compute part count
            part_count = max(1, (file_size + _PART_SIZE_BYTES - 1) // _PART_SIZE_BYTES)

            # 3. Generate presigned PUT URLs for each part
            async def _presign_part(part_number: int) -> str:
                return await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._s3.generate_presigned_url(
                        "upload_part",
                        Params={
                            "Bucket": self._bucket,
                            "Key": key,
                            "UploadId": upload_id,
                            "PartNumber": part_number,
                        },
                        ExpiresIn=3600,
                    ),
                )

            part_urls = await asyncio.gather(
                *[_presign_part(i + 1) for i in range(part_count)]
            )

            logger.info(
                "upload_multipart: key=%s upload_id=%s parts=%d",
                key,
                upload_id,
                part_count,
            )
            return {
                "upload_id": upload_id,
                "key": key,
                "part_count": part_count,
                "part_size_bytes": _PART_SIZE_BYTES,
                "part_urls": [
                    {"part_number": i + 1, "url": url}
                    for i, url in enumerate(part_urls)
                ],
            }
        except ClientError:
            logger.exception("upload_multipart: S3 error for key=%s", key)
            raise

    async def complete_multipart(
        self,
        user_id: str,
        filename: str,
        upload_id: str,
        parts: list[dict],
    ) -> dict:
        """Complete a multipart upload.

        ``parts`` must be a list of ``{"PartNumber": int, "ETag": str}``.
        Returns location, key, and etag.
        """
        key = self._key(user_id, filename)
        multipart_upload = {"Parts": parts}

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload=multipart_upload,
                ),
            )
            logger.info("complete_multipart: key=%s upload_id=%s", key, upload_id)
            return {
                "location": response.get("Location", ""),
                "key": response.get("Key", key),
                "etag": response.get("ETag", "").strip('"'),
            }
        except ClientError:
            logger.exception(
                "complete_multipart: S3 error for key=%s upload_id=%s", key, upload_id
            )
            raise

    # ------------------------------------------------------------------
    # Download / delete
    # ------------------------------------------------------------------

    async def download(self, user_id: str, filename: str) -> bytes:
        """Download a file from S3 and return raw bytes."""
        key = self._key(user_id, filename)
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.get_object(Bucket=self._bucket, Key=key),
            )
            data: bytes = response["Body"].read()
            logger.debug("download: key=%s size=%d", key, len(data))
            return data
        except ClientError:
            logger.exception("download: S3 error for key=%s", key)
            raise

    async def delete(self, user_id: str, filename: str) -> bool:
        """Delete a file from S3. Returns True on success."""
        key = self._key(user_id, filename)
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.delete_object(Bucket=self._bucket, Key=key),
            )
            logger.info("delete: key=%s", key)
            return True
        except ClientError:
            logger.exception("delete: S3 error for key=%s", key)
            return False

    # ------------------------------------------------------------------
    # Listing / metadata
    # ------------------------------------------------------------------

    async def list_files(
        self,
        user_id: str,
        prefix: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """List files for a user with size, last modified, and content type.

        Returns a list of dicts: ``{key, filename, size, modified, content_type}``.
        """
        base_prefix = f"files/{user_id}/"
        full_prefix = base_prefix + prefix

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.list_objects_v2(
                    Bucket=self._bucket,
                    Prefix=full_prefix,
                    MaxKeys=limit,
                ),
            )
            items = []
            for obj in response.get("Contents", []):
                key: str = obj["Key"]
                filename = key[len(base_prefix):]  # strip prefix
                items.append(
                    {
                        "key": key,
                        "filename": filename,
                        "size": obj.get("Size", 0),
                        "modified": obj.get("LastModified", "").isoformat()
                        if hasattr(obj.get("LastModified", ""), "isoformat")
                        else str(obj.get("LastModified", "")),
                        "content_type": self._guess_content_type(filename),
                    }
                )
            logger.debug("list_files: user_id=%s count=%d", user_id, len(items))
            return items
        except ClientError:
            logger.exception("list_files: S3 error for user_id=%s", user_id)
            return []

    async def get_metadata(self, user_id: str, filename: str) -> dict:
        """Return HEAD object metadata for a file."""
        key = self._key(user_id, filename)
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.head_object(Bucket=self._bucket, Key=key),
            )
            return {
                "key": key,
                "filename": filename,
                "size": response.get("ContentLength", 0),
                "content_type": response.get("ContentType", ""),
                "modified": str(response.get("LastModified", "")),
                "etag": response.get("ETag", "").strip('"'),
                "metadata": response.get("Metadata", {}),
            }
        except ClientError:
            logger.exception("get_metadata: S3 error for key=%s", key)
            raise

    # ------------------------------------------------------------------
    # Copy and share
    # ------------------------------------------------------------------

    async def copy(self, user_id: str, source: str, dest: str) -> dict:
        """Copy a file within the same user's namespace.

        Returns metadata for the destination object.
        """
        src_key = self._key(user_id, source)
        dst_key = self._key(user_id, dest)
        copy_source = {"Bucket": self._bucket, "Key": src_key}

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.copy_object(
                    CopySource=copy_source,
                    Bucket=self._bucket,
                    Key=dst_key,
                ),
            )
            logger.info("copy: %s -> %s", src_key, dst_key)
            return {
                "source_key": src_key,
                "dest_key": dst_key,
                "etag": response.get("CopyObjectResult", {})
                .get("ETag", "")
                .strip('"'),
            }
        except ClientError:
            logger.exception("copy: S3 error for src=%s dst=%s", src_key, dst_key)
            raise

    async def share(
        self,
        user_id: str,
        filename: str,
        expires_hours: int = 24,
    ) -> str:
        """Return a public shareable URL.

        Uses CDN URL if a CDN domain is configured, otherwise returns a
        presigned GET URL valid for ``expires_hours``.
        """
        key = self._key(user_id, filename)

        if self._cdn_domain:
            url = f"{self._cdn_domain}/{key}"
            logger.debug("share: CDN url for key=%s", key)
            return url

        expires_seconds = expires_hours * 3600
        try:
            url = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": key},
                    ExpiresIn=expires_seconds,
                ),
            )
            logger.debug("share: presigned url for key=%s expires=%dh", key, expires_hours)
            return url
        except ClientError:
            logger.exception("share: S3 error for key=%s", key)
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(user_id: str, filename: str) -> str:
        """Build the S3 object key: ``files/{user_id}/{filename}``."""
        # Sanitise filename to prevent path traversal
        safe_filename = filename.lstrip("/").replace("..", "")
        return f"files/{user_id}/{safe_filename}"

    @staticmethod
    def _guess_content_type(filename: str) -> str:
        """Guess MIME type from filename, falling back to octet-stream."""
        mime, _ = mimetypes.guess_type(filename)
        return mime or "application/octet-stream"
