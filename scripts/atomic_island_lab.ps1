param(
    [ValidateSet('Inspect', 'Install', 'Probe', 'Status', 'Plain', 'Full', 'Island', 'Android', 'Update', 'Loop', 'End', 'Logs')]
    [string]$Action = 'Inspect',
    [string]$Serial,
    [ValidatePattern('^[A-Z][A-Z0-9_]{0,63}$')]
    [string]$Scene = 'FOCUS_TIMER',
    [ValidateSet('com.mutsumi.focus.atomiclab', 'com.vivo.systemuitesttophone')]
    [string]$Package = 'com.mutsumi.focus.atomiclab',
    [string]$Apk,
    [string]$Adb = 'D:\Android\Sdk\platform-tools\adb.exe'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $Adb)) { throw "ADB not found: $Adb" }
$deviceLines = & $Adb devices
$connected = @($deviceLines | Where-Object { $_ -match '^\S+\s+device\s*$' } | ForEach-Object { ($_ -split '\s+')[0] })
if (-not $Serial) {
    if ($connected.Count -ne 1) { throw 'Connect and authorize one vivo/iQOO phone, or specify -Serial. No device was changed.' }
    $Serial = $connected[0]
}
if ($Serial.StartsWith('emulator-')) { throw 'This experiment needs an OriginOS phone, not an Android emulator.' }
if ($Serial -notin $connected) { throw "Device $Serial is unavailable or has not authorized USB debugging." }

function Invoke-LabAdb {
    param([string[]]$Arguments)
    & $Adb -s $Serial @Arguments
    if ($LASTEXITCODE -ne 0) { throw "ADB command failed: $($Arguments -join ' ')" }
}

function Start-LabAction {
    param([string]$Command, [string]$Mode)
    $arguments = @('shell', 'am', 'start', '-n', "$Package/com.mutsumi.focus.atomiclab.AtomicLabActivity", '-f', '0x20000000', '--es', 'action', $Command, '--es', 'scene', $Scene)
    if ($Mode) { $arguments += @('--es', 'mode', $Mode) }
    Invoke-LabAdb -Arguments $arguments
}

switch ($Action) {
    'Inspect' {
        foreach ($property in @('ro.product.manufacturer','ro.product.model','ro.build.version.release','ro.build.version.sdk','ro.vivo.os.version','ro.vivo.os.build.display.id','ro.build.display.id')) {
            Write-Output "$property`:"
            Invoke-LabAdb -Arguments @('shell','getprop',$property)
        }
        # Some vendor builds print valid help but return a nonzero exit code.
        & $Adb -s $Serial shell cmd notification help
        Invoke-LabAdb -Arguments @('shell','pm','path','com.android.systemui')
    }
    'Install' {
        if (-not $Apk) { $Apk = Join-Path $repoRoot 'artifacts\Mutsumi-Atomic-Lab-debug.apk' }
        if (-not (Test-Path -LiteralPath $Apk)) { throw "APK not found: $Apk" }
        $sdkRoot = Split-Path -Parent (Split-Path -Parent $Adb)
        $aapt = Join-Path $sdkRoot 'build-tools\36.0.0\aapt.exe'
        if (-not (Test-Path -LiteralPath $aapt)) { throw "Need aapt to verify the intended APK package: $aapt" }
        $packageLine = (& $aapt dump badging $Apk | Select-String '^package:').Line
        if ($packageLine -notmatch "name='$([regex]::Escape($Package))'") { throw "APK package differs from -Package: $packageLine" }
        if ($Package -eq 'com.vivo.systemuitesttophone') {
            $installed = & $Adb -s $Serial shell pm path $Package
            if ($installed) { throw 'The official demo package already exists on this device. Inspect it before replacing it.' }
        }
        Invoke-LabAdb -Arguments @('install','-r',$Apk)
    }
    'Probe' { Start-LabAction -Command 'probe' }
    'Status' { Start-LabAction -Command 'inspect' }
    'Plain' { Start-LabAction -Command 'create' -Mode 'plain' }
    'Full' { Start-LabAction -Command 'create' -Mode 'full' }
    'Island' { Start-LabAction -Command 'create' -Mode 'island' }
    'Android' { Start-LabAction -Command 'create' -Mode 'android' }
    'Update' { Start-LabAction -Command 'update' }
    'Loop' { Start-LabAction -Command 'loop' }
    'End' { Start-LabAction -Command 'end' }
    'Logs' { Invoke-LabAdb -Arguments @('exec-out','run-as',$Package,'cat','files/atomic-lab.log') }
}
