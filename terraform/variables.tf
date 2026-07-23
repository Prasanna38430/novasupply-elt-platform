variable "aws_region" {
  description = "Region for the raw-zone bucket. Kept the same as the Snowflake account region so data never crosses regions."
  type        = string
  default     = "eu-west-3"
}

variable "s3_raw_bucket" {
  description = "Globally unique name for the S3 raw zone bucket. Supplied from S3_RAW_BUCKET in .env."
  type        = string
}

variable "snowflake_user" {
  description = "Snowflake login that the new roles are granted to. Supplied from SNOWFLAKE_USER in .env."
  type        = string
}

variable "snowflake_database" {
  description = "Database holding the NovaSupply platform, kept separate from other projects in the account."
  type        = string
  default     = "NOVASUPPLY"
}

variable "snowflake_warehouse" {
  description = "Compute warehouse for NovaSupply."
  type        = string
  default     = "NOVASUPPLY_WH"
}

variable "warehouse_auto_suspend_seconds" {
  description = "Idle seconds before the warehouse suspends. Low on purpose: an idle running warehouse burns credits for nothing."
  type        = number
  default     = 60
}
