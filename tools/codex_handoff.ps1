# Aciona o Codex para revisar/corrigir uma etapa. Uso: .\tools\codex_handoff.ps1 -Etapa 1 -Nome "Estrutura inicial"
param([Parameter(Mandatory)][int]$Etapa, [Parameter(Mandatory)][string]$Nome)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$estadoPath = Join-Path $root 'docs\controle\estado.json'
$estado = Get-Content $estadoPath -Raw | ConvertFrom-Json
if ($estado.estado_geral -eq 'pausado' -or $estado.retomada_manual_obrigatoria) {
    Write-Error "Projeto pausado: $($estado.motivo_pausa). Aguardando retomada manual."; exit 2
}
$nn = '{0:D2}' -f $Etapa
$promptFile = Join-Path $root "docs\controle\prompt-codex-$nn.md"
$logFile = Join-Path $root "docs\controle\codex-$nn.jsonl"
if (-not (Test-Path $promptFile)) { Write-Error "Prompt ausente: $promptFile"; exit 1 }

$estado.estado_geral = 'aguardando Codex'; $estado.fase = 'revisão'; $estado.ia_responsavel = 'Codex'
$estado | ConvertTo-Json -Depth 5 | Set-Content $estadoPath -Encoding utf8

Push-Location $root
try {
    Get-Content $promptFile -Raw | codex exec --sandbox workspace-write --json - | Tee-Object -FilePath $logFile | Out-Null
    $code = $LASTEXITCODE
} finally { Pop-Location }

$estado = Get-Content $estadoPath -Raw | ConvertFrom-Json
$log = if (Test-Path $logFile) { Get-Content $logFile -Raw } else { '' }
$motivo = $null
if ($code -ne 0) {
    $motivo = switch -Regex ($log) {
        'usage limit|rate limit|quota'  { 'limite de uso'; break }
        'insufficient|credit|balance'   { 'falta de saldo'; break }
        'context length|context window' { 'limite de contexto'; break }
        'unauthorized|401|login'        { 'autenticação'; break }
        'network|ECONN|timeout'         { 'conectividade'; break }
        default                         { 'interrupção de causa desconhecida' }
    }
    $estado.estado_geral = 'pausado'; $estado.motivo_pausa = "Codex: $motivo"; $estado.retomada_manual_obrigatoria = $true
} else {
    $estado.estado_geral = 'em andamento'; $estado.fase = 'validação'; $estado.ia_responsavel = 'Claude'
}
$estado | ConvertTo-Json -Depth 5 | Set-Content $estadoPath -Encoding utf8
exit $code
