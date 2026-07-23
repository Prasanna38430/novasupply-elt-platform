"""Upload the local raw zone to S3, preserving the partition layout.

The S3 keys mirror data/raw exactly, so `sales/dt=2026-07-18/sales.csv` locally becomes
`s3://<bucket>/sales/dt=2026-07-18/sales.csv`. Keeping the layouts identical is what
makes the local and cloud paths interchangeable rather than two separate designs.

Uploads skip files whose size already matches in S3, so re-running only sends what
changed.

    python ingestion/upload_to_s3.py
"""
from __future__ import annotations

import os

import boto3
from botocore.exceptions import ClientError

from config import PROJECT_ROOT, RAW_DATA_DIR


def s3_client():
    return boto3.session.Session(
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ["AWS_REGION"],
    ).client("s3")


def existing_sizes(client, bucket: str) -> dict[str, int]:
    """Key -> size for everything already in the bucket."""
    sizes: dict[str, int] = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            sizes[obj["Key"]] = obj["Size"]
    return sizes


def main() -> None:
    bucket = os.environ["S3_RAW_BUCKET"]
    client = s3_client()

    try:
        remote = existing_sizes(client, bucket)
    except ClientError as exc:
        raise SystemExit(f"cannot read s3://{bucket}: {exc}") from exc

    local_files = sorted(p for p in RAW_DATA_DIR.rglob("*.csv") if p.is_file())
    if not local_files:
        raise SystemExit(f"no CSV files under {RAW_DATA_DIR} - run the generators first")

    uploaded = skipped = 0
    total_bytes = 0
    for path in local_files:
        key = path.relative_to(RAW_DATA_DIR).as_posix()
        size = path.stat().st_size
        if remote.get(key) == size:
            skipped += 1
            continue
        client.upload_file(str(path), bucket, key)
        uploaded += 1
        total_bytes += size

    print(f"uploaded {uploaded} file(s), {total_bytes / 1_048_576:.1f} MiB")
    print(f"skipped  {skipped} already present and unchanged")
    print(f"target   s3://{bucket}/")


if __name__ == "__main__":
    main()
