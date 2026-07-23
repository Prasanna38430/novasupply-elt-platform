output "s3_raw_bucket" {
  description = "Name of the raw zone bucket."
  value       = aws_s3_bucket.raw.id
}

output "s3_raw_bucket_region" {
  description = "Region the bucket lives in. Must match the Snowflake account region."
  value       = aws_s3_bucket.raw.region
}

output "snowflake_database" {
  value = snowflake_database.novasupply.name
}

output "snowflake_warehouse" {
  value = snowflake_warehouse.novasupply.name
}

output "snowflake_roles" {
  description = "Roles created for the platform, narrowest first."
  value = [
    snowflake_account_role.analyst.name,
    snowflake_account_role.loader.name,
    snowflake_account_role.transformer.name,
  ]
}
