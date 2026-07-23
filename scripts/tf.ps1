# Run terraform with credentials loaded from .env.
#
# The providers read their credentials from environment variables, so nothing secret
# ends up in the Terraform configuration, on the command line, or in git. This script
# just bridges .env to those variables for the current process.
#
#   .\scripts\tf.ps1 init
#   .\scripts\tf.ps1 plan
#   .\scripts\tf.ps1 apply

param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $TerraformArgs)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot ".env"

if (-not (Test-Path $envFile)) {
    throw "No .env found at $envFile. Copy .env.example and fill it in first."
}

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $name, $value = $line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
    }
}

# Terraform picks up variables prefixed with TF_VAR_.
$env:TF_VAR_s3_raw_bucket  = $env:S3_RAW_BUCKET
$env:TF_VAR_snowflake_user = $env:SNOWFLAKE_USER
$env:TF_VAR_aws_region     = $env:AWS_REGION

# The provider connects with whatever SNOWFLAKE_WAREHOUSE says, but .env points that at
# NOVASUPPLY_WH -- the warehouse Terraform itself creates. Terraform cannot connect using
# a warehouse that does not exist yet, so it uses the account's default warehouse for its
# own session. This only affects Terraform; dbt still runs on NOVASUPPLY_WH.
$env:SNOWFLAKE_WAREHOUSE = "COMPUTE_WH"

foreach ($required in @("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3_RAW_BUCKET",
                        "SNOWFLAKE_ORGANIZATION_NAME", "SNOWFLAKE_ACCOUNT_NAME",
                        "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_ROLE")) {
    if (-not [Environment]::GetEnvironmentVariable($required, "Process")) {
        throw "$required is missing or empty in .env"
    }
}

Push-Location (Join-Path $repoRoot "terraform")
try {
    & terraform @TerraformArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
