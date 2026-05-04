$ErrorActionPreference = "Stop"

$workspaceRoot = "C:\Users\ASHTON-FRITZ\Documents\New project"
$bundleRoot = Join-Path $workspaceRoot "ssd_transfer_bundle"
$payloadRoot = Join-Path $bundleRoot "payload"
$snapshotRoot = Join-Path $payloadRoot "New project"
$manifestPath = Join-Path $bundleRoot "TRANSFER_MANIFEST.json"
$checksumsPath = Join-Path $bundleRoot "SHA256SUMS.txt"
$copyScriptPath = Join-Path $bundleRoot "COPY_TO_EXTERNAL_SSD.ps1"
$readmePath = Join-Path $bundleRoot "README_TRANSFER.txt"
$singleArchivePath = Join-Path $workspaceRoot "Horizon_Orchestra_Full_Transfer_2026-03-22.zip"

$excludeDirs = @(
    "ssd_transfer_bundle",
    ".pytest-tmp",
    ".tmp",
    "__pycache__",
    ".uv-cache",
    ".build-tmp",
    ".test-tmp",
    "_tmp_repo_copy"
)

$excludeDirPatterns = @(
    "pytest-cache-files-*"
)

$excludeFilePatterns = @(
    "*.pyc",
    "*.pyo"
)

if (Test-Path $bundleRoot) {
    Remove-Item -Recurse -Force $bundleRoot
}

New-Item -ItemType Directory -Force -Path $bundleRoot | Out-Null
New-Item -ItemType Directory -Force -Path $payloadRoot | Out-Null
New-Item -ItemType Directory -Force -Path $snapshotRoot | Out-Null

$xdArgs = @()
foreach ($dir in $excludeDirs) {
    $xdArgs += $dir
}

$xfArgs = @()
foreach ($pattern in $excludeFilePatterns) {
    $xfArgs += $pattern
}

$topLevelItems = Get-ChildItem -Force $workspaceRoot
foreach ($item in $topLevelItems) {
    if ($excludeDirs -contains $item.Name) {
        continue
    }
    if ($excludeDirPatterns | Where-Object { $item.Name -like $_ }) {
        continue
    }
    $destination = Join-Path $snapshotRoot $item.Name
    if ($item.PSIsContainer) {
        $extraExcludedPaths = @()
        $nestedDirs = Get-ChildItem -Directory -Recurse -Force $item.FullName -ErrorAction SilentlyContinue
        foreach ($nested in $nestedDirs) {
            if (($excludeDirs -contains $nested.Name) -or ($excludeDirPatterns | Where-Object { $nested.Name -like $_ })) {
                $extraExcludedPaths += $nested.FullName
            }
        }
        $dirArgs = @(
            $item.FullName,
            $destination,
            "/E",
            "/R:1",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NP",
            "/XD"
        ) + $xdArgs + $extraExcludedPaths + @("/XF") + $xfArgs
        $null = & robocopy @dirArgs
        $robocopyCode = $LASTEXITCODE
        if ($robocopyCode -ge 8) {
            throw "Robocopy failed for $($item.FullName) with exit code $robocopyCode"
        }
    } else {
        Copy-Item -LiteralPath $item.FullName -Destination $destination -Force
    }
}

$payloadFiles = Get-ChildItem -Recurse -File -Force $snapshotRoot
$totalBytes = ($payloadFiles | Measure-Object -Property Length -Sum).Sum
$relativeFiles = $payloadFiles | ForEach-Object {
    $_.FullName.Substring($snapshotRoot.Length).TrimStart("\")
}

$manifest = [ordered]@{
    created_at = (Get-Date).ToString("o")
    source_workspace = $workspaceRoot
    bundle_root = $bundleRoot
    snapshot_root = $snapshotRoot
    total_files = $payloadFiles.Count
    total_bytes = [int64]$totalBytes
    total_gb = [math]::Round(($totalBytes / 1GB), 3)
    excluded_directories = $excludeDirs
    excluded_file_patterns = $excludeFilePatterns
    important_paths = @(
        "repo",
        "codex_upstream",
        "dify_upstream",
        "openclaw_upstream",
        "claude_code_upstream",
        "chromium_depot_tools",
        "tests",
        "horizon.py",
        "install.sh",
        "requirements.txt"
    )
    notes = @(
                  "This bundle preserves the New project workspace shape under payload\\New project.",
                  "Transient caches were excluded to keep the transfer cleaner.",
                  "Mobile node_modules is included so the iOS/mobile workspace transfers as-built."
              )
}

$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding utf8

$hashLines = New-Object System.Collections.Generic.List[string]
foreach ($file in $payloadFiles) {
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
    $rel = $file.FullName.Substring($bundleRoot.Length).TrimStart("\")
    $hashLines.Add("$hash *$rel")
}
$hashLines | Set-Content -Path $checksumsPath -Encoding utf8

$copyScript = @'
param(
    [Parameter(Mandatory = $true)]
    [string]$DestinationRoot
)

$ErrorActionPreference = "Stop"
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $DestinationRoot "ssd_transfer_bundle"
New-Item -ItemType Directory -Force -Path $target | Out-Null
$null = robocopy $source $target /E /R:1 /W:1
if ($LASTEXITCODE -ge 8) {
    throw "Copy to external SSD failed with robocopy exit code $LASTEXITCODE"
}
Write-Host "Transfer bundle copied to $target"
'@
$copyScript | Set-Content -Path $copyScriptPath -Encoding utf8

$readme = @"
Horizon Orchestra Transfer Bundle
=================================

Created: $((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))

What is included:
- A staged snapshot of the New project workspace under payload\New project
- Repo work, Horizon state, upstream reference repos, and top-level workspace files
- SHA256 checksums in SHA256SUMS.txt
- A copy helper script in COPY_TO_EXTERNAL_SSD.ps1

What was excluded:
- Cache folders like .pytest-tmp, __pycache__, .uv-cache, .build-tmp, .test-tmp
- Python bytecode files

How to copy this bundle to an external SSD:
1. Plug in the SSD and note its drive letter, for example E:\
2. Run:
   powershell -ExecutionPolicy Bypass -File "$copyScriptPath" -DestinationRoot "E:\"

After transfer:
- Verify hashes using SHA256SUMS.txt if desired
- Mobile dependencies were included in this transfer snapshot
"@
$readme | Set-Content -Path $readmePath -Encoding utf8

if (Test-Path $singleArchivePath) {
    Remove-Item -Force $singleArchivePath
}

tar.exe -a -c -f $singleArchivePath -C $bundleRoot .
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create single transfer archive at $singleArchivePath"
}

Write-Host "Transfer bundle created at $bundleRoot"
Write-Host "Snapshot root: $snapshotRoot"
Write-Host ("Files: {0}" -f $payloadFiles.Count)
Write-Host ("Size (GB): {0}" -f [math]::Round(($totalBytes / 1GB), 3))
Write-Host ("Single archive: {0}" -f $singleArchivePath)
