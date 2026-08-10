param(
    [string]$Environment = "memoli"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runId = [Guid]::NewGuid().ToString("N")
$runRoot = Join-Path $repositoryRoot ".test-tmp\$runId"
$processTemp = Join-Path $runRoot "process"
$pytestTemp = Join-Path $runRoot "pytest"
New-Item -ItemType Directory -Path $processTemp -Force | Out-Null

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:TMP = $processTemp
$env:TEMP = $processTemp

Push-Location $repositoryRoot
try {
    conda run -n $Environment python -m pytest -q --basetemp $pytestTemp -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
