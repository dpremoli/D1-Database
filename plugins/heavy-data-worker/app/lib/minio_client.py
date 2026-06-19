"""MinIO / S3-compatible object storage client."""

import os

import boto3
from botocore.config import Config

BUCKET: str = os.getenv("MINIO_BUCKET", "d1-files")
PART_EXPIRY_SECONDS: int = int(os.getenv("UPLOAD_PART_EXPIRY_SECONDS", "3600"))


def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def create_multipart_upload(
    object_key: str, content_type: str = "application/octet-stream"
) -> str:
    """Initiate a multipart upload and return the UploadId."""
    resp = _client().create_multipart_upload(
        Bucket=BUCKET, Key=object_key, ContentType=content_type
    )
    return resp["UploadId"]


def presign_part(object_key: str, upload_id: str, part_number: int) -> str:
    """Return a presigned PUT URL for a single multipart part."""
    return _client().generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": BUCKET,
            "Key": object_key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=PART_EXPIRY_SECONDS,
    )


def complete_multipart_upload(object_key: str, upload_id: str, parts: list) -> None:
    """Finalise a multipart upload.  *parts* must be [{PartNumber, ETag}, ...]."""
    _client().complete_multipart_upload(
        Bucket=BUCKET,
        Key=object_key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )


def put_object(
    object_key: str, data: bytes, content_type: str = "application/octet-stream"
) -> None:
    """Upload *data* as a single object (for small results like SVG plots)."""
    _client().put_object(
        Bucket=BUCKET, Key=object_key, Body=data, ContentType=content_type
    )


def download_file(object_key: str, local_path: str) -> None:
    """Stream *object_key* from MinIO to *local_path*."""
    _client().download_file(BUCKET, object_key, local_path)
