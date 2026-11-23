# VoiceStudio Fork - read-only Windows environment and local API preflight.
# No dependencies installed, models downloaded, settings changed, files created, or secrets printed.
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:3900"
)

$ErrorActionPreference = "Stop"
Write-Host "VoiceStudio Windows preflight (read-only)"
Write-Host ("Timestamp (local): " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"))

if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -ge 6) {
    Write-Warning "This script is intended for Windows."
}

try {
    $os = Get-CimInstance Win32_OperatingSystem
    $cs = Get-CimInstance Win32_ComputerSystem
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $gpus = @(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name)
    Write-Host ("OS: " + $os.Caption + " " + $os.Version)
    Write-Host ("CPU: " + $cpu.Name)
    Write-Host ("RAM (GiB): " + [math]::Round($cs.TotalPhysicalMemory / 1GB, 1))
    Write-Host ("GPUs: " + (($gpus | Sort-Object -Unique) -join ", "))
    $drive = $env:SystemDrive
    if ($drive) {
        $disk = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='" + $drive + "'")
        if ($disk) {
            Write-Host ("System drive free (GiB): " + [math]::Round($disk.FreeSpace / 1GB, 1))
        }
    }
} catch {
    Write-Warning ("Hardware discovery error: " + $_.Exception.Message)
}

foreach ($cmd in @("bun", "node", "git", "ffmpeg", "voicestudio")) {
    $item = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($null -eq $item) {
        Write-Host ("Executable " + $cmd + ": not on PATH")
    } else {
        Write-Host ("Executable " + $cmd + ": found")
    }
}

try {
    $uri = [uri]$BaseUrl
    if ($uri.Scheme -notin @("http", "https")) { throw "BaseUrl must use http or https" }
    $BaseUrl = $BaseUrl.TrimEnd("/")
} catch {
    Write-Error ("Invalid BaseUrl: " + $_.Exception.Message)
    exit 2
}

$failed = $false
foreach ($path in @("/health", "/openapi.json", "/v1/audio/voices")) {
    try {
        $url = $BaseUrl + $path
        # Avoid outputting arbitrary response bodies which may contain personal voice names.
        $response = Invoke-WebRequest -Uri $url -Method Get -UseBasicParsing -TimeoutSec 8
        Write-Host ($path + ": HTTP " + [int]$response.StatusCode)
    } catch {
        $failed = $true
        Write-Warning ($path + ": unavailable (" + $_.Exception.GetType().Name + ")")
    }
}

if ($failed) {
    Write-Host "Some probes failed. This is normal if VoiceStudio is not yet running."
    exit 1
}

Write-Host "API preflight completed; a playable WAV test is still required."
exit 0
