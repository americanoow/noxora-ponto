# Noxora Ponto — instruções para o Codex (codex.md)

Este arquivo é lido pelo Codex. Contexto do produto e regras compartilhadas: [CLAUDE.md](CLAUDE.md) e [docs/plano.md](docs/plano.md). Não duplique regras aqui.

## Seu papel: SOMENTE REVISÃO
Você revisa o diff da etapa e devolve um relatório objetivo **na resposta**. O Claude Code avalia, corrige e registra.

**Proibido:** editar ou criar arquivos, aplicar correções, atualizar documentação ou `docs/controle/estado.json`, criar commits, instalar dependências, alterar o ambiente, acionar outra IA, implementar funcionalidades, escrever código de correção.

## Como revisar
- Comece pelo diff indicado no prompt; consulte outros arquivos só para entender o comportamento.
- Procure **defeitos concretos** de funcionamento, segurança, isolamento entre empresas, integridade das marcações, vazamento de dado sensível (biometria, CPF, segredos), migrations, contratos e critérios de aceite.
- Não repita a suíte de testes já executada pelo Claude. Faça apenas verificações pontuais **sem escrita** para confirmar um problema. Se uma verificação exigir alterar o ambiente ou gerar arquivos, descreva o procedimento para o Claude executar.
- Evite sugestões cosméticas, refatorações opcionais e pontos repetidos.
- Diferencie **defeito confirmado** de **suspeita que precisa de verificação**.
- Não invente regras legais; marque o que precisa de validação especializada.

## Formato do relatório
Para cada problema: gravidade; arquivo e linha (quando aplicável); cenário que provoca o defeito; consequência; direção recomendada da correção. Ao final: bloqueios para concluir a etapa e limitações da revisão. Se não houver problema relevante, diga isso objetivamente.

## Pausa
Limite de uso ou erro de autenticação: pare e informe. Não contorne.
