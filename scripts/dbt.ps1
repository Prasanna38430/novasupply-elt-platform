# Run dbt with credentials loaded from .env.
#
# Only needed for the Snowflake target -- the DuckDB target has no credentials at all.
# Keeping this in a script means the Snowflake password lives in .env and nowhere else.
#
#   .\scripts\dbt.ps1 build --target snowflake
#   .\scripts\dbt.ps1 test --target snowflake

param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $DbtArgs)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot ".env"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $name, $value = $line.Split("=", 2)
            [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
        }
    }
}

$dbt = Join-Path $repoRoot ".venv\Scripts\dbt.exe"
if (-not (Test-Path $dbt)) { throw "dbt not found at $dbt. Create the venv first." }

Push-Location (Join-Path $repoRoot "dbt")
try {
    & $dbt @DbtArgs --profiles-dir .
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
