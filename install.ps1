# Instalace isir-mcp (spustit v PowerShellu ve slozce isir-mcp)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "1/3 Vytvarim virtualni prostredi..."
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
Write-Host "2/3 Instaluji balicek a zavislosti..."
& .\.venv\Scripts\pip.exe install -e ".[dev]" -q
Write-Host "3/3 Spoustim offline testy..."
& .\.venv\Scripts\python.exe -m pytest -q

$tess = "C:\Program Files\Tesseract-OCR\tesseract.exe"
if (-not (Test-Path $tess)) {
  Write-Warning "Tesseract nenalezen v $tess - nainstalujte z https://github.com/UB-Mannheim/tesseract/wiki (s jazykem Czech), jinak nebude fungovat OCR skenu."
}

$py = (Resolve-Path .\.venv\Scripts\python.exe).Path
$cache = Join-Path (Split-Path $PSScriptRoot -Parent) "isir-cache"
$cfg = @{
  mcpServers = @{
    isir = @{
      command = $py
      args = @("-m", "isir_mcp.server")
      env = @{
        TESSERACT_CMD = $tess
        ISIR_OCR_LANG = "ces+eng"
        ISIR_CACHE_DIR = $cache
      }
    }
  }
} | ConvertTo-Json -Depth 5

Write-Host ""
Write-Host "Hotovo. Do %APPDATA%\Claude\claude_desktop_config.json pridejte (nebo slucte) tento blok:"
Write-Host ""
Write-Host $cfg
$cfg | Set-Content -Encoding UTF8 (Join-Path $PSScriptRoot "claude_desktop_config.snippet.json")
Write-Host ""
Write-Host "(ulozeno tez do claude_desktop_config.snippet.json)"
