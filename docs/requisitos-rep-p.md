# Requisitos do REP-P (Portaria MTP nº 671/2021) aplicáveis ao núcleo de marcação

Fonte lida: texto consolidado da Portaria MTP nº 671/2021 publicado pelo Ministério do Trabalho e Emprego em gov.br (PDF "compilada", 210 páginas, lido em 2026-10-21). Foram lidos os arts. 73 a 91 e o Anexo IX. **Isto é leitura técnica do texto, não parecer jurídico.** Itens marcados como pendentes precisam de validação especializada antes da comercialização.

## 1. Requisitos confirmados no texto lido

| Ref. | Requisito | Como o produto trata |
|---|---|---|
| Art. 74, I–IV | O sistema não pode: restringir horário de marcação; marcar automaticamente; exigir autorização prévia para sobrejornada; ter dispositivo que permita alterar os dados registrados pelo empregado | Nenhuma regra de escala/disponibilidade bloqueia marcação; não há API de escrita sobre marcações; imutabilidade garantida também por gatilhos no banco |
| Art. 78 | REP-P é software em servidor dedicado ou nuvem, exclusivo para registro de jornada | Backend multiempresa em nuvem (a avaliar "exclusivo" na validação) |
| Art. 79, I–IX | Comprovante: título "Comprovante de Registro de Ponto do Trabalhador"; NSR; empregador (nome, CNPJ/CPF, CEI/CAEPF/CNO se houver); local da prestação do serviço; trabalhador (nome e CPF); data e horário; **número de registro no INPI (REP-P)**; **hash SHA-256 da marcação**; assinatura eletrônica (se impresso) | Comprovante estruturado (JSON) com todos os campos; campos ausentes são listados como pendentes |
| Art. 80 | Comprovante impresso ou arquivo PDF assinado (arts. 87–88); acesso após cada marcação sem pedido prévio; extração pelo empregado das últimas 48 h | Acesso imediato na resposta da marcação; PDF assinado e portal do funcionário pendentes (etapas 11–12) |
| Art. 81 | O sistema deve gerar o Arquivo Fonte de Dados (AFD); em REP-P deve ser prontamente gerado ao Auditor-Fiscal | Etapa 12 |
| Art. 88, §§1–2 | Assinaturas do REP-P com certificado ICP-Brasil: PAdES no comprovante PDF; CAdES destacado (.p7s) no AFD/AEJ | **Externo** (certificado) |
| Art. 89 | Fabricante/desenvolvedor fornece Atestado Técnico e Termo de Responsabilidade (PDF/PAdES); empregador só pode usar o sistema se o possuir | **Externo** |
| Art. 91 | REP-P deve ter certificado de registro de programa de computador no INPI e atender ao Anexo IX | **Externo** |
| Anexo IX, 1 | Identificar organização e trabalhador | Empresa/unidade/CPF do trabalhador no registro |
| Anexo IX, 2 | Relógio sincronizado com a Hora Legal Brasileira (Observatório Nacional), variação máxima de 30 s | Horário oficial da marcação é o do servidor; divergência do relógio do tablet é registrada. Sincronismo NTP do servidor: etapa 14/15 |
| Anexo IX, 3 | Coletor exibe relógio não analógico com horas, minutos e segundos no momento da marcação | Tablet (etapa 6/7) |
| Anexo IX, 4–5 | Marcações vêm de coletor on-line; excepcionalmente off-line, enviadas no primeiro momento on-line | Campo `offline` e fila (etapa 7) |
| Anexo IX, 6 | Armazenamento de Registro de Ponto (ARP) com redundância e alta disponibilidade; NSR com sequência própria **por estabelecimento**, de 1 em 1, iniciando em 1 | NSR por unidade, alocado sob bloqueio. Redundância: etapa 14/15 |
| Anexo IX, 6.5 / 10 | Campos da marcação: NSR, CPF, data/hora da marcação com fuso, data/hora da gravação com fuso, identificação do coletor, hash SHA-256 | Todos armazenados; ver modelo `TimeRecord` |
| Anexo IX, 7 | Dados da ARP não podem ser apagados ou alterados, direta ou indiretamente, pelo prazo mínimo legal | Gatilhos no banco bloqueiam UPDATE/DELETE/TRUNCATE; ORM bloqueia alteração e exclusão |
| Anexo IX, 8 | Marcação: identificação inequívoca do trabalhador, data/hora confiável, gravação na ARP, comprovante | Fluxo de `record_punch` |
| Anexo IX, 11–12 | Gerar AFD a partir da ARP, inclusive por intervalo | Etapa 12 |
| Anexo IX, 13 | Alta disponibilidade de todas as etapas do registro | Infraestrutura (etapas 14–15) |
| Anexo V (versão histórica no texto) | Registro tipo "7" (marcação REP-P): NSR(9) · tipo · data/hora da marcação (24, `AAAA-MM-ddThh:mm:00±ZZZZ`) · CPF(12) · data/hora da gravação (24) · coletor(2) · on/off-line(1) · hash(64); hash SHA-256 calculado sobre NSR, tipo, DH da marcação, CPF, DH da gravação, coletor, on/off-line e **hash do registro anterior** | Implementado como `hash_version = "v1-anexo-v-historico"`, ver pendência 1 |

