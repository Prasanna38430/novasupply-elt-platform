terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    # Note the namespace: the provider moved from Snowflake-Labs to snowflakedb, and
    # the old namespace is frozen at 1.0.5. Anything written against Snowflake-Labs
    # examples will use resource names that no longer exist.
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "~> 2.0"
    }
  }
}
