# Aciona o Codex para revisar/corrigir uma etapa. Uso: .\tools\codex_handoff.ps1 -Etapa 1 -Nome "Estrutura inicial"
param([Parameter(Mandatory)][int]$Etapa, [Parameter(Mandatory)][string]$Nome)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$estadoPath = Join-Path $root 'docs\controle\estado.json'
function Read-Estado { [IO.File]::ReadAllText($estadoPath, [Text.Encoding]::UTF8) | ConvertFrom-Json }
function Save-Estado($e) { [IO.File]::WriteAllText($estadoPath, ($e | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false)) }
$estado = Read-Estado
if ($estado.estado_geral -eq 'pausado' -or $estado.retomada_manual_obrigatoria) {
    Write-Error "Projeto pausado: $($estado.motivo_pausa). Aguardando retomada manual."; exit 2
}
$nn = '{0:D2}' -f $Etapa
$promptFile = Join-Path $root "docs\controle\prompt-codex-$nn.md"
$logFile = Join-Path $root "docs\controle\codex-$nn.jsonl"
if (-not (Test-Path $promptFile)) { Write-Error "Prompt ausente: $promptFile"; exit 1 }

$estado.estado_geral = 'aguardando Codex'; $estado.fase = 'revisão'; $estado.ia_responsavel = 'Codex'
Save-Estado $estado

Push-Location $root
try {
    Get-Content $promptFile -Raw | codex exec --sandbox workspace-write --json - | Tee-Object -FilePath $logFile | Out-Null
    $code = $LASTEXITCODE
} finally { Pop-Location }

$estado = Read-Estado
$log = if (Test-Path $logFile) { Get-Content $logFile -Raw -Encoding UTF8 } else { '' }
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
Save-Estado $estado
exit $code
