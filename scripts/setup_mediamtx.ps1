# PowerShell setup script for MediaMTX (v1.20.1) on Windows
# Downloads standalone pre-built mediamtx.exe into data/bin/mediamtx/

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
$BinDir = Join-Path $ProjectRoot "data\bin\mediamtx"
$ExePath = Join-Path $BinDir "mediamtx.exe"
$Version = "v1.20.1"
$DownloadUrl = "https://github.com/bluenviron/mediamtx/releases/download/$Version/mediamtx_${Version}_windows_amd64.zip"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " IBVAP - MediaMTX Windows Setup ($Version)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

if (-not (Test-Path $BinDir)) {
    Write-Host "Creating directory: $BinDir" -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
}

if (Test-Path $ExePath) {
    Write-Host "MediaMTX binary already present at: $ExePath" -ForegroundColor Green
} else {
    Write-Host "Downloading MediaMTX $Version for Windows x64..." -ForegroundColor Yellow
    Write-Host "URL: $DownloadUrl"
    
    $TempZip = Join-Path $BinDir "mediamtx.zip"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $TempZip -UseBasicParsing
        
        Write-Host "Extracting archive..." -ForegroundColor Yellow
        Expand-Archive -Path $TempZip -DestinationPath $BinDir -Force
        
        if (Test-Path $ExePath) {
            Write-Host "MediaMTX successfully installed to: $ExePath" -ForegroundColor Green
        } else {
            Write-Error "Extraction failed: mediamtx.exe not found in $BinDir"
            exit 1
        }
    } finally {
        if (Test-Path $TempZip) {
            Remove-Item -Path $TempZip -Force -ErrorAction SilentlyContinue
        }
    }
}

Write-Host "`nUsage Instructions:" -ForegroundColor Cyan
Write-Host "  1. Start MediaMTX in background or separate console:"
Write-Host "     & '$ExePath'" -ForegroundColor Yellow
Write-Host "  2. Service Endpoints:"
Write-Host "     - REST API:   http://localhost:9997"
Write-Host "     - RTSP:       rtsp://localhost:8554"
Write-Host "     - WebRTC:     http://localhost:8889"
Write-Host "     - HLS:        http://localhost:8888"
Write-Host "==========================================" -ForegroundColor Cyan
