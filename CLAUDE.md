# Noxora Ponto — instruções para o Claude Code

SaaS brasileiro de controle de jornada (REP-P, Portaria MTP 671/2021, CLT, LGPD) e gestão operacional de funcionários. Multiempresa, com tablets compartilhados e reconhecimento facial 1:1. Visão completa: [docs/plano.md](docs/plano.md).

## Papéis (vigente desde 2026-10-27, autorização do usuário)
- O **Claude Code** conduz o desenvolvimento de ponta a ponta: implementa, revisa as próprias alterações, corrige, testa, documenta e comita.
- **Não há** revisão obrigatória do Codex nem aprovação do usuário entre etapas. O Codex pode ser usado como revisor opcional (ver [AGENTS.md](AGENTS.md)), nunca como requisito para avançar.
- O Claude continua enquanto houver trabalho executável e só traz perguntas quando uma decisão do usuário for realmente necessária (custo, contratação, produção, dados reais, decisões comerciais/jurídicas).

## Memória compartilhada (ler antes de agir)
- [docs/controle/estado.json](docs/controle/estado.json): fonte de verdade do estado. Respeite qualquer pausa por limite de uso.
- [docs/progresso.md](docs/progresso.md), [docs/plano.md](docs/plano.md), [docs/arquitetura.md](docs/arquitetura.md), [docs/decisoes-tecnicas.md](docs/decisoes-tecnicas.md), [docs/requisitos-rep-p.md](docs/requisitos-rep-p.md), [docs/pendencias-externas.md](docs/pendencias-externas.md)
- `docs/etapas/NN-*.md` (histórico das etapas)

## Princípios obrigatórios
1. Isolar dados de cada empresa (nunca confiar em id de empresa vindo do cliente).
2. Marcações originais são imutáveis; ajustes ficam em registros separados, com justificativa e auditoria.
3. Disponibilidade operacional é separada do ponto legal.
4. Biometria é dado sensível: protegida, fora de logs, com retenção limitada.
5. Idempotência: sem perda nem duplicação de marcações.
6. Distinguir informação confirmada, pendente e desatualizada.
7. Não afirmar conformidade legal só porque o código existe. Registrar o que precisa de validação especializada. Não inventar regras, formatos ou certificações. Hipóteses ficam identificadas como hipóteses.
8. Integração simulada pode apoiar testes, mas nunca é apresentada como integração real.

## Ciclo de trabalho
1. Implementar em entregas coerentes, com testes.
2. Executar as verificações (backend em PostgreSQL, frontend, Flutter quando disponível).
3. Revisar o próprio diff com olhar adversarial (isolamento, imutabilidade, dados sensíveis, concorrência) e corrigir antes de seguir.
4. Comitar na branch de trabalho e enviar quando a integração permitir.
5. Registrar decisões importantes em `docs/decisoes-tecnicas.md` e o estado em `docs/progresso.md`/`estado.json`. Evitar relatórios repetitivos.

## Autorizações
- Pode instalar dependências de desenvolvimento e serviços locais no ambiente autorizado.
- **Exige autorização do usuário:** contratar serviços, gerar despesas, alterar produção, publicar dados reais.
- Nunca colocar segredos no repositório.

## Pausa por limite de uso
Se houver esgotamento confirmado de uso/créditos/contexto: parar, preservar o trabalho (commit), marcar `retomada_manual_obrigatoria` no estado, informar o motivo e aguardar o usuário. Não trocar automaticamente de conta, modelo ou cobrança.

## Idioma
Interface e documentação em português do Brasil.