## 2. Pendências que exigem validação externa (não afirmar conformidade)

1. **Especificação do AFD/AEJ.** O AFD disponível no portal foi consultado na revisão (abaixo); a pendência agora é validar os bytes exatos usados no hash, o preenchimento dos campos e a cadeia com a ARP completa. AEJ não consultado nesta revisão. Manter `hash_version` e não reescrever registros antigos.
2. **"Estabelecimento".** O NSR é por estabelecimento. O produto usa a **unidade** como estabelecimento. Confirmar se unidade ≡ estabelecimento (CNPJ/endereço) e como tratar várias unidades sob um mesmo estabelecimento.
3. **Demais registros da ARP** (Anexo IX, 6.1–6.4: empregador, ajuste de relógio, empregado, eventos sensíveis) e a numeração NSR compartilhada com as marcações. Hoje só marcações consomem NSR; alterações cadastrais ficam na auditoria (append-only). Definir com especialista como entram na sequência.
4. **Prazo mínimo legal de guarda.** O texto lido remete a "prazo mínimo legal" sem fixá-lo. Não foi definido política de retenção/expurgo; **nenhuma exclusão de marcação existe**.
5. **Identificador do coletor** (códigos "01" aplicativo mobile … "04" dispositivo eletrônico, no layout histórico). O tablet usa `01` provisoriamente.
6. **Suficiência da identificação** por matrícula e por biometria facial frente a "identificação inequívoca" (Anexo IX, 8.1) e à LGPD. Desde 2026-10-31 (D123), no modo facial quem não tem biometria ativa (não autorizou, retirou ou não cadastrou) e todos, com o motor fora do ar, registram pela matrícula: o sistema não restringe a marcação (art. 74) nem condiciona o registro ao consentimento.
7. **Obrigatoriedade do CPF** do trabalhador no registro: marcação **nunca é recusada** por CPF ausente (não se perde marcação); o CPF fica como snapshot, possivelmente vazio, e o AFD deverá sinalizar a pendência.
8. **Certificados e registros externos**: certificado ICP-Brasil (PAdES/CAdES), registro no INPI, Atestado Técnico e Termo de Responsabilidade.
9. **Marcação em unidade diferente da lotação** (empregado de passagem): hoje o terminal só encontra empregados lotados na unidade do aparelho (decisão D27). Avaliar se isso pode impedir marcação legítima.
10. **Sincronismo com a Hora Legal Brasileira** (±30 s) e **alta disponibilidade** são requisitos de operação, ainda não demonstrados.

## 3. Conferência técnica em 22/10/2026

Fontes oficiais: [página REP do MTE](https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/fiscalizacao-do-trabalho/rep) e [leiaute AFD disponível no portal](https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/fiscalizacao-do-trabalho/leiaute-do-arquivo-fonte-de-dados-afd.pdf), seis páginas, versão 004 indicada no cabeçalho.

O DH tem 24 caracteres, segundos fixos 00 e offset com sinal seguido de quatro dígitos; coincide com `format_dh`. O tipo 7 mantém NSR(9), CPF(12), dois DH(24), coletor(2), indicador online/offline(1) e hash(64). O cálculo inclui os sete primeiros campos e o hash anterior, se existir. O código 01 identifica aplicativo mobile.

