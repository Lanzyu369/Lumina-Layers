[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$Remote = "origin",
    [string]$Branch = "",
    [int]$IntervalSeconds = 300,
    [switch]$Watch,
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
    [ValidateSet("v1", "v2", "auto", "shapely_v1", "rasterio_manifold3d")]
    [string]$GlbKernel = "v2",
    [ValidateSet("v1", "v2", "trimesh_v1", "rasterio_manifold3d")]
    [string]$VectorGlbKernel = "v2",
    [ValidateSet("http", "https")]
    [string]$PublicScheme = "http"
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

function Invoke-GitOutput {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git failed ($LASTEXITCODE): git $($Arguments -join ' ')"
    }
    return $output
}

function Assert-CleanWorktree {
    $status = Invoke-GitOutput @("status", "--porcelain")
    if ($status) {
        throw "Worktree has local changes. Commit, stash, or deploy manually before enabling auto-update."
    }
}

function Resolve-Branch {
    if ($Branch.Trim()) {
        return $Branch.Trim()
    }
    $current = (Invoke-GitOutput @("rev-parse", "--abbrev-ref", "HEAD")).Trim()
    if ($current -eq "HEAD") {
        throw "Cannot auto-update from detached HEAD. Pass -Branch explicitly."
    }
    return $current
}

function Invoke-Deploy {
    $deployScript = Join-Path $ScriptDir "docker_local_deploy.ps1"
    $deployArgs = @(
        "-RepoRoot", $RepoRoot,
        "-RuntimeRoot", $RuntimeRoot,
        "-ImageName", $ImageName,
        "-ContainerName", $ContainerName,
        "-PublicHost", $PublicHost,
        "-PublicFrontendPort", $PublicFrontendPort,
        "-PublicBackendPort", $PublicBackendPort,
        "-MaxWorkers", $MaxWorkers,
        "-WorkerMaxTasksPerChild", $WorkerMaxTasksPerChild,
        "-MallocArenaMax", $MallocArenaMax,
        "-SolverCacheBuildMemoryLimitMb", $SolverCacheBuildMemoryLimitMb,
        "-GlbKernel", $GlbKernel,
        "-VectorGlbKernel", $VectorGlbKernel,
        "-PublicScheme", $PublicScheme
    )
    $powershellArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $deployScript)
    $powershellArgs += $deployArgs
    Invoke-Checked "powershell" $powershellArgs
}

function Sync-Once {
    Push-Location $RepoRoot
    try {
        Assert-CleanWorktree
        $targetBranch = Resolve-Branch
        Write-Host "Checking $Remote/$targetBranch ..."
        Invoke-Checked "git" @("fetch", $Remote, $targetBranch)

        $localHead = (Invoke-GitOutput @("rev-parse", "HEAD")).Trim()
        $remoteHead = (Invoke-GitOutput @("rev-parse", "$Remote/$targetBranch")).Trim()
        if ($localHead -eq $remoteHead) {
            Write-Host "No update. HEAD is $localHead"
            return
        }

        Write-Host "Updating $localHead -> $remoteHead"
        Invoke-Checked "git" @("merge", "--ff-only", "$Remote/$targetBranch")
        Invoke-Deploy
    }
    finally {
        Pop-Location
    }
}

do {
    if (-not $RepoRoot.Trim()) {
        $RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
    }
    $RepoRoot = (Resolve-Path $RepoRoot).Path

    try {
        Sync-Once
    }
    catch {
        Write-Error $_
        if (-not $Watch) {
            throw
        }
    }

    if ($Watch) {
        Start-Sleep -Seconds $IntervalSeconds
    }
} while ($Watch)
