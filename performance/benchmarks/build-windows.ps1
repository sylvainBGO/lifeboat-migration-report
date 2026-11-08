param(
    [Parameter(Mandatory=$true)][string]$BaselineSource,
    [Parameter(Mandatory=$true)][string]$FinalSource,
    [string]$OutputDirectory = 'benchmark-delivery'
)
$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$baseline = (Resolve-Path $BaselineSource).Path
$final = (Resolve-Path $FinalSource).Path
$destination = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force $destination | Out-Null
$buildRoot = Join-Path $repository 'benchmark-build'
New-Item -ItemType Directory -Force $buildRoot | Out-Null

foreach ($variant in @(@('Baseline', $baseline), @('Final', $final))) {
    $name = "Lifeboat-$($variant[0])-Worker"
    $variantSource = $variant[1]
    python -m PyInstaller --noconfirm --clean --onefile --console --name $name --paths $variantSource --collect-submodules codex_transfer --distpath $destination --workpath "$buildRoot/$name" --specpath $buildRoot "$PSScriptRoot/restore_worker.py"
    if ($LASTEXITCODE -ne 0) { throw "$name build failed" }
}
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Lifeboat-Benchmark --paths $final --hidden-import codex_transfer.defender_control --distpath $destination --workpath "$buildRoot/launcher" --specpath $buildRoot "$PSScriptRoot/benchmark.py"
if ($LASTEXITCODE -ne 0) { throw 'Benchmark UI build failed' }
Copy-Item "$PSScriptRoot/BENCHMARK-GUIDE.md" "$destination/LISEZMOI.md"
Copy-Item "$final/../LICENSE" "$destination/LICENSE-Lifeboat.txt"
Copy-Item "$PSScriptRoot/scenarios.json" $destination
@'
@echo off
cd /d "%~dp0"
start "Lifeboat" "Lifeboat-Benchmark.exe" --gui
'@ | Set-Content "$destination/Lancer-Benchmark.cmd" -Encoding ascii
python "$PSScriptRoot/write_build_identity.py" --baseline-source $baseline --final-source $final --directory $destination --repository $repository
if ($LASTEXITCODE -ne 0) { throw 'Benchmark build identity failed' }
