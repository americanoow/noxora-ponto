# Aciona o Codex para REVISAO SOMENTE LEITURA de uma etapa.
# Uso: .\tools\codex_handoff.ps1 -Etapa 6 -Nome "Reconhecimento facial"
#
# - Sandbox read-only: o Codex nao escreve no projeto. O script confere o arvore antes/depois e sinaliza violacao.
# - O relatorio (ultima mensagem do Codex) e salvo em docs/etapas/NN-revisao.md; o Claude completa as demais secoes.
# - Respeita pausa por limite de uso; classifica falhas apenas pelos eventos de erro da ferramenta.
# Este arquivo precisa ser salvo em UTF-8 COM BOM (PowerShell 5.1 le arquivos sem BOM como ANSI).
param([Parameter(Mandatory)][int]$Etapa, [Parameter(Mandatory)][string]$Nome)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding $false
$root = Split-Path $PSScriptRoot -Parent
$estadoPath = Join-Path $root 'docs\controle\estado.json'
function Read-Estado { [IO.File]::ReadAllText($estadoPath, [Text.Encoding]::UTF8) | ConvertFrom-Json }
function Save-Estado($e) { [IO.File]::WriteAllText($estadoPath, ($e | ConvertTo-Json -Depth 5), $utf8) }

$estado = Read-Estado
if ($estado.estado_geral -eq 'pausado' -or $estado.retomada_manual_obrigatoria) {
    Write-Error "Projeto pausado: $($estado.motivo_pausa). Aguardando retomada manual."; exit 2
}
$nn = '{0:D2}' -f $Etapa
$promptFile = Join-Path $root "docs\controle\prompt-codex-$nn.md"
$logFile = Join-Path $root "docs\controle\codex-$nn.jsonl"
$reportTmp = Join-Path $env:TEMP "codex-revisao-$nn.md"
$reportFile = Join-Path $root "docs\etapas\$nn-revisao.md"
if (-not (Test-Path $promptFile)) { Write-Error "Prompt ausente: $promptFile"; exit 1 }
if (Test-Path $reportTmp) { Remove-Item $reportTmp -Force }

function Get-TreeFingerprint {
    # Hash de todo arquivo modificado ou nao rastreado (exceto logs e estado.json, escritos pelo proprio mecanismo).
    Push-Location $root
    try {
        $files = & git ls-files -m -o --exclude-standard 2>$null | Where-Object { $_ -and ($_ -notmatch '^docs/controle/(codex-|estado\.json$)') }
        $map = [ordered]@{}
        foreach ($f in $files) {
            if (Test-Path -LiteralPath $f -PathType Leaf) { $map[$f] = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash }
        }
        $head = (& git rev-parse HEAD 2>$null)
        return ($head + "`n" + (($map.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "`n"))
    } finally { Pop-Location }
}

$before = Get-TreeFingerprint
$estado.estado_geral = 'aguardando Codex'; $estado.fase = 'revisão (somente leitura)'; $estado.ia_responsavel = 'Codex'
Save-Estado $estado

$OutputEncoding = $utf8   # o prompt segue UTF-8 ao CLI do Codex
Push-Location $root
try {
    Get-Content $promptFile -Raw -Encoding UTF8 |
        codex exec --sandbox read-only --ephemeral --json -o $reportTmp - |
        Tee-Object -FilePath $logFile | Out-Null
    $code = $LASTEXITCODE
} finally { Pop-Location }

$after = Get-TreeFingerprint
$estado = Read-Estado
$log = if (Test-Path $logFile) { [IO.File]::ReadAllText($logFile, [Text.Encoding]::UTF8) } else { '' }
$report = if (Test-Path $reportTmp) { [IO.File]::ReadAllText($reportTmp, [Text.Encoding]::UTF8).Trim() } else { '' }

if ($code -ne 0 -or -not $report) {
    # Classifica so pelos eventos de erro da ferramenta, nunca pelo texto do codigo revisado.
    $erros = ($log -split "`n" | Where-Object { $_ -match '"type"\s*:\s*"(error|turn\.failed)"' }) -join "`n"
    $detalhe = if ($erros) { ($erros -split "`n")[-1].Trim() } else { 'sem evento de erro no log' }
    $motivo = switch -Regex ($erros) {
        'usage limit|rate limit|quota'  { 'limite de uso'; break }
        'insufficient|credit|balance'   { 'falta de saldo'; break }
        'context length|context window' { 'limite de contexto'; break }
        'unauthorized|401|login'        { 'autenticação'; break }
        'network|ECONN|timeout'         { 'conectividade'; break }
        default                         { 'interrupção de causa desconhecida' }
    }
    $estado.estado_geral = 'pausado'; $estado.ia_responsavel = 'nenhuma (projeto pausado)'
    $estado.motivo_pausa = "Codex: $motivo. Mensagem da ferramenta: $detalhe"
    $estado.retomada_manual_obrigatoria = $true
    Save-Estado $estado
    if ($before -ne $after) { Write-Warning 'O projeto foi alterado durante a execução (alterações parciais preservadas). Inspecione com git status.' }
    exit $(if ($code -ne 0) { $code } else { 1 })
}

# Relatorio bruto, sem edicao, na secao 1. Se ja existir revisao da etapa, entra como revisao complementar.
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
$raw = "## Apontamentos originais do Codex (relatório bruto, não editado) — $stamp`n`n$report`n"
if (Test-Path $reportFile) {
    $existing = [IO.File]::ReadAllText($reportFile, [Text.Encoding]::UTF8)
    [IO.File]::WriteAllText($reportFile, $existing.TrimEnd() + "`n`n---`n`n# Revisão complementar`n`n$raw", $utf8)
} else {
    $skeleton = "# Etapa $nn — Revisão ($Nome)`n`n" +
        "> Divisão vigente: o Codex apenas revisa; o Claude analisa, corrige e valida. " +
        "Não consta aprovação do Codex para correções que ele não revisou.`n`n" + $raw + "`n" +
        "## Análise e correções do Claude`n`n_(para cada apontamento: confirmado / refutado com evidência / suspeita a verificar; correção feita; arquivos)_`n`n" +
        "## Testes executados e resultados`n`n_(pendente)_`n`n" +
        "## Pendências`n`n_(pendente)_`n`n" +
        "## Revisão complementar necessária?`n`n_(pendente: sim/não e motivo)_`n"
    [IO.File]::WriteAllText($reportFile, $skeleton, $utf8)
}

$estado.estado_geral = 'em andamento'; $estado.fase = 'correção (Claude)'; $estado.ia_responsavel = 'Claude'
Save-Estado $estado
if ($before -ne $after) {
    Write-Warning 'VIOLAÇÃO DA REGRA SOMENTE-LEITURA: o projeto mudou durante a revisão. Inspecione com git status/diff antes de seguir.'
    exit 3
}
Write-Host "Relatório salvo em docs/etapas/$nn-revisao.md"
exit 0
