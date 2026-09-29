param(
    [string]$Sdk = 'D:\Android\Sdk',
    [string]$Jdk = 'C:\Program Files\Java\jdk-21',
    [string]$Serial = 'emulator-5556',
    [switch]$NoPush
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$helperRoot = $PSScriptRoot
$repoRoot = Split-Path (Split-Path $helperRoot -Parent) -Parent
$outputRoot = Join-Path $repoRoot '.tmp\android-ui'
$classes = Join-Path $outputRoot 'classes'
$dex = Join-Path $outputRoot 'dex'
$helperJar = Join-Path $outputRoot 'live-ui-helper.jar'
$javac = Join-Path $Jdk 'bin\javac.exe'
$jar = Join-Path $Jdk 'bin\jar.exe'
$androidJar = Join-Path $Sdk 'platforms\android-36\android.jar'
$d8 = Join-Path $Sdk 'build-tools\36.0.0\d8.bat'
$adb = Join-Path $Sdk 'platform-tools\adb.exe'
foreach ($required in @($javac, $jar, $androidJar, $d8, (Join-Path $helperRoot 'LiveUiSnapshot.java'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing build dependency: $required" }
}
if (-not $NoPush -and -not (Test-Path -LiteralPath $adb -PathType Leaf)) { throw "Missing adb: $adb" }
New-Item -ItemType Directory -Force -Path $classes,$dex | Out-Null
& $javac --release 8 -cp $androidJar -d $classes (Join-Path $helperRoot 'LiveUiSnapshot.java')
if ($LASTEXITCODE) { throw 'javac failed' }
& $d8 --min-api 26 --lib $androidJar --output $dex (Join-Path $classes 'LiveUiSnapshot.class')
if ($LASTEXITCODE) { throw 'd8 failed' }
& $jar --create --file $helperJar -C $dex classes.dex
if ($LASTEXITCODE) { throw 'jar failed' }
if (-not (Test-Path -LiteralPath $helperJar -PathType Leaf)) { throw 'jar output missing' }
if ($NoPush) {
    Write-Output "Built $helperJar; device unchanged."
} else {
    & $adb -s $Serial push $helperJar /data/local/tmp/live-ui-helper.jar
    if ($LASTEXITCODE) { throw 'adb push failed' }
    Write-Output "Built and pushed $helperJar. Read-only snapshot: adb -s $Serial shell CLASSPATH=/data/local/tmp/live-ui-helper.jar app_process /system/bin LiveUiSnapshot dump"
}
