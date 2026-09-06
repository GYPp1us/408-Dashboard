param(
    [ValidateSet('Debug', 'Release')]
    [string]$Variant = 'Debug'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$androidRoot = Join-Path $repoRoot 'android'

if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = 'D:\Android\Sdk' }
if (-not $env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT = $env:ANDROID_HOME }
if (-not $env:GRADLE_USER_HOME) { $env:GRADLE_USER_HOME = 'D:\GradleUserHome' }
if (-not $env:JAVA_HOME) { $env:JAVA_HOME = 'C:\Program Files\Java\jdk-21' }
$env:TMP = Join-Path $repoRoot '.tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null

$taskSuffix = if ($Variant -eq 'Release') { 'Release' } else { 'Debug' }
& (Join-Path $androidRoot 'gradlew.bat') -p $androidRoot 'testDebugUnitTest' "lint${taskSuffix}" "assemble${taskSuffix}"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$apk = Join-Path $androidRoot "app\build\outputs\apk\$($Variant.ToLowerInvariant())\app-$($Variant.ToLowerInvariant()).apk"
Write-Host "APK: $apk"
