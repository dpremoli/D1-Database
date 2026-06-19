"""MinIO / S3-compatible object storage client."""

import os

import boto3
from botocore.config import Config

BUCKET: str = os.getenv("MINIO_BUCKET", "d1-files")


def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def download_file(object_key: str, local_path: str) -> None:
    """Stream *object_key* from MinIO to *local_path*."""
    _client().download_file(BUCKET, object_key, local_path)


def put_object(
    object_key: str, data: bytes, content_type: str = "application/octet-stream"
) -> None:
    """Upload *data* as a single object."""
    _client().put_object(
        Bucket=BUCKET, Key=object_key, Body=data, ContentType=content_type
    )
