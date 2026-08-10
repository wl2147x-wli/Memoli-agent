param(
    [Parameter(Mandatory = $true)]
    [string]$BaseImage,
    [string]$Tag = "memoli-code-runner:0.1.0"
)

$ErrorActionPreference = "Stop"
if ($BaseImage -notmatch '@sha256:[0-9a-f]{64}$') {
    throw "BaseImage 必须固定到 sha256 digest。"
}

$runnerRoot = (Resolve-Path $PSScriptRoot).Path
docker build --build-arg "BASE_IMAGE=$BaseImage" -f `
    (Join-Path $runnerRoot "Dockerfile") -t $Tag $runnerRoot
if ($LASTEXITCODE -ne 0) { throw "code runner 镜像构建失败。" }

$imageId = docker image inspect $Tag --format '{{.Id}}'
if ($LASTEXITCODE -ne 0 -or $imageId -notmatch '^sha256:[0-9a-f]{64}$') {
    throw "无法读取 code runner 镜像 digest。"
}
$imageId | Set-Content -Encoding utf8 (Join-Path $runnerRoot "runner-image.lock")
Write-Output $imageId
