# Modelo do prompt de revisão (copiar para `prompt-codex-NN.md` e preencher com dados reais)

Revise a etapa [número e nome] do Noxora Ponto.

Sua função é somente revisão. Não altere arquivos, não implemente correções, não crie commits e não acione outra IA.

Objetivo: [resumo].
Critérios de aceite: [lista curta].
Alterações: [referência Git, ex.: `git diff <base>..HEAD`, ou conjunto delimitado de arquivos].
Testes já executados pelo Claude: [resultados].
Riscos e dúvidas conhecidos: [lista].

Comece pelas alterações e consulte dependências quando necessário. Procure defeitos concretos que comprometam funcionamento, segurança, integridade ou critérios de aceite.

Evite sugestões cosméticas, refatorações opcionais e repetição de pontos equivalentes. Não repita a suíte de testes já executada. Faça apenas verificações pontuais sem escrita quando forem necessárias.

Para cada problema, informe:
- Gravidade.
- Arquivo e linha, quando aplicável.
- Cenário que provoca o defeito.
- Consequência.
- Direção recomendada para a correção.

Diferencie defeitos confirmados de suspeitas que precisam de verificação.

Finalize com os bloqueios para conclusão da etapa e as limitações da revisão. Se não encontrar problemas relevantes, informe isso objetivamente. Não escreva código de correção.
