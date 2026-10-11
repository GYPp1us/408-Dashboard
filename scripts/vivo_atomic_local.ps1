param(
    [ValidateSet('Inspect', 'Enable', 'Disable')]
    [string]$Action = 'Inspect',
    [Parameter(Mandatory)]
    [string]$Serial,
    [ValidateRange(1024, 65535)]
    [int]$Port = 5037,
    [string]$Adb = 'D:\Android\Sdk\platform-tools\adb.exe'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$scene = 'FOCUS_TIMER'
$packages = @('com.mutsumi.focus.atomiclab', 'com.mutsumi.focus.debug', 'com.mutsumi.focus')
$connected = @(& $Adb -P $Port devices | Where-Object { $_ -match '^\S+\s+device\s*$' } |
    ForEach-Object { ($_ -split '\s+')[0] })
if ($Serial.StartsWith('emulator-') -or $Serial -notin $connected) {
    throw 'Specify an authorized physical phone serial. No configuration was changed.'
}

function Invoke-AtomicAdb {
    param([string[]]$Arguments)
    $result = & $Adb -P $Port -s $Serial @Arguments
    if ($LASTEXITCODE -ne 0) { throw "ADB failed: $($Arguments -join ' ')" }
    return $result
}

# Binder transaction numbers are vendor/firmware specific. Reject an upgrade
# until its framework Stub has been inspected again, including the parcel types.
$build = (Invoke-AtomicAdb @('shell', 'getprop', 'ro.build.display.id')).Trim()
$model = (Invoke-AtomicAdb @('shell', 'getprop', 'ro.product.model')).Trim()
if ($model -ne 'V2505A' -or $build -ne 'PD2505B_A_16.0.30.14.W10') {
    throw "Unverified firmware: $model / $build. Inspect its framework before using this script."
}

function Get-AtomicConfig {
    # Keep only the OEM configuration section, never other apps' notice content.
    $dump = (Invoke-AtomicAdb @('shell', 'dumpsys', 'notification')) -join "`n"
    $start = $dump.IndexOf('SuperXNoti Inform ')
    $end = $dump.IndexOf('SUPERX_CHANGED_INFO', [Math]::Max(0, $start))
    if ($start -lt 0 -or $end -le $start) { throw 'Expected SuperX configuration section missing.' }
    return $dump.Substring($start, $end - $start)
}

function Get-AtomicMappings {
    param([string]$Config)
    $currentPackage = ''
    foreach ($line in ($Config -split "`n")) {
        if ($line -match '^appInfo (\S+)\s*$') { $currentPackage = $Matches[1] }
        elseif ($line -match '^scene (\S+) switch (true|false)\s*$') {
            [pscustomobject]@{ Package = $currentPackage; Scene = $Matches[1]; Enabled = $Matches[2] }
        }
    }
}

function Get-UnrelatedMappings {
    param([object[]]$Mappings)
    return ($Mappings | Where-Object Scene -ne $scene | ForEach-Object {
        "$($_.Package)|$($_.Scene)|$($_.Enabled)"
    } | Sort-Object) -join "`n"
}

$before = Get-AtomicConfig
$beforeMappings = @(Get-AtomicMappings $before)
$conflicts = @($beforeMappings | Where-Object { $_.Scene -eq $scene -and $_.Package -notin $packages })
if ($conflicts.Count) { throw 'FOCUS_TIMER has unrelated packages; refuse to replace its list.' }

if ($Action -ne 'Inspect') {
    $snapshotDir = Join-Path $repoRoot '.tmp\atomic-island-lab\device'
    New-Item -ItemType Directory -Path $snapshotDir -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $before | Set-Content -LiteralPath (Join-Path $snapshotDir "superx-$stamp-before.txt") -Encoding utf8
    if ($Action -eq 'Enable') {
        $command = 'service call notification 209 i32 1 s16 FOCUS_TIMER i32 1 s16 true i32 1 s16 com.mutsumi.focus.atomiclab-com.mutsumi.focus.debug-com.mutsumi.focus i32 1 s16 true-true-true'
    } else {
        # Remove our package mappings; the ROM retains an empty disabled scene.
        $command = "service call notification 209 i32 1 s16 FOCUS_TIMER i32 1 s16 false i32 1 s16 '' i32 1 s16 ''"
    }
    $reply = (Invoke-AtomicAdb @('shell', $command)) -join "`n"
    if ($reply -notmatch '^Result: Parcel\(\s*00000000\s+') { throw "Binder rejected configuration: $reply" }
    $after = Get-AtomicConfig
    $afterMappings = @(Get-AtomicMappings $after)
    $after | Set-Content -LiteralPath (Join-Path $snapshotDir "superx-$stamp-after.txt") -Encoding utf8
    if ((Get-UnrelatedMappings $beforeMappings) -cne (Get-UnrelatedMappings $afterMappings)) {
        throw 'Unrelated mappings changed during the operation. Inspect the saved snapshots.'
    }
    $own = @($afterMappings | Where-Object Scene -eq $scene)
    if ($Action -eq 'Enable') {
        if ($own.Count -ne $packages.Count -or @($own | Where-Object Enabled -ne 'true').Count -or
            (($own.Package | Sort-Object) -join '|') -cne (($packages | Sort-Object) -join '|')) {
            throw 'The requested package mappings were not enabled.'
        }
    } elseif ($own.Count) { throw 'Our package mappings were not removed.' }
    Write-Output "$Action verified; all unrelated package/scene mappings match."
}

foreach ($package in $packages) {
    $reply = (Invoke-AtomicAdb @('shell', 'service', 'call', 'notification', '210',
        's16', $package, 's16', $scene, 'i32', '0')) -join "`n"
    if ($reply -match '00000000\s+0000000([01])\s+') {
        Write-Output "$package`: $scene=$($Matches[1] -eq '1')"
    } else { throw "Unexpected scene status reply: $reply" }
}
