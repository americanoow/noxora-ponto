# Operação do Noxora Ponto

> Nada aqui deve ser executado em produção, contratado ou publicado sem autorização do responsável pelo produto.

## 1. Implantação de referência (servidor com Docker)
```bash
cp deploy/env.prod.example deploy/.env.prod        # preencher (nunca versionar)
mkdir -p deploy/secrets
python3 -c "import os,base64,json;print(json.dumps({'k1':base64.b64encode(os.urandom(32)).decode()}))" > deploy/secrets/biometric_keys.json
chmod 600 deploy/secrets/biometric_keys.json deploy/.env.prod
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod up -d --build
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod exec backend python manage.py create_platform_admin voce@empresa.com
```
- `migrate` roda `preflight` (bloqueia se houver dados incompatíveis), `migrate` e `check --deploy`; só depois sobem `backend` e `worker`.
- `edge` (Caddy) obtém certificado TLS automaticamente para `DOMAIN` (portas 80/443 abertas e DNS apontando para o servidor).
- O papel `noxora_app` é criado na primeira subida do banco (`deploy/db-init/01-roles.sh`) sem ser dono das tabelas.
- Proxy corporativo: `docker build --secret id=extra_ca,src=ca.crt ...`; imagens base alternativas: `--build-arg PYTHON_IMAGE=... NODE_IMAGE=... CADDY_IMAGE=...`.

### PostgreSQL gerenciado (Supabase)
Remova o serviço `db` e use em `DATABASE_URL`/`MIGRATE_DATABASE_URL` a conexão direta ou o pooler em **modo sessão** com `sslmode=require` (o modo transação não preserva estado de sessão e exige desligar prepared statements; não foi testado). Requisitos: extensão `btree_gist` (disponível no Supabase), papel da aplicação sem propriedade das tabelas, backups PITR do plano escolhido **mais** os backups lógicos abaixo. O produto **não** usa armazenamento de arquivos hoje (imagens faciais nunca são gravadas; relatórios são gerados sob demanda), então o Storage do Supabase não é necessário. Regras de negócio permanecem no backend (não usar acesso direto do cliente ao banco).

## 2. Tarefas periódicas (`worker`)
`python manage.py run_worker`: e-mails da outbox (10 s), cobrança (`run_billing`, 1 h), `verify_timeclock` (24 h; problemas aparecem como log `ERROR` "tarefa com alerta") e retenção da biometria (`purge_biometrics`, 24 h: rosto de inativos há `BIOMETRIC_INACTIVE_RETENTION_DAYS`, padrão 30; tentativas não usadas há `BIOMETRIC_ATTEMPT_RETENTION_DAYS`, padrão 90 — validar os prazos com o jurídico). Comandos avulsos: `process_outbox`, `run_billing`, `verify_timeclock`, `purge_biometrics [--inactive-days N] [--dry-run]`.

## 3. Backup e restauração verificada
```bash
DATABASE_URL=postgres://... BACKUP_DIR=/backups BACKUP_PASSFILE=/run/secrets/backup_pass ./ops/backup.sh
ADMIN_DATABASE_URL=postgres://dono@host/postgres BACKUP_PASSFILE=... ./ops/restore_verify.sh /backups/noxora-AAAA.dump.enc
```
A verificação restaura num banco temporário e confere SHA-256 do arquivo, migrations em dia, cadeia de marcações, presença dos gatilhos de proteção e contagens do manifesto. **Executado em 2026-10-27** com dados de demonstração (371 marcações): "RESTAURAÇÃO VERIFICADA". Recomendação: backup diário + teste de restauração semanal, cópia fora do provedor, retenção definida com o jurídico (prazo legal de guarda da ARP é pendência).

## 4. Chaves e segredos
| Segredo | Onde | Rotação |
|---|---|---|
| `DJANGO_SECRET_KEY` | ambiente | trocar mantendo a anterior em `SECRET_KEY_FALLBACKS` até expirarem sessões/links; afeta MFA e outbox (lidos também com as chaves antigas para MFA) |
| Chaves biométricas | arquivo `BIOMETRIC_KEYS_FILE` | acrescentar nova chave, mudar `BIOMETRIC_ACTIVE_KEY_ID`, `rotate_biometric_key`, conferir `--check`, remover a antiga |
| Senhas do banco | `.env.prod` | papel por papel, sem derrubar o `backend` |
| `BILLING_WEBHOOK_SECRET` | ambiente | combinar com o gateway |
KMS/HSM e crypto-shredding por registro são evolução recomendada (pendência).

## 5. Monitoramento
- `GET /api/health/` (processo) e `GET /api/ready/` (banco) para o balanceador.
- Logs JSON em stdout com `X-Request-ID` em cada resposta e linha de acesso (sem corpo nem query string).
- Alertas sugeridos: `ready` falhando; log `tarefa com alerta` (cadeia); `OutboundEmail` com status `failed`; faturas `failed`; 5xx acima do normal.
- Sentry/APM: não incluído (decisão de fornecedor).

## 6. Desempenho medido (2026-10-27, 4 CPUs compartilhadas por gerador, gunicorn 4×4 e PostgreSQL 16)
`ops/loadtest_punches.py`: 3000 marcações + 300 reenvios via HTTP: **0 duplicidade, 0 perda, cadeia íntegra**; ~150 req/s; p50 200–260 ms, p95 0,4–1,1 s. O NSR serializa por unidade (bloqueio de linha); unidades diferentes gravam em paralelo. Limite por tablet: `DEVICE_RATE_LIMIT` (padrão 120/min).

## 7. Incidentes comuns
- **Tablet perdido/roubado**: painel → revogar (efeito no próximo acesso). Fila offline do aparelho fica retida; reativar o mesmo cadastro envia a fila.
- **Usuário perdeu o autenticador**: `manage.py reset_mfa email --reason "..."` (auditado).
- **Marcação chegou depois do fechamento**: o espelho mostra `divergent=true`; reabrir com motivo, tratar e fechar de novo.
- **Cadeia com problema** (`verify_timeclock`): não corrigir dados; preservar o banco, abrir incidente e acionar especialista.
