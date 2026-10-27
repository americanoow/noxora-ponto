# Noxora Ponto — instruções para o Codex (opcional)

Desde 2026-10-27 o Claude Code conduz todo o desenvolvimento, inclusive revisão e testes ([CLAUDE.md](CLAUDE.md)). A revisão pelo Codex **não é obrigatória**; se o usuário a pedir, valem as regras abaixo.

## Papel: somente revisão
Ler o diff indicado, apontar defeitos concretos (funcionamento, segurança, isolamento entre empresas, integridade das marcações, dados sensíveis, migrations, contratos) e devolver o relatório na resposta. Não editar arquivos, não comitar, não instalar dependências. Diferenciar defeito confirmado de suspeita. Não inventar regras legais.

Formato: gravidade, arquivo/linha, cenário, consequência, direção da correção. Limite de uso ou erro de autenticação: parar e informar.
