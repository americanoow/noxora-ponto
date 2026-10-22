# PostgreSQL 17 portátil para desenvolvimento e testes SEM Docker (Windows).
# Uso:  .\tools\postgres_local.ps1 setup | start | stop | status | env
#
# - Instala em .local/postgres (ignorado pelo Git). Escuta somente em 127.0.0.1:5433, sem senha
#   (autenticação "trust"): serve apenas para desenvolvimento local, NUNCA para dados reais.
# - O zip oficial da EDB é baixado uma vez e conferido por SHA-256 (valor registrado abaixo).
#   Para reaproveitar um zip já baixado: setup -ZipPath C:\caminho\pg17.zip
param(
    [Parameter(Mandatory)][ValidateSet('setup', 'start', 'stop', 'status', 'env')][string]$Action,
    [string]$ZipPath
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$base = Join-Path $root '.local\postgres'
$bin = Join-Path $base 'pgsql\bin'
$data = Join-Path $base 'data'
$port = 5433
$version = '17.5-1'
$url = "https://get.enterprisedb.com/postgresql/postgresql-$version-windows-x64-binaries.zip"
$sha256 = '795196df1b2855fd0c7fb52629c6cc16acaa85819912e732bd4c46863e77eb30'  # conferido na primeira baixa

function Test-Server { & "$bin\pg_isready.exe" -h 127.0.0.1 -p $port 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }

switch ($Action) {
    'setup' {
        if (-not (Test-Path "$bin\postgres.exe")) {
            New-Item -ItemType Directory -Force $base | Out-Null
            $zip = if ($ZipPath) { $ZipPath } else { Join-Path $base 'pg.zip' }
            if (-not (Test-Path $zip)) { Invoke-WebRequest -Uri $url -OutFile $zip }
            $hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
            if ($hash -ne $sha256) { throw "SHA-256 inesperado ($hash). Arquivo recusado." }
            # tar.exe (nativo no Windows 10+) é muito mais rápido que Expand-Archive para ~18 mil arquivos.
            # Caminho completo: no PATH pode haver um tar GNU (Git Bash) que não lê zip.
            & "$env:SystemRoot\System32\tar.exe" -xf $zip -C $base
            if ($LASTEXITCODE -ne 0) { throw 'Falha ao extrair o PostgreSQL.' }
        }
        if (-not (Test-Path "$data\PG_VERSION")) {
            & "$bin\initdb.exe" -D $data -U noxora -A trust -E UTF8 --locale=C | Out-Null
        }
        Write-Host "PostgreSQL pronto em $base. Execute: .\tools\postgres_local.ps1 start"
    }
    'start' {
        if (Test-Server) { Write-Host "Já em execução na porta $port."; break }
        # Start-Process evita que o pg_ctl fique preso à saída do servidor.
        Start-Process -FilePath "$bin\pg_ctl.exe" -WindowStyle Hidden -ArgumentList @(
            '-D', "`"$data`"", '-l', "`"$base\server.log`"", '-w', 'start',
            '-o', "`"-p $port -c listen_addresses=127.0.0.1 -c fsync=off -c max_connections=60`""
        )
        for ($i = 0; $i -lt 30 -and -not (Test-Server); $i++) { Start-Sleep -Seconds 1 }
        if (-not (Test-Server)) { throw "Servidor não respondeu. Veja $base\server.log" }
        $exists = & "$bin\psql.exe" -h 127.0.0.1 -p $port -U noxora -d postgres -Atc "select 1 from pg_database where datname='noxora'"
        if (-not $exists) { & "$bin\psql.exe" -h 127.0.0.1 -p $port -U noxora -d postgres -c "create database noxora" | Out-Null }
        Write-Host "PostgreSQL em execução. Use: `$env:DATABASE_URL = 'postgres://noxora@127.0.0.1:$port/noxora'"
    }
    'stop' { & "$bin\pg_ctl.exe" -D $data -m fast stop }
    'status' { if (Test-Server) { Write-Host 'em execução' } else { Write-Host 'parado'; exit 1 } }
    'env' { Write-Output "postgres://noxora@127.0.0.1:$port/noxora" }
}
