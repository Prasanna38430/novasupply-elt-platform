# Neither provider is given credentials here. Both read them from environment
# variables, so no secret is ever written into the configuration or into git.
# Use scripts/tf.ps1, which loads .env and then calls terraform.
#
#   AWS       AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
#   Snowflake SNOWFLAKE_ORGANIZATION_NAME, SNOWFLAKE_ACCOUNT_NAME,
#             SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_ROLE

provider "aws" {
  region = var.aws_region

  # Tag everything, so anything unexpected on the bill can be traced back here.
  default_tags {
    tags = {
      Project   = "novasupply"
      ManagedBy = "terraform"
    }
  }
}

provider "snowflake" {}
