# Progresso

Estado vivo em [controle/estado.json](controle/estado.json).

## Ambiente (2026-10-21)
Git, Python 3.15, Node 24, Codex CLI 0.163.0 disponíveis. **Ausentes:** Docker, Flutter. PostgreSQL 17.5 portátil disponível via `tools/postgres_local.ps1` (porta 5433). JAVA_HOME definido (JDK 21).

## Etapas
| Etapa | Implementado | Testado | Revisado Codex | Validado ext. | Implantado |
|-------|--------------|---------|----------------|---------------|------------|
| 1 | sim, com validações pendentes | backend SQLite e frontend; Flutter/PostgreSQL pendentes | sim, conferido pelo Claude | não | não |
| 2 | sim | backend 83 (SQLite), frontend 25 | sim, conferido pelo Claude: [relatório](etapas/02-revisao.md) | não | não |
| 3 | sim | backend 150 (SQLite), frontend 33 | sim, relatório completo; conferido pelo Claude: [relatório](etapas/03-revisao.md) | não | não |
| 4 | sim (Flutter não compilado) | backend 202 (SQLite, 1 ignorado), frontend 39 | sim, conferido pelo Claude: [relatório](etapas/04-revisao.md) | não | não |
| 5 | sim (Flutter não compilado) | backend 259 em PostgreSQL 17.5 e 255 em SQLite; frontend 44 | sim, conferido pelo Claude: [relatório](etapas/05-revisao.md) | não (ver requisitos-rep-p.md) | não |
| 6 | sim: motor real OpenCV YuNet+SFace e câmera no tablet (2026-10-27); vivacidade básica não certificada | backend 336 em PostgreSQL e 328 em SQLite; frontend 54 | revisão principal feita (3 apontamentos corrigidos pelo Claude); revisão complementar NÃO feita (apenas Claude Code, por instrução do usuário); auto-revisão registrada | não | não |
| 7 | sim | backend em PostgreSQL; Dart **executado** em 2026-10-27 (analyze limpo) | não (Codex descontinuado) | não (tablet real pendente) | não |

## Modelo
Pedidos de troca de modelo (Opus 5.5 médio para decisões difíceis) são feitos ao usuário via `/model`; nenhum até agora.

## Revisão da etapa 2 (21/10/2026)
Implementada e revisada com correções pelo Codex; conferência do Claude pendente. Backend: 82 testes SQLite; frontend: 25 testes, lint, typecheck e build. Decisão sobre enumeração temporal por e-mail síncrono e validação PostgreSQL permanecem essenciais. Ver [etapas/02-revisao.md](etapas/02-revisao.md). Etapa 3 não iniciada.

## Histórico de pausas
- 2026-10-21 (etapa 3): Codex atingiu limite de uso. Retomada manual autorizada pelo usuário às 23:25 do mesmo dia.
- 2026-10-22 (etapa 6): Codex atingiu limite de uso durante a revisão (renovação informada pela ferramenta: 4:33 AM). Projeto pausado; retomada manual obrigatória.
- 2026-10-22 11:37: retomada manual autorizada pelo usuário. Nova divisão de trabalho: Codex apenas revisa (sandbox somente leitura); Claude implementa, corrige e valida. Ver CLAUDE.md e AGENTS.md.
- 2026-10-22: pausa pedida pelo usuário após a etapa 6. Revisão complementar do Codex não realizada (modelo em capacidade máxima, não é limite de uso). Aguardando retomada manual.
- 2026-10-24: retomada autorizada pelo usuário. Instrução: usar apenas o Claude Code (sem Codex) e parar ao terminar a próxima etapa (etapa 7).
- 2026-10-24: etapa 7 concluída só com o Claude Code. Pausa solicitada pelo usuário: etapa 8 não iniciada.
- 2026-10-27: retomada autorizada pelo usuário com condução autônoma pelo Claude Code (implementação, revisão, correção e testes). Revisão do Codex e aprovação entre etapas deixam de ser exigidas. Ambiente de nuvem: Linux, Python 3.13, Node 22, PostgreSQL 16 local, Flutter 3.47 (sem Android SDK: APK não gerável aqui).

## Retomada autônoma — 2026-10-27 (Claude Code, sem Codex)
Ambiente de nuvem: PostgreSQL 16, Redis 7, Flutter 3.47.8, Docker (imagens base via mirror.gcr.io). Push ao GitHub recusado (403).

