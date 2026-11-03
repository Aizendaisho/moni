<#
  Instala todo lo que el proyecto necesita en Windows 10/11.
  Uso (doble clic en scripts\setup.bat, o desde PowerShell):
      .\scripts\setup.ps1              # todo
      .\scripts\setup.ps1 -SinModelos  # todo menos los modelos de IA (unos 5 GB)

  Es seguro ejecutarlo varias veces: lo que ya está instalado se salta.
#>
param(
    [switch]$SinModelos
)

# "Continue": los programas como uv escriben su progreso en stderr y no debe tomarse como error.
$ErrorActionPreference = "Continue"
$Raiz = Split-Path -Parent $PSScriptRoot
$Fallos = @()

function Paso($texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }
function Ok($texto) { Write-Host "    OK  $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    !!  $texto" -ForegroundColor Yellow }

function Refrescar-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                "$env:USERPROFILE\.cargo\bin;$env:USERPROFILE\.local\bin"
}

function Instalar-Winget($id, $nombre, $comando, $extra = @()) {
    if ($comando -and (Get-Command $comando -ErrorAction SilentlyContinue)) {
        Ok "$nombre ya está instalado"
        return
    }
    $lista = winget list --id $id --exact --accept-source-agreements 2>$null | Out-String
    if ($lista -match [regex]::Escape($id)) {
        Ok "$nombre ya está instalado"
        return
    }
    Write-Host "    Instalando $nombre..."
    $wingetArgs = @("install", "--id", $id, "--exact", "--silent",
              "--accept-package-agreements", "--accept-source-agreements") + $extra
    & winget @wingetArgs
    if ($LASTEXITCODE -ne 0) {
        Aviso "No se pudo instalar $nombre (código $LASTEXITCODE)"
        $script:Fallos += $nombre
    } else {
        Ok "$nombre instalado"
    }
    Refrescar-Path
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "Falta winget. Instala 'App Installer' desde Microsoft Store y vuelve a ejecutar." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- 1. Programas
Paso "1/5 Programas base (winget)"
Instalar-Winget "Git.Git"                       "Git"                 "git"
Instalar-Winget "astral-sh.uv"                  "uv (Python)"         "uv"
Instalar-Winget "OpenJS.NodeJS.LTS"             "Node.js LTS"         "node"
Instalar-Winget "Rustlang.Rustup"               "Rust (rustup)"       "rustup"
Instalar-Winget "Microsoft.EdgeWebView2Runtime" "WebView2"            $null
Instalar-Winget "Ollama.Ollama"                 "Ollama"              "ollama"
Instalar-Winget "GodotEngine.GodotEngine"       "Godot 4"             $null
Instalar-Winget "Gyan.FFmpeg"                   "FFmpeg"              "ffmpeg"
# Compilador de C++ que Tauri necesita en Windows (descarga grande, ~3 GB)
Instalar-Winget "Microsoft.VisualStudio.2022.BuildTools" "Visual Studio Build Tools (C++)" $null `
    @("--override", "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended")

Refrescar-Path
if (Get-Command rustup -ErrorAction SilentlyContinue) {
    rustup default stable | Out-Null
    Ok "Rust stable configurado"
}

# ---------------------------------------------------------------- 2. Python
Paso "2/5 Núcleo Python (core) con todas las dependencias"
Push-Location "$Raiz\core"
try {
    uv python install 3.11
    uv sync --extra todo
    if ($LASTEXITCODE -ne 0) { throw "uv sync falló" }
    Ok "Dependencias de Python instaladas"
    uv run playwright install chromium
    if ($LASTEXITCODE -eq 0) { Ok "Navegador de Playwright instalado" } else { Aviso "Playwright no pudo descargar Chromium"; $Fallos += "Playwright" }
} catch {
    Aviso $_; $Fallos += "Python (core)"
} finally { Pop-Location }

# ---------------------------------------------------------------- 3. App
Paso "3/5 App de escritorio (Tauri + React)"
Push-Location "$Raiz\app"
try {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install falló" }
    Ok "Dependencias de la app instaladas"
} catch {
    Aviso $_; $Fallos += "App (npm)"
} finally { Pop-Location }

# ---------------------------------------------------------------- 4. Modelos
if ($SinModelos) {
    Paso "4/5 Modelos de IA: omitidos (-SinModelos)"
} else {
    Paso "4/5 Modelos de Ollama (LLM, visión, embeddings)"
    if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
        Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 5
    }
    foreach ($m in @("qwen3:4b", "moondream", "nomic-embed-text")) {
        Write-Host "    Descargando $m..."
        ollama pull $m
        if ($LASTEXITCODE -eq 0) { Ok $m } else { Aviso "Falló $m"; $Fallos += "Ollama: $m" }
    }

    Paso "5/5 Modelos de voz (Whisper, Piper, palabra de activación)"
    Push-Location "$Raiz\core"
    try {
        uv run python "$Raiz\scripts\descargar_modelos.py"
        if ($LASTEXITCODE -ne 0) { throw "descarga de modelos de voz falló" }
    } catch {
        Aviso $_; $Fallos += "Modelos de voz"
    } finally { Pop-Location }
}

# ---------------------------------------------------------------- Resumen
Write-Host ""
if ($Fallos.Count -eq 0) {
    Write-Host "Todo listo. Cierra esta ventana, abre una nueva terminal y ejecuta scripts\dev.bat" -ForegroundColor Green
} else {
    Write-Host "Terminó con problemas en: $($Fallos -join ', ')" -ForegroundColor Yellow
    Write-Host "Vuelve a ejecutar el script; lo que ya está instalado se salta."
}
