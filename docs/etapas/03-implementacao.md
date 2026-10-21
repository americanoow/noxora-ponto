# Etapa 3 — Cadastros da operação: implementação

## Entregue
- App `operations`: Unit, Sector, Employee, Assignment (lotação com vigência), WorkSchedule/ScheduleDay, EmployeeSchedule (jornada com vigência).
- API em `/api/companies/{id}/`: `units/`, `sectors/`, `employees/` (busca `q`, filtros `unit`, `sector`, `active`, paginação 25/100), `employees/{id}/assignments/`, `employees/{id}/schedules/`, `schedules/`, `employees/import/`.
- Escopo do gestor (unidades/setores) editável no vínculo (`scope_unit_ids`, `scope_sector_ids`); gestor lê, administrador escreve; funcionário não acessa.
- Importação CSV com prévia, erros por linha e gravação tudo-ou-nada.
- `manage.py seed_demo` (só com DEBUG): empresa fictícia com 30 funcionários.
- Frontend: abas Funcionários (busca, filtros, paginação, lotação), Unidades e setores, Jornadas, Importação.
- Decisões D16–D22 em decisoes-tecnicas.md.

## Verificações executadas
- Backend: 121 testes (SQLite), ruff e `makemigrations --check` limpos. Cobrem isolamento por empresa em todos os endpoints novos, escopo do gestor, histórico de lotação/jornada, importação inválida, CPF, auditoria sem dados pessoais.
- Frontend: 30 testes, lint, typecheck, prettier, build.

## Pendências
- PostgreSQL real: concorrência de lotações, restrições (collation/unicidade por `Lower`) e exclusão de intervalos sobrepostos.
- Flutter/Docker ausentes (herdado). Atualização em massa e edição de jornada atribuída não suportadas por decisão.
