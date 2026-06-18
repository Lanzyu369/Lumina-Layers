[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$RuntimeRoot = "E:\Lumina-Layers\lumina-runtime",
    [string]$MaterialsSeedPath = "",
    [string]$MaterialsSeedUrl = "",
    [string]$MaterialsSeedSha256 = "",
    [string]$ImageName = "lumina-layers:local-latest",
    [string]$ContainerName = "lumina-layers-local",
    [string]$PublicHost = "localhost",
    [int]$PublicFrontendPort = 4174,
    [int]$PublicBackendPort = 8000,
    [int]$MaxWorkers = 2,
    [int]$WorkerMaxTasksPerChild = 3,
    [int]$MallocArenaMax = 2,
    [int]$SolverCacheBuildMemoryLimitMb = 8192,
    [ValidateSet("v1", "v2", "auto", "shapely_v1", "rasterio_manifold3d")]
    [string]$GlbKernel = "v2",
    [ValidateSet("v1", "v2", "trimesh_v1", "rasterio_manifold3d")]
    [string]$VectorGlbKernel = "v2",
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

function Read-EnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }

    Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }

        $separator = $line.IndexOf("=")
        if ($separator -lt 1) {
            return
        }

        $key = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }

    return $values
}

if (-not $RepoRoot.Trim()) {
    $RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
$localEnv = Read-EnvFile (Join-Path $RepoRoot ".env.local")
$RuntimeRoot = Ensure-Directory $RuntimeRoot
$outputDir = Ensure-Directory (Join-Path $RuntimeRoot "output")
$logsDir = Ensure-Directory (Join-Path $RuntimeRoot "logs")
$feedbackDir = Ensure-Directory (Join-Path $RuntimeRoot "feedback")
$lutPresetDir = Ensure-SeededDirectory (Join-Path $RepoRoot "lut-preset") (Join-Path $RuntimeRoot "lut-preset")
$materialsDir = Ensure-Directory (Join-Path $RuntimeRoot "materials")
$materialsSeedFile = ""
if ($MaterialsSeedPath.Trim() -and $MaterialsSeedUrl.Trim()) {
    throw "Use either -MaterialsSeedPath or -MaterialsSeedUrl, not both."
}
if ($MaterialsSeedPath.Trim()) {
    $resolvedSeedPath = (Resolve-Path $MaterialsSeedPath).Path
    $materialsSeedDir = Ensure-Directory (Join-Path $RuntimeRoot "materials-seed")
    $materialsSeedFile = Join-Path $materialsSeedDir "lumina-materials-seed.zip"
    Copy-Item -LiteralPath $resolvedSeedPath -Destination $materialsSeedFile -Force
    $materialsSeedFile = (Resolve-Path $materialsSeedFile).Path
}
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
        $buildArgs = @("build", "-t", $ImageName)
        if ($MaterialsSeedUrl.Trim()) {
            $buildArgs += @("--build-arg", "MATERIALS_SEED_URL=$MaterialsSeedUrl")
        }
        if ($MaterialsSeedSha256.Trim()) {
            $buildArgs += @("--build-arg", "MATERIALS_SEED_SHA256=$MaterialsSeedSha256")
        }
        $buildArgs += "."
        Invoke-Checked "docker" $buildArgs
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
    "-p", "${PublicFrontendPort}:8000",
    "-p", "${PublicBackendPort}:8000",
    "-v", "${outputDir}:/app/output",
    "-v", "${logsDir}:/app/logs",
    "-v", "${feedbackDir}:/app/feedback",
    "-v", "${lutPresetDir}:/app/lut-preset",
    "-v", "${materialsDir}:/app/materials",
    "-v", "${settingsFile}:/app/user_settings.json",
    "-e", "LUMINA_MATERIALS_DIR=/app/materials",
    "-e", "LUMINA_SERVE_FRONTEND_DIST=1",
    "-e", "LUMINA_FRONTEND_DIST_DIR=/app/frontend/dist",
    "-e", "VITE_ALLOW_ALL_HOSTS=true",
    "-e", "VITE_DEV_HOST=0.0.0.0",
    "-e", "LUMINA_LOG_DIR=/app/logs",
    "-e", "LUMINA_LOG_FORMAT=json",
    "-e", "LUMINA_FEEDBACK_DUMP_DIR=/app/feedback",
    "-e", "LUMINA_MAX_WORKERS=$MaxWorkers",
    "-e", "LUMINA_WORKER_MAX_TASKS_PER_CHILD=$WorkerMaxTasksPerChild",
    "-e", "LUMINA_SOLVER_CACHE_BUILD_MEMORY_LIMIT_MB=$SolverCacheBuildMemoryLimitMb",
    "-e", "LUMINA_GLB_KERNEL=$GlbKernel",
    "-e", "LUMINA_VECTOR_GLB_KERNEL=$VectorGlbKernel",
    "-e", "MALLOC_ARENA_MAX=$MallocArenaMax",
    "-e", "OMP_NUM_THREADS=1",
    "-e", "OPENBLAS_NUM_THREADS=1",
    "-e", "MKL_NUM_THREADS=1",
    "-e", "VECLIB_MAXIMUM_THREADS=1",
    "-e", "NUMEXPR_NUM_THREADS=1"
)

