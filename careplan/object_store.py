"""S3-compatible object storage (MinIO locally, AWS S3 in production).

Raw uploaded documents live in object storage; the Kafka message carries only a small
reference (the object key) -- the "claim-check" pattern. Why:
  - keeps large blobs OUT of Kafka (broker messages stay small and cheap);
  - object storage is the durable source of truth, so the ingestion topic can be replayed
    and the documents re-fetched and re-indexed at will;
  - the SAME boto3 client points at MinIO locally and real S3 in prod -- only S3_ENDPOINT changes.
"""

import os
import uuid
from functools import lru_cache

BUCKET = os.environ.get("S3_BUCKET", "knowledge")


@lru_cache
def get_s3():
    import boto3
    from botocore.config import Config

    endpoint = os.environ.get("S3_ENDPOINT")  # e.g. http://minio:9000 locally; unset -> real AWS S3
    # MinIO needs path-style addressing (host/bucket) instead of AWS's virtual-hosted (bucket.host)
    cfg = Config(s3={"addressing_style": "path"}) if endpoint else None
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "minioadmin"),
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        config=cfg,
    )


def ensure_bucket() -> None:
    s3 = get_s3()
    names = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    if BUCKET not in names:
        s3.create_bucket(Bucket=BUCKET)


def put_document(source: str, content: str) -> str:
    """Store a raw document; return its object key (the claim check that travels through Kafka)."""
    ensure_bucket()
    key = f"knowledge/{source}/{uuid.uuid4().hex}.txt"
    get_s3().put_object(Bucket=BUCKET, Key=key, Body=content.encode("utf-8"))
    return key


def get_document(key: str) -> str:
    """Fetch a document's content by object key."""
    return get_s3().get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8")
