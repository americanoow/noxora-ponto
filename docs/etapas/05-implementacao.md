# Etapa 5 — Núcleo de marcação de ponto: implementação

Requisitos oficiais (Portaria MTP 671/2021, arts. 73–91 e Anexo IX) levantados **antes** do modelo: ver [requisitos-rep-p.md](../requisitos-rep-p.md), com a separação entre confirmado e pendente de validação externa.

## Entregue
- App `timeclock`: `TimeRecord` (imutável), `NsrCounter`, hash encadeado (`hashing.py`, versão `v1-anexo-v-historico`), comando `verify_timeclock` (NSR contíguo, encadeamento e contador).
- Gatilhos no banco bloqueando UPDATE/DELETE/TRUNCATE (migration 0002; PostgreSQL e SQLite).
- API do tablet: `POST /api/device/punches/` (201 nova, 200 reenvio) e `GET /api/device/punches/{id}/receipt/` (apenas do próprio dispositivo).
- Painel somente leitura: `GET /api/companies/{id}/time-records/` (filtros `from`, `to`, `employee`, `unit`; paginação; CPF mascarado; gestor só no seu escopo) e detalhe com comprovante. Nenhum método de escrita.
- Dados do empregador (`/employer/`, validação de CNPJ/CPF, auditoria antes/depois) e endereço da unidade (campos do art. 79).
- Contrato de identificação (`PROVIDERS`) para a facial da etapa 6.
- Frontend: abas Marcações (somente leitura) e Empregador. Flutter: `punch()` com id de evento estável, relógio com segundos e `PunchPanel` (não compilado).
- Decisões D30–D40.

## Verificações executadas
- Backend: 233 testes (SQLite, 1 ignorado de concorrência PostgreSQL), ruff e `makemigrations --check` limpos. Cobrem: campos do Anexo IX, NSR por unidade, cadeia de hash e detecção de adulteração, idempotência (inclusive corrida simulada e payload divergente), rollback sem consumir NSR, marcação sem escala/CPF/unidade ativa, escopo do terminal, imutabilidade no ORM e no SQL direto, painel sem escrita, isolamento entre empresas, comprovante e empregador.
- Frontend: 44 testes, lint, typecheck, build.

## Pendências
- Todas as pendências de [requisitos-rep-p.md](../requisitos-rep-p.md) §2: layout vigente do AFD/hash, estabelecimento, ARP completa, prazo de guarda, certificados/INPI/Atestado, identificação, HLB e alta disponibilidade.
- Concorrência de NSR sob carga em PostgreSQL real (não executada); Flutter não compilado.
