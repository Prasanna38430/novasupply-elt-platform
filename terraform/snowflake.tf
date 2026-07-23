resource "snowflake_database" "novasupply" {
  name    = var.snowflake_database
  comment = "NovaSupply retail supply-chain analytics platform, managed by Terraform."
}

# One schema per layer, matching what dbt builds locally on DuckDB.
locals {
  schemas = {
    RAW        = "Untyped landing zone, loaded from S3. Faithful copy of source files."
    STAGING    = "Typed and cleaned views over RAW."
    MARTS      = "Star schema: dim_* and fct_* tables serving the business questions."
    QUARANTINE = "Rows rejected by validation, kept with the reason they failed."
    SNAPSHOTS  = "dbt snapshots holding Type-2 history."
  }
}

resource "snowflake_schema" "layers" {
  for_each = local.schemas

  database = snowflake_database.novasupply.name
  name     = each.key
  comment  = each.value
}

# XSMALL is the smallest and cheapest size, and is far more than this data needs.
# auto_suspend is the single most important cost control in Snowflake: a warehouse left
# running idle bills by the second for doing nothing.
resource "snowflake_warehouse" "novasupply" {
  name                = var.snowflake_warehouse
  warehouse_size      = "XSMALL"
  auto_suspend        = var.warehouse_auto_suspend_seconds
  auto_resume         = true
  initially_suspended = true
  comment             = "NovaSupply compute. Suspends after ${var.warehouse_auto_suspend_seconds}s idle."
}

# ---------------------------------------------------------------------------
# Roles. Three of them, split by what each job actually needs to do, so that no
# day-to-day work runs as ACCOUNTADMIN.
# ---------------------------------------------------------------------------

resource "snowflake_account_role" "loader" {
  name    = "NOVASUPPLY_LOADER"
  comment = "Ingestion. Writes into RAW and nothing else."
}

resource "snowflake_account_role" "transformer" {
  name    = "NOVASUPPLY_TRANSFORMER"
  comment = "dbt. Reads RAW, builds STAGING, MARTS, QUARANTINE and SNAPSHOTS."
}

resource "snowflake_account_role" "analyst" {
  name    = "NOVASUPPLY_ANALYST"
  comment = "Read-only access to MARTS for BI and the dashboard."
}

locals {
  all_roles = {
    loader      = snowflake_account_role.loader.name
    transformer = snowflake_account_role.transformer.name
    analyst     = snowflake_account_role.analyst.name
  }
}

# Every role needs compute and needs to see the database.
resource "snowflake_grant_privileges_to_account_role" "warehouse_usage" {
  for_each = local.all_roles

  account_role_name = each.value
  privileges        = ["USAGE"]

  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.novasupply.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "database_usage" {
  for_each = local.all_roles

  account_role_name = each.value
  privileges        = ["USAGE"]

  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.novasupply.name
  }
}

# dbt creates and drops objects across its layers, so the transformer owns them.
resource "snowflake_grant_privileges_to_account_role" "transformer_database" {
  account_role_name = snowflake_account_role.transformer.name
  privileges        = ["CREATE SCHEMA"]

  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.novasupply.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "transformer_schemas" {
  for_each = snowflake_schema.layers

  account_role_name = snowflake_account_role.transformer.name
  all_privileges    = true

  on_schema {
    schema_name = "\"${snowflake_database.novasupply.name}\".\"${each.value.name}\""
  }
}

# Schema names are built from the schema resources rather than written as literals.
# Terraform derives its ordering from resource references, so a hardcoded name leaves it
# free to grant against a schema it has not created yet.
locals {
  schema_fqn = {
    for key, schema in snowflake_schema.layers :
    key => "\"${snowflake_database.novasupply.name}\".\"${schema.name}\""
  }
}

# The loader only ever touches RAW.
resource "snowflake_grant_privileges_to_account_role" "loader_raw" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["USAGE", "CREATE TABLE", "CREATE STAGE", "CREATE FILE FORMAT"]

  on_schema {
    schema_name = local.schema_fqn["RAW"]
  }
}

# The analyst reads the marts and nothing more -- including tables dbt creates later,
# hence future_schemas rather than a one-off grant.
resource "snowflake_grant_privileges_to_account_role" "analyst_marts_usage" {
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["USAGE"]

  on_schema {
    schema_name = local.schema_fqn["MARTS"]
  }
}

resource "snowflake_grant_privileges_to_account_role" "analyst_marts_select" {
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["SELECT"]

  on_schema_object {
    future {
      object_type_plural = "TABLES"
      in_schema          = local.schema_fqn["MARTS"]
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "analyst_marts_select_views" {
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["SELECT"]

  on_schema_object {
    future {
      object_type_plural = "VIEWS"
      in_schema          = local.schema_fqn["MARTS"]
    }
  }
}

# Without this the roles exist but nobody can assume them.
resource "snowflake_grant_account_role" "to_user" {
  for_each = local.all_roles

  role_name = each.value
  user_name = var.snowflake_user
}
