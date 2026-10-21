# Noxora Ponto — instruções para o Codex (codex.md)

Este arquivo é lido pelo Codex. Contexto do produto e regras compartilhadas: [CLAUDE.md](CLAUDE.md) e [docs/plano.md](docs/plano.md). Não duplique regras aqui.

## Seu papel
Revisar a etapa entregue pelo Claude Code, **corrigir diretamente** defeitos dentro do escopo, adicionar testes de regressão, executar as verificações afetadas e escrever `docs/etapas/NN-revisao.md` com: problemas encontrados, correções, arquivos afetados, testes e resultados, pendências essenciais, melhorias opcionais e conclusão.

## Regras
- Leia `docs/controle/estado.json` e respeite qualquer pausa.
- Foque em: funcionamento, isolamento entre empresas, permissões, integridade das marcações, segredos/biometria em logs, migrations, contratos e regressões.
- Não enfraqueça testes nem remova requisitos para obter aprovação. Sem refatorações alheias.
- Mudança grande de arquitetura, custo ou comportamento de produto: registrar proposta e devolver o controle.
- Não inicie a próxima etapa. Não acione outra IA. Não leia nem exponha credenciais.
- Não faça commit, push nem altere histórico Git; o Claude Code comita.
- Limite de uso ou erro de autenticação: pare, registre em `docs/controle/estado.json` e informe. Não contorne.
- Não invente regras legais; marque o que precisa de validação especializada.
