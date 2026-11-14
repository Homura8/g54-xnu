<#
.SYNOPSIS
  Read the G54 kernel log from the USB serial console (kernel patch 0210, boot-arg g54usb=1).

.DESCRIPTION
  Finds the CDC-ACM port with USB ID 1209:0003 (or uses -Port), opens it with DTR on
  (which makes the phone replay its whole 4 MiB log ring, then follow it live) and
  copies everything to the console and to -Out. Read-only: nothing is written to the
  phone. Stop with Ctrl+C, or use -Seconds for a bounded capture.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\g54_console.ps1 -Out out\usblog\boot.log -Seconds 30
#>
param(
    [string]$Port = "",
    [string]$Out = "",
    [int]$Seconds = 0,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

function Find-G54Port {
    $dev = Get-CimInstance Win32_PnPEntity |
        Where-Object { $_.PNPDeviceID -like 'USB\VID_1209&PID_0003*' -and $_.Name -match '\((COM\d+)\)' } |
        Select-Object -First 1
    if ($dev -and $dev.Name -match '\((COM\d+)\)') { return $Matches[1] }
    return ""
}

if (-not $Port) { $Port = Find-G54Port }
if (-not $Port) {
    Write-Error "No G54 USB console (USB\VID_1209&PID_0003) found. Is the phone booted with g54usb=1 and plugged in?"
}

$sp = New-Object System.IO.Ports.SerialPort $Port, 115200, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$sp.DtrEnable = $true          # DTR 0->1: the phone replays the log ring from its oldest byte
$sp.RtsEnable = $true
$sp.ReadTimeout = 500
$sp.ReadBufferSize = 1MB
$sp.Encoding = [System.Text.Encoding]::GetEncoding(28591)   # bytes 1:1 (Latin-1)
$sp.Open()

$writer = $null
if ($Out) {
    $dir = Split-Path -Parent $Out
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    $writer = New-Object System.IO.StreamWriter($Out, $false, [System.Text.Encoding]::GetEncoding(28591))
}

$total = 0
$start = Get-Date
Write-Host "G54 console on $Port (Ctrl+C to stop)$(if ($Out) { ", saving to $Out" })"
try {
    while ($true) {
        if ($Seconds -gt 0 -and ((Get-Date) - $start).TotalSeconds -ge $Seconds) { break }
        $chunk = $sp.ReadExisting()
        if ($chunk.Length -gt 0) {
            $total += $chunk.Length
            if ($writer) { $writer.Write($chunk); $writer.Flush() }
            if (-not $Quiet) { [Console]::Out.Write($chunk) }
        } else {
            Start-Sleep -Milliseconds 50
        }
    }
} finally {
    $sp.DtrEnable = $false
    $sp.Close()
    if ($writer) { $writer.Close() }
    Write-Host "`n[$total bytes from $Port]"
}
