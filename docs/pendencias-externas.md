# Pendências que dependem do responsável pelo produto ou de terceiros

Atualizado em 2026-10-27. Cada item diz **o que falta**, **por que o Claude não pode resolver** e **o que já está pronto**.

## Decisões do responsável pelo produto
1. **Frontend (painel web)**: aguardando suas instruções para o redesenho e as telas das etapas 8–13. Todas as APIs estão prontas ([api.md](api.md)).
2. **Motor facial em produção**: (a) usar o motor OpenCV já integrado com a política `basic_challenge` (prova de presença básica, **não certificada**), ou (b) contratar SDK/serviço com vivacidade certificada (custo, contrato, operador LGPD). Até lá, a política padrão `certified` recusa o desafio básico.
3. **Gateway de pagamento** (Asaas, Stripe, Pagar.me, Iugu…): contrato e credenciais. Hoje só há sandbox local.
4. **Preços e limites dos planos**: os três planos têm valores placeholder.
5. **Sistema de folha** a integrar: escolher fornecedor; o layout dele define o arquivo (hoje há CSV/TXT genéricos com rubricas configuráveis).
6. **Hospedagem**: servidor/VM com Docker ou Supabase + outro host para a aplicação; domínio e DNS; SMTP transacional (ex.: provedor de e-mail). Nada foi contratado.
7. **Push para o GitHub**: a integração desta sessão recusou o push (403). Reconectar o GitHub em claude.ai ou instalar o Claude GitHub App no repositório.

## Validação especializada (jurídica/trabalhista/técnica)
8. Leiaute oficial do **AFD** (cabeçalho, trailer, versão, CRC-16, preenchimento) e o **AEJ** (não implementado) — portais gov.br inacessíveis na rede da nuvem; ver [requisitos-rep-p.md](requisitos-rep-p.md).
9. **Regras de apuração** (tolerância, adicionais, intervalos, noturno, DSR, banco de horas, convenções coletivas) — parâmetros com referência à CLT, tratados como hipóteses.
10. **REP-P**: registro no INPI, Atestado Técnico e Termo de Responsabilidade, certificado ICP-Brasil (PAdES no comprovante, CAdES no AFD), sincronismo com a Hora Legal Brasileira, marcação offline (condições), unidade ≡ estabelecimento.
11. **LGPD**: base legal da biometria (art. 11), RIPD, prazos de retenção (biometria, localização, marcações), contratos com operadores.
12. **Calibração do reconhecimento facial** (limiar, FAR/FRR, viés) e testes de ataque de apresentação com a população real.

## Testes físicos e acessos que não puderam ser feitos aqui
13. **APK**: Android SDK indisponível na rede da nuvem; a CI gera o APK debug. Build de release/assinatura pendente.
14. **Tablet real**: câmera, iluminação, tempo de resposta, armazenamento seguro, reinício com fila offline, rotação de credencial.
15. **SMTP real**: envio pela outbox testado com backend em memória e falhas simuladas; sem servidor real.
16. **Implantação real**: pilha testada localmente em modo produção (TLS local, papel de banco restrito, teste ponta a ponta); não há ambiente publicado.
