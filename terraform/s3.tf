# The raw zone. Same date-partitioned layout as data/raw locally, so the switch from
# local files to S3 is a path change rather than a redesign.

resource "aws_s3_bucket" "raw" {
  bucket = var.s3_raw_bucket
}

# Raw data is the one thing we cannot regenerate if a bad load overwrites it, so keep
# previous versions of every object.
resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Nothing in here is ever public. This blocks it at the bucket level regardless of what
# any future object ACL or policy tries to do.
resource "aws_s3_bucket_public_access_block" "raw" {
  bucket = aws_s3_bucket.raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning means every overwrite keeps the old copy forever unless told otherwise.
# Thirty days is long enough to recover from a bad load without paying to store history
# indefinitely.
resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.raw]
}
