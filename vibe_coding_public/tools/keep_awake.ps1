param(
    [int]$IntervalSeconds = 30,
    [string]$HeartbeatPath = "runs\keep_awake_heartbeat.txt"
)

$ErrorActionPreference = "Stop"

$signature = @"
using System;
using System.Runtime.InteropServices;

public static class KeepAwakeNative {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@

Add-Type -TypeDefinition $signature -ErrorAction SilentlyContinue

$ES_CONTINUOUS = [uint32]2147483648
$ES_SYSTEM_REQUIRED = [uint32]1
$ES_DISPLAY_REQUIRED = [uint32]2

$heartbeatFullPath = Join-Path (Get-Location) $HeartbeatPath
$heartbeatDir = Split-Path -Parent $heartbeatFullPath
if ($heartbeatDir -and -not (Test-Path $heartbeatDir)) {
    New-Item -ItemType Directory -Path $heartbeatDir | Out-Null
}

Write-Host "Keeping this Windows session awake. Press Ctrl+C to stop."
Write-Host "Heartbeat: $heartbeatFullPath"

try {
    while ($true) {
        [void][KeepAwakeNative]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED -bor $ES_DISPLAY_REQUIRED)
        $line = "{0} keep-awake heartbeat" -f (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
        Add-Content -Path $heartbeatFullPath -Value $line
        Start-Sleep -Seconds $IntervalSeconds
    }
}
finally {
    [void][KeepAwakeNative]::SetThreadExecutionState($ES_CONTINUOUS)
    Add-Content -Path $heartbeatFullPath -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK") + " keep-awake stopped")
}