[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$RuntimeRoot = "E:\Lumina-Layers\lumina-runtime",
    [string]$ImageName = "lumina-layers:local-latest",
    [string]$ContainerName = "lumina-layers-local",
    [string]$PublicHost = "localhost",
    [int]$PublicFrontendPort = 4174,
    [int]$PublicBackendPort = 8000,
    [int]$MaxWorkers = 2,
    [int]$WorkerMaxTasksPerChild = 3,
    [int]$MallocArenaMax = 2,
    [int]$SolverCacheBuildMemoryLimitMb = 8192,
    [ValidateSet("http", "https")]
    [string]$PublicScheme = "http",
    [switch]$SkipBuild,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Ensure-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    return (Resolve-Path $Path).Path
}

function Ensure-SeededDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Target
    )

    Ensure-Directory $Target | Out-Null
    $hasContent = Get-ChildItem -LiteralPath $Target -Force -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $hasContent -and (Test-Path -LiteralPath $Source)) {
        Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Target -Recurse -Force
    }
    return (Resolve-Path $Target).Path
}

if (-not $RepoRoot.Trim()) {
    $RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
$RuntimeRoot = Ensure-Directory $RuntimeRoot
$outputDir = Ensure-Directory (Join-Path $RuntimeRoot "output")
$logsDir = Ensure-Directory (Join-Path $RuntimeRoot "logs")
$feedbackDir = Ensure-Directory (Join-Path $RuntimeRoot "feedback")
$lutPresetDir = Ensure-SeededDirectory (Join-Path $RepoRoot "lut-preset") (Join-Path $RuntimeRoot "lut-preset")
$settingsFile = Join-Path $RuntimeRoot "user_settings.json"
if (-not (Test-Path -LiteralPath $settingsFile)) {
    Set-Content -LiteralPath $settingsFile -Value "{}" -Encoding UTF8
}
$settingsFile = (Resolve-Path $settingsFile).Path
if ($PublicFrontendPort -lt 1 -or $PublicFrontendPort -gt 65535) {
    throw "PublicFrontendPort must be between 1 and 65535."
}
if ($PublicBackendPort -lt 1 -or $PublicBackendPort -gt 65535) {
    throw "PublicBackendPort must be between 1 and 65535."
}
if ($MaxWorkers -lt 1) {
    throw "MaxWorkers must be at least 1."
}
if ($WorkerMaxTasksPerChild -lt 1) {
    throw "WorkerMaxTasksPerChild must be at least 1."
}
if ($MallocArenaMax -lt 1) {
    throw "MallocArenaMax must be at least 1."
}
if ($SolverCacheBuildMemoryLimitMb -lt 512) {
    throw "SolverCacheBuildMemoryLimitMb must be at least 512."
}

if (-not $SkipBuild) {
    Push-Location $RepoRoot
    try {
        Invoke-Checked "docker" @("build", "-t", $ImageName, ".")
    }
    finally {
        Pop-Location
    }
}

if ($NoStart) {
    Write-Host "Image build complete. Skipped container start because -NoStart was set."
    exit 0
}

$existingContainer = docker ps -a --filter "name=^/$ContainerName$" --format "{{.ID}}"
if ($existingContainer) {
    Invoke-Checked "docker" @("rm", "-f", $ContainerName)
}

$runArgs = @(
    "run", "-d",
    "--name", $ContainerName,
    "-p", "${PublicFrontendPort}:4174",
    "-p", "${PublicBackendPort}:8000",
    "-v", "${outputDir}:/app/output",
    "-v", "${logsDir}:/app/logs",
    "-v", "${feedbackDir}:/app/feedback",
    "-v", "${lutPresetDir}:/app/lut-preset",
    "-v", "${settingsFile}:/app/user_settings.json",
    "-e", "VITE_ALLOW_ALL_HOSTS=true",
    "-e", "VITE_DEV_HOST=0.0.0.0",
    "-e", "LUMINA_LOG_DIR=/app/logs",
    "-e", "LUMINA_LOG_FORMAT=json",
    "-e", "LUMINA_FEEDBACK_DUMP_DIR=/app/feedback",
    "-e", "LUMINA_MAX_WORKERS=$MaxWorkers",
    "-e", "LUMINA_WORKER_MAX_TASKS_PER_CHILD=$WorkerMaxTasksPerChild",
    "-e", "LUMINA_SOLVER_CACHE_BUILD_MEMORY_LIMIT_MB=$SolverCacheBuildMemoryLimitMb",
    "-e", "MALLOC_ARENA_MAX=$MallocArenaMax",
    "-e", "OMP_NUM_THREADS=1",
    "-e", "OPENBLAS_NUM_THREADS=1",
    "-e", "MKL_NUM_THREADS=1",
    "-e", "VECLIB_MAXIMUM_THREADS=1",
    "-e", "NUMEXPR_NUM_THREADS=1"
)

$runArgs += $ImageName
Invoke-Checked "docker" $runArgs

Write-Host ""
Write-Host "Lumina local Docker deployment started."
Write-Host "Main frontend : ${PublicScheme}://${PublicHost}:$PublicFrontendPort"
Write-Host "Main backend  : ${PublicScheme}://${PublicHost}:$PublicBackendPort/api/health"
Write-Host "Runtime root  : $RuntimeRoot"
Write-Host "Container     : $ContainerName"
Write-Host "Workers       : max=$MaxWorkers recycle=$WorkerMaxTasksPerChild arena=$MallocArenaMax"
Write-Host "Cache budget  : ${SolverCacheBuildMemoryLimitMb}MB"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  docker logs -f $ContainerName"
Write-Host "  docker rm -f $ContainerName"
