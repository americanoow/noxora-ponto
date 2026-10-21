# Noxora Ponto — instruções para o Claude Code

SaaS brasileiro de controle de jornada (REP-P, Portaria MTP 671/2021, CLT, LGPD) e gestão operacional de funcionários. Multiempresa, com tablets compartilhados e reconhecimento facial 1:1. Visão completa: [docs/plano.md](docs/plano.md).

## Papéis
- **Claude Code** implementa, testa, prepara a passagem e confere as correções do Codex.
- **Codex** revisa, corrige diretamente dentro do escopo e executa verificações. Veja [AGENTS.md](AGENTS.md).
- Apenas uma IA edita o projeto por vez. Durante a execução do Codex, não edite arquivos.

## Memória compartilhada (ler antes de agir)
- [docs/controle/estado.json](docs/controle/estado.json): fonte de verdade do estado. Respeite qualquer pausa.
- [docs/progresso.md](docs/progresso.md), [docs/plano.md](docs/plano.md), [docs/arquitetura.md](docs/arquitetura.md), [docs/decisoes-tecnicas.md](docs/decisoes-tecnicas.md)
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
Ler estado, implementar, testar, checkpoint, entregar ao Codex (`tools/codex_handoff.ps1`), ler o relatório, conferir correções, atualizar docs e estado, avançar se os critérios forem atendidos.

## Commits
Commits locais pequenos, um por etapa de segurança/entrega. Sem push, sem publicar, sem alterar histórico compartilhado.

## Pausa por limite de uso
Se Claude ou Codex atingir limite confirmado de uso/créditos/contexto: parar, preservar o trabalho, marcar `retomada_manual_obrigatoria` no estado e aguardar o usuário. Não trocar de conta, modelo ou provedor, nem comprar créditos.

## Modelo
Decisões difíceis de arquitetura ou problemas persistentes: sugerir ao usuário trocar para Opus 5.5 (médio) e voltar ao Sonnet (médio) ao fim da etapa. O modelo é trocado pelo usuário (`/model`); registrar o pedido em `docs/progresso.md`.

## Idioma
Interface e documentação em português do Brasil.
