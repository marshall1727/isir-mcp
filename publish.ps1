# Publikace na GitHub + vytvoreni release (spustit v PowerShellu ve slozce isir-mcp).
# Predpoklad: na GitHubu existuje PRAZDNY repozitar https://github.com/marshall1727/isir-mcp
# Release vznikne automaticky: push tagu vX.Y.Z spusti workflow .github/workflows/release.yml,
# ktery sestavi .mcpb (Claude Desktop), wheel, sdist a zdrojovy zip a zverejni je v zalozce Releases.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path .git) {
  Write-Host "Repozitar uz je inicializovany - jen commit a push."
} else {
  git init | Out-Null
  git branch -M main
}

if (-not (git config user.name) -or -not (git config user.email)) {
  Write-Host "Git nezna vasi identitu. Nastavte ji a spustte skript znovu:"
  Write-Host '  git config --global user.name "marshall1727"'
  Write-Host '  git config --global user.email "ID+marshall1727@users.noreply.github.com"'
  exit 1
}

$version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$tag = "v$version"

git add -A
if (git status --porcelain) {
  git commit -m "isir-mcp $version"
  if ($LASTEXITCODE -ne 0) { throw "git commit selhal." }
} else {
  Write-Host "Nic noveho ke commitu."
}

$remotes = @(git remote)
if ($remotes -notcontains "origin") {
  git remote add origin https://github.com/marshall1727/isir-mcp.git
}
git push -u origin main
if ($LASTEXITCODE -ne 0) { throw "git push selhal." }

if (git tag -l $tag) {
  Write-Host "Tag $tag uz existuje - release se znovu nevytvari. Pro novou verzi zvyste version v pyproject.toml a CHANGELOG.md."
} else {
  git tag -a $tag -m "isir-mcp $version"
  git push origin $tag
  Write-Host "Tag $tag odeslan - GitHub Actions sestavi release."
}

Write-Host ""
Write-Host "Repozitar: https://github.com/marshall1727/isir-mcp"
Write-Host "Prubeh:    https://github.com/marshall1727/isir-mcp/actions"
Write-Host "Release:   https://github.com/marshall1727/isir-mcp/releases/tag/$tag"
