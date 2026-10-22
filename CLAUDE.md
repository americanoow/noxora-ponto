# Noxora Ponto — instruções para o Claude Code

SaaS brasileiro de controle de jornada (REP-P, Portaria MTP 671/2021, CLT, LGPD) e gestão operacional de funcionários. Multiempresa, com tablets compartilhados e reconhecimento facial 1:1. Visão completa: [docs/plano.md](docs/plano.md).

## Papéis (divisão vigente desde 2026-10-22)
- **Claude Code** implementa, testa, prepara a entrega, **avalia os apontamentos do Codex, corrige os problemas confirmados**, adiciona testes de regressão, executa as verificações afetadas, atualiza documentação e estado, e encerra a etapa.
- **Codex** faz **somente revisão**: lê o diff, aponta defeitos concretos e devolve um relatório objetivo. **Não edita arquivos, não corrige, não atualiza documentação, não comita.** Veja [AGENTS.md](AGENTS.md).
- O Codex roda em sandbox somente leitura (`tools/codex_handoff.ps1`). O relatório vem na resposta e é salvo pelo script em `docs/etapas/NN-revisao.md`.

## Memória compartilhada (ler antes de agir)
- [docs/controle/estado.json](docs/controle/estado.json): fonte de verdade do estado. Respeite qualquer pausa.
- [docs/progresso.md](docs/progresso.md), [docs/plano.md](docs/plano.md), [docs/arquitetura.md](docs/arquitetura.md), [docs/decisoes-tecnicas.md](docs/decisoes-tecnicas.md), [docs/requisitos-rep-p.md](docs/requisitos-rep-p.md)
- `docs/etapas/NN-implementacao.md` e `NN-revisao.md`

## Princípios obrigatórios
1. Isolar dados de cada empresa (nunca confiar em id de empresa vindo do cliente).
2. Marcações originais são imutáveis; ajustes ficam em registros separados, com justificativa e auditoria.
3. Disponibilidade operacional é separada do ponto legal.
4. Biometria é dado sensível: protegida, fora de logs, com retenção limitada.
5. Idempotência: sem perda nem duplicação de marcações.
6. Distinguir informação confirmada, pendente e desatualizada.
7. Não afirmar conformidade legal só porque o código existe. Registrar o que precisa de validação especializada. Não inventar regras, formatos ou certificações.

## Ciclo de cada etapa
1. Claude implementa e executa as verificações iniciais.
2. Claude comita o checkpoint e escreve `docs/etapas/NN-implementacao.md` e o prompt `docs/controle/prompt-codex-NN.md` (modelo: [docs/controle/modelo-prompt-revisao.md](docs/controle/modelo-prompt-revisao.md)).
3. Claude chama `tools/codex_handoff.ps1 -Etapa N -Nome "..."` (uma revisão principal por etapa).
4. Claude analisa **cada** apontamento: confirma, refuta com evidência ou marca como suspeita a verificar. Nenhum é ignorado em silêncio.
5. Claude corrige os problemas confirmados, adiciona testes de regressão e roda as verificações afetadas.
6. Claude registra o resultado em `docs/etapas/NN-revisao.md` (seções abaixo) e encerra a etapa se os critérios forem atendidos.

### Registro da revisão (`NN-revisao.md`)
Separar claramente: apontamento original do Codex (relatório bruto, não editado), correção feita pelo Claude, testes executados e resultados, pendências e necessidade (ou não) de revisão complementar. **Não declarar que o Codex aprovou uma correção que ele não revisou.** Nesse caso registrar: “Correção implementada e validada pelo Claude após apontamento do Codex”.

### Segunda revisão (só quando necessária)
Pedir revisão complementar apenas se a correção envolver segurança, isolamento entre empresas, perda/duplicação de dados, cálculo de jornada ou integridade das marcações, mudança relevante de arquitetura/contrato, dúvida técnica que os testes não resolveram, ou se uma correção causou regressão relevante. Enviar somente as correções e o contexto necessário.

## Economia do Codex
Uma revisão principal por etapa; prompt curto (objetivo, critérios, referência do diff, testes já executados, riscos); sem o plano das 15 etapas; o Codex começa pelo diff; sem sugestões cosméticas; rotina de testes é do Claude; sem trocar modelo nem aumentar esforço automaticamente.

## Commits
Commits locais pequenos, um por etapa de segurança/entrega. Sem push, sem publicar, sem alterar histórico compartilhado. Apenas o Claude comita.

## Pausa por limite de uso
Se Claude ou Codex atingir limite confirmado de uso/créditos/contexto: parar, preservar o trabalho, marcar `retomada_manual_obrigatoria` no estado e aguardar o usuário. Não trocar de conta, modelo ou provedor, nem comprar créditos. A nova divisão **não** autoriza continuar com uma ferramenta bloqueada.

## Modelo
Decisões difíceis de arquitetura ou problemas persistentes: sugerir ao usuário trocar para Opus 5.5 (médio) e voltar ao Sonnet (médio) ao fim da etapa. O modelo é trocado pelo usuário (`/model`); registrar o pedido em `docs/progresso.md`.

## Idioma
Interface e documentação em português do Brasil.