if ($materialsSeedFile) {
    $runArgs += @(
        "-v", "${materialsSeedFile}:/app/resources/materials/lumina-materials-seed.zip:ro",
        "-e", "LUMINA_MATERIALS_SEED_PATH=/app/resources/materials/lumina-materials-seed.zip"
    )
}
if ($MaterialsSeedUrl.Trim()) {
    $runArgs += @("-e", "LUMINA_MATERIALS_SEED_URL=$MaterialsSeedUrl")
}
if ($MaterialsSeedSha256.Trim()) {
    $runArgs += @("-e", "LUMINA_MATERIALS_SEED_SHA256=$MaterialsSeedSha256")
}

$feedbackEnvKeys = @(
    "LUMINA_FEEDBACK_SMTP_HOST",
    "LUMINA_FEEDBACK_SMTP_PORT",
    "LUMINA_FEEDBACK_SMTP_USER",
    "LUMINA_FEEDBACK_SMTP_PASSWORD",
    "LUMINA_FEEDBACK_SMTP_FROM",
    "LUMINA_FEEDBACK_TO",
    "LUMINA_FEEDBACK_SMTP_USE_TLS",
    "LUMINA_FEEDBACK_SMTP_TIMEOUT_S",
    "LUMINA_FEEDBACK_RELAY_URL",
    "LUMINA_FEEDBACK_RELAY_TOKEN",
    "LUMINA_FEEDBACK_RELAY_TIMEOUT_S"
)
foreach ($key in $feedbackEnvKeys) {
    if ($localEnv.ContainsKey($key) -and $localEnv[$key]) {
        $runArgs += @("-e", "${key}=$($localEnv[$key])")
    }
}

$runArgs += $ImageName
Invoke-Checked "docker" $runArgs

Write-Host ""
Write-Host "Lumina local Docker deployment started."
Write-Host "Main frontend : ${PublicScheme}://${PublicHost}:$PublicFrontendPort"
Write-Host "Main backend  : ${PublicScheme}://${PublicHost}:$PublicBackendPort/api/health"
Write-Host "Runtime root  : $RuntimeRoot"
Write-Host "Container     : $ContainerName"
Write-Host "Materials    : $materialsDir"
if ($materialsSeedFile) {
    Write-Host "Seed         : $materialsSeedFile"
}
elseif ($MaterialsSeedUrl.Trim()) {
    Write-Host "Seed         : $MaterialsSeedUrl"
}
else {
    Write-Host "Seed         : <not configured>"
}
Write-Host "Workers       : max=$MaxWorkers recycle=$WorkerMaxTasksPerChild arena=$MallocArenaMax"
Write-Host "Cache budget  : ${SolverCacheBuildMemoryLimitMb}MB"
Write-Host "GLB kernel   : $GlbKernel"
Write-Host "Vector GLB   : $VectorGlbKernel"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  docker logs -f $ContainerName"
Write-Host "  docker rm -f $ContainerName"
