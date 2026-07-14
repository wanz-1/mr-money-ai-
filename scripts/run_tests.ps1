$ErrorActionPreference = "Stop"

function Invoke-ProjectPython {
  param([string[]]$Arguments)

  $pythonWorks = $false
  try {
    & python --version *> $null
    $pythonWorks = ($LASTEXITCODE -eq 0)
  } catch {
    $pythonWorks = $false
  }

  if ($pythonWorks) {
    & python @Arguments
    exit $LASTEXITCODE
  }

  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "No working python executable found and uv is not available."
  }

  $env:UV_CACHE_DIR = Join-Path (Get-Location) ".uv-cache"
  & uv run --no-project python @Arguments
  exit $LASTEXITCODE
}

Invoke-ProjectPython @("-m", "unittest", "discover", "-s", "tests")