| Entrega | Implementado | Testado | Validado ext. / real |
|---|---|---|---|
| Tablet: Flutter compilado/testado, câmera e desafio facial | sim | 78 testes Dart, analyze limpo | APK e aparelho real pendentes |
| Etapa 6: motor facial real (D62–D64) | sim | regras com motor substituído + integração com fotos reais (opcional) | calibração/eficácia pendentes |
| Etapa 8: apuração com regras versionadas (D65–D68) | sim | 24 cenários de referência + API | regras: validação especializada |
| Etapa 9: ajustes, abonos, fechamento/reabertura (D69–D70) | sim | API, imutabilidade no banco | — |
| Etapa 10: disponibilidade (D71–D72) | sim | API | — |
| Etapa 11: portal, espelho PDF/CSV, exportações (D73–D75) | sim (API) | API | PDF sem assinatura ICP |
| Etapa 12: AFD e folha (D76–D77) | sim (AEJ não) | estrutura e hash do AFD | leiaute oficial a conferir |
| Etapa 13: planos/assinaturas/sandbox (D78–D81) | sim | ciclo completo e webhooks | gateway real pendente |
| Etapa 14: segurança, cache, outbox, MFA, backup, carga | sim | gatilhos de cadeia, varredura de isolamento, Redis, restore executado, carga HTTP | — |
| Etapa 15: Docker, Compose, Caddy, worker | sim | pilha de produção local + teste ponta a ponta HTTPS | sem ambiente publicado |
| Frontend completo (padrões da skill swiftui-patterns adaptados) | sim | 69 testes + verificação visual com dados reais (desktop e 390 px) | validação com usuários pendente |

Verificações finais: ver resumo no fim da sessão e [pendencias-externas.md](pendencias-externas.md).

## 2026-10-29 — Linguagem simples e motor facial em desenvolvimento
- Interface reescrita em linguagem do dia a dia (glossário em D86), com descrição de cada função no Início, mensagens de erro acionáveis e leitura mais fácil (D87). Textos gerados pelo servidor continuam técnicos (D88, pendente). Frontend: 70 testes, tipos, lint e formatação limpos.
- Motor facial OpenCV ativo em desenvolvimento (D89); funcionou no fluxo completo em celular Android (APK debug gerado neste computador). **Pendente:** recusa de outra pessoa/foto/vídeo, calibração do limiar, vivacidade certificada, LGPD, cofre de chaves, APK de produção assinado.
- `availability`: o indício de ponto passa a citar a unidade da última batida.

## 2026-10-30 — Redesenho da interface (web e tablet)
- Nova identidade (D90–D98): tokens, ponto como assinatura, barra lateral agrupada, Hoje, folha de ponto com linha do tempo e painel do dia, solicitações em lista+detalhe, fechamento guiado, portal mobile e tablet Flutter.
- Verificações: frontend 70 testes, tipos, lint e formatação limpos; tablet 78 testes e `flutter analyze` limpos. Capturas renderizadas em `docs/design/capturas/` (web). Tablet: APK de teste gerado, sem captura de tela.
- Pendências listadas em `decisoes-tecnicas.md` (som, crachá/QR, anexos, histórico por dia, fonte no Flutter, modo escuro).

## 2026-10-30 — Revisão de segurança e consistência (19 achados)
- Corrigidos os 12 achados da primeira lista e os 7 da segunda (D99–D113): turno noturno, fechamento (inativos, incompletos com exceção, corrida), fuso por vigência, pedidos no fuso da unidade, paginação/limites explícitos, vivacidade com desafio do servidor, banco de horas, permissões do gestor, origem das batidas do tablet, TXT de folha sem truncar, jornada/lotação retroativas, MFA com limite de tentativas e login recente, intervalo × duração, prorrogação noturna, limites do plano sob bloqueio.
- Backend: 501 testes passando no PostgreSQL (485 + 18 pulados no SQLite), `ruff` limpo. Frontend: 74 testes, tipos, lint, formatação e build limpos. Tablet: 84 testes, `flutter analyze` limpo.
- Pendências: ver o fim da seção Revisão de segurança e consistência em `decisoes-tecnicas.md`.

## 2026-10-30 — Menu simplificado
- Menu do gestor com seis entradas e abas dentro de cada uma; Meses fechados dentro de Minha folha; situação da equipe como módulo opcional; detalhes técnicos recolhidos (D114–D117).
- Backend: 503 testes no PostgreSQL. Frontend: 77 testes, tipos, lint e build limpos.

## 2026-10-30 — Ajustes após revisão do menu
- Abas mantêm período; planilhas distribuídas nas telas de dados; AFD e folha em Arquivos fiscais; convidar e dar acesso em um passo; local das batidas escondido; código morto removido (D118–D122).
- Backend: 504 testes no PostgreSQL. Frontend: 76 testes, tipos, lint e build limpos.

## 2026-10-31 — Revisão de segurança, LGPD e legislação trabalhista
- Corrigido: biometria não pode mais impedir o registro (alternativa pela matrícula, sem capturar o rosto); titular retira a autorização e baixa os próprios dados; prova do termo obrigatória; retenção automática da biometria; limites legais nas regras; espelho mostra ajustes; `/admin/` removido; PDFs sem marcação injetada; nomes de arquivo e matrícula seguros; cookie CSRF HttpOnly; espera por conta no login e no segundo fator; CSP na borda; tablet só HTTPS em produção; código duplicado/morto removido (D123–D134).
- Backend: 532 testes no PostgreSQL. Frontend: 73 testes, tipos, lint e build limpos. Tablet: 86 testes e `flutter analyze` limpos.
