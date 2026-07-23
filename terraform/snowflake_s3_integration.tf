# Lets Snowflake read the raw zone from S3 without ever holding an AWS key.
#
# Snowflake assumes an IAM role in this account instead. That normally creates a cycle:
# the integration needs the role ARN, and the role's trust policy needs values that only
# exist once the integration has been created. Two things break it — the role ARN is
# constructed from the account id rather than referencing the role resource, and the
# external id is one we choose rather than one Snowflake generates.

data "aws_caller_identity" "current" {}

locals {
  snowflake_role_name = "novasupply-snowflake-s3-access"
  snowflake_role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.snowflake_role_name}"
  # Guards against the confused-deputy problem: Snowflake must present this value to
  # assume the role, so another Snowflake account cannot borrow our integration.
  snowflake_external_id = "NOVASUPPLY_S3_ACCESS"
}

# snowflake_storage_integration_aws, not the older snowflake_storage_integration, which
# the provider deprecates in favour of the per-cloud resources.
resource "snowflake_storage_integration_aws" "s3" {
  name                      = "NOVASUPPLY_S3_INTEGRATION"
  enabled                   = true
  storage_provider          = "S3"
  storage_aws_role_arn      = local.snowflake_role_arn
  storage_aws_external_id   = local.snowflake_external_id
  storage_allowed_locations = ["s3://${aws_s3_bucket.raw.id}/"]
  comment                   = "Read-only access to the NovaSupply raw zone."
}

# Read-only. Snowflake loads from the raw zone and must never write to it.
resource "aws_iam_policy" "snowflake_s3_read" {
  name        = "novasupply-snowflake-s3-read"
  description = "Read-only access to the NovaSupply raw zone for Snowflake COPY INTO."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = "${aws_s3_bucket.raw.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = aws_s3_bucket.raw.arn
      },
    ]
  })
}

resource "aws_iam_role" "snowflake" {
  name        = local.snowflake_role_name
  description = "Assumed by Snowflake to read the raw zone."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          # The IAM user Snowflake created on its side for this integration. Only
          # available once the integration exists, which is what orders these two.
          AWS = snowflake_storage_integration_aws.s3.describe_output[0].iam_user_arn
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "sts:ExternalId" = local.snowflake_external_id
          }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "snowflake_s3_read" {
  role       = aws_iam_role.snowflake.name
  policy_arn = aws_iam_policy.snowflake_s3_read.arn
}

# The loader uses the integration to build a stage; dbt reads what the loader produced.
resource "snowflake_grant_privileges_to_account_role" "loader_integration" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["USAGE"]

  on_account_object {
    object_type = "INTEGRATION"
    object_name = snowflake_storage_integration_aws.s3.name
  }
}