**Divergência a esclarecer:** a regra geral 7 determina preenchimento pela esquerda e espaços nas posições restantes; o código preenche NSR/CPF com zeros à esquerda. Não foi localizado vetor oficial que resolva essa interpretação, caixa hexadecimal ou interação com outros tipos de registro. Não alterar o algoritmo histórico silenciosamente: validar um vetor com especialista e, se necessário, adotar nova versão para registros futuros. O nome `v1-anexo-v-historico` foi preservado.

**Limites técnicos encontrados:** UPDATE/DELETE e TRUNCATE PostgreSQL são protegidos; SQLite recebeu proteção contra substituição via REPLACE. INSERT de novas linhas com NSR/hash arbitrários continua permitido por SQL e bulk_create, e o contador pode ser adulterado. Isso impede afirmar integridade contra escrita direta. Proposta e evidências em [05-revisao.md](etapas/05-revisao.md).

Comprovantes JSON novos preservam snapshot; legados sem snapshot sinalizam ausência, sem reconstruir o passado com cadastro atual. CPF do empregador fica mascarado no terminal/gestor e omitido da auditoria; administrador ainda o acessa para cadastro. Isso não substitui os campos e assinatura do futuro comprovante oficial.

## 3. Marcação offline (etapa 7) — pendências para validação especializada

O Anexo IX (itens 4 e 5) admite marcação **off-line "excepcionalmente"**, enviada "no primeiro momento em que o coletor entrar em modo on-line, garantidas as normas de segurança da informação". O produto implementa isso com limites explícitos (decisões D52–D61). Pontos que **não** estão resolvidos:

11. **Condições da excepcionalidade**: o texto não define quando o off-line é admissível nem por quanto tempo. O produto limita por política da empresa (padrão desligada) e por idade do evento (35 dias).
12. **Identificação offline**: só por matrícula (o reconhecimento facial não funciona offline). Avaliar se isso é "identificação inequívoca" (Anexo IX, 8.1) e a base legal; o registro fica marcado `registration_offline` e sinalizado.
13. **Comprovante**: o art. 80 exige acesso ao comprovante após cada marcação. Offline o tablet entrega confirmação **provisória** sem NSR nem hash; o comprovante só existe depois da sincronização.
14. **Hora**: a Hora Legal Brasileira com variação máxima de 30 s não é garantida offline. O servidor **estima** o horário corrigindo o relógio do tablet pelo último desvio medido e sinaliza dúvidas; `recorded_at` guarda o recebimento. Validar se essa estimativa é aceitável e como tratar divergências acima de 30 s.
15. **NSR**: segue a ordem de **recebimento**, não a do evento (decisão D55). Validar com o especialista se isso atende ao requisito de sequência.
16. **Segurança da informação do reenvio**: a fila no aparelho tem proteção em repouso (Keystore), mas não prova integridade contra aparelho com root; compensações no servidor (idempotência, sinalizações, limite de idade, auditoria do lote). Avaliar a suficiência.

## 4. Arquivos técnicos (etapa 12, 2026-10-27)

- **AFD** gerado por estabelecimento (`GET /api/companies/{id}/fiscal/afd/?unit=&from=&to=`), somente administrador, com registro de cada geração (hash, tamanho, versão do gerador). Tipo 7 com os campos conferidos na etapa 5; o hash de cada linha é recalculável a partir dos campos do próprio arquivo e do hash anterior (teste automatizado).
- **Cabeçalho (tipo 1, 302 posições) e trailer (tipo 9, 64)** reconstruídos a partir do Anexo V; coerentes com indícios externos (INPI em 190–206; quantidade de tipo 7 em 055–063), porém **não conferidos** com o PDF oficial nesta sessão (gov.br/planalto inacessíveis na rede da nuvem). Pendentes: valor do campo "versão do leiaute" (`AFD_LAYOUT_VERSION`, hoje 003), variante do CRC-16 (implementada CRC-16/ARC como hipótese), preenchimento e codificação (ISO-8859-1).
- **Assinatura CAdES (.p7s)** com certificado ICP-Brasil: externa, não implementada.
- **AEJ (Arquivo Eletrônico de Jornada)**: **não implementado**. O leiaute não pôde ser consultado e não será inventado. Os dados necessários (marcações, jornadas contratuais, vínculos) existem no sistema.
- **Folha**: exportação genérica (CSV ou TXT de largura fixa) a partir do **instantâneo do fechamento**, com códigos de rubrica configuráveis por empresa. Integração com um sistema de folha específico depende da escolha do fornecedor e da especificação oficial dele.
