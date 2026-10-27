#!/bin/sh
# Papel da aplicação SEM ser dono das tabelas (não pode remover gatilhos de imutabilidade nem TRUNCATE).
# O dono (noxora_owner) só é usado pelo serviço "migrate".
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
CREATE ROLE noxora_app LOGIN PASSWORD '${APP_DB_PASSWORD:-troque}';
GRANT CONNECT ON DATABASE $POSTGRES_DB TO noxora_app;
GRANT USAGE ON SCHEMA public TO noxora_app;
ALTER DEFAULT PRIVILEGES FOR ROLE $POSTGRES_USER IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO noxora_app;
ALTER DEFAULT PRIVILEGES FOR ROLE $POSTGRES_USER IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO noxora_app;
SQL
