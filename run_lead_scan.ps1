param(
  [string]$Query = "kafe Samsun",
  [int]$Limit = 20,
  [int]$Workers = 5,
  [int]$Concurrency = 2
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$tokenFile = Join-Path $root "apifytoken.txt"
if (-not (Test-Path -LiteralPath $tokenFile)) { throw "apifytoken.txt bulunamadı." }
$env:APIFY_API_TOKEN = (Get-Content -Raw -LiteralPath $tokenFile).Trim()
try {
  Set-Location $root
  python .\lead_automation.py --query $Query --limit $Limit --workers $Workers --concurrency $Concurrency
} finally {
  Remove-Item Env:APIFY_API_TOKEN -ErrorAction SilentlyContinue
}
