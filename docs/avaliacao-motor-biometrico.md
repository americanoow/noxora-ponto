# Avaliação do motor biométrico (etapa 6)

Pesquisa feita em 2026-10-22. **Não é parecer jurídico nem teste de eficácia.** Nenhum serviço pago foi contratado e nenhum algoritmo próprio foi escrito.

## O que o produto precisa
Verificação **1:1** (matrícula → rosto) em tablet Android compartilhado, com **detecção de apresentação (anti-spoofing/vivacidade)**, qualidade de captura, operação preferencialmente on-line, licença compatível com SaaS comercial, e dado biométrico tratado como sensível (LGPD).

## Opções encontradas

| Opção | O que entrega | Licença / observação | Veredito |
|---|---|---|---|
| **Google ML Kit – Face Detection** | Detecção, pontos e classificações (sorriso, olhos). **Não reconhece pessoas e não faz vivacidade** | Gratuito; ver documentação ML Kit | Útil só para qualidade/enquadramento na captura; **não resolve** identidade nem antifraude |
| **OpenCV Zoo – SFace** (reconhecimento) + **YuNet** (detecção) | Embedding facial ONNX e detector leve; permitem comparar 1:1 por distância | SFace: Apache-2.0; YuNet: MIT (conforme READMEs do OpenCV Zoo; conferir o `LICENSE` na versão usada). A **origem e a licença dos dados de treino não foram verificadas** | **Candidato técnico para piloto**, mas **sem vivacidade**; limiares de aceitação (FAR/FRR) precisam ser calibrados com dados da população real; viés demográfico não avaliado |
| **InsightFace (buffalo_l etc.)** | Reconhecimento de alta qualidade | Código MIT, **pesos para pesquisa não comercial**; uso comercial exige contatar o fornecedor | **Não usar** sem licença |
| **PAD (anti-spoofing) de código aberto** (ex.: Silent-Face-Anti-Spoofing) | Classificador de apresentação | Eficácia não certificada; requer validação própria contra ataques (foto, vídeo, máscara) | Pode ser avaliado, **não** pode ser apresentado como antifraude comprovada |
| **SDKs/serviços comerciais** (liveness certificada ISO 30107-3, serviços de nuvem de verificação) | Verificação + vivacidade com avaliação independente | **Pago** e envia dado biométrico a terceiro (transferência/operador LGPD) | **Exige decisão de custo e contratual** — não autorizado |

## Decisão e bloqueio (registrados)
1. **Motor real: BLOQUEADO para decisão do responsável pelo produto.** Escolher entre (a) piloto com SFace+YuNet no servidor **sem** afirmar antifraude, ou (b) contratar SDK/serviço com vivacidade certificada. Isso altera custo, fornecedor e tratamento de dados: fora do que este plano autoriza.
2. O produto entrega **o contrato de integração** (`BiometricEngine`), todo o **armazenamento protegido**, o **fluxo de verificação com tentativas, bloqueio e token de uso único**, a **política por empresa**, a **alternativa autorizada** e a **exclusão**. Falta apenas plugar o motor.
3. Há um **simulador** para testes: só funciona com `DJANGO_DEBUG=true`; a configuração recusa iniciar em produção com ele; toda tentativa grava `engine = simulator`. **Os testes com o simulador não comprovam eficácia biométrica nem antifraude.**
4. Modo `face` da empresa **exige vivacidade aprovada** (`liveness = passed`); um motor sem vivacidade não satisfaz esse modo.

## Offline
Nenhum dos candidatos foi validado em Android real. Reconhecimento **no aparelho** exigiria distribuir templates aos tablets (aumenta a superfície de risco) e continua sem prova de vivacidade. **Não se promete reconhecimento facial offline.** A etapa 7 deve definir a alternativa e suas condições (por exemplo, marcação por exceção autorizada com revisão posterior).

## Pendências para validação especializada
- Base legal para tratamento biométrico (LGPD art. 11), RIPD/DPIA, política de retenção e descarte (o produto implementa exclusão e `purge_biometrics`, rodado todo dia pelo worker com prazos padrão de 30 dias após a inativação e 90 dias para tentativas — **a validar**).
- Teste de eficácia (FAR/FRR, ataques de apresentação), viés demográfico e acessibilidade.
- Gestão de chaves em KMS/HSM (hoje chave de aplicação por variável de ambiente), rotação e backup sem material biométrico em claro.
- Contratos com operadores e eventual transferência internacional.

## Fontes
- OpenCV Zoo, SFace e YuNet (READMEs/licenças): https://github.com/opencv/opencv_zoo
- Google ML Kit, detecção de faces (Android): https://developers.google.com/ml-kit/vision/face-detection/android
- InsightFace (pesos de modelos): https://github.com/deepinsight/insightface

## Atualização da etapa 7 — alternativa offline definida
Nenhum motor foi validado e o reconhecimento facial **não funciona offline** neste produto. A alternativa implementada é a marcação **por matrícula**, gravada como `registration_offline`, **sinalizada para revisão** e disponível apenas se o administrador ativar `offline_policy = registration_only` (padrão: desativada). Em empresas no modo `face` isso é um rebaixamento deliberado da identificação, visível no histórico. Exceção autorizada por código também **não** funciona offline (o código é validado no servidor). Detalhes e limites: decisões D52–D61 e [requisitos-rep-p.md](requisitos-rep-p.md), seção 3.

## Atualização 2026-10-27 — motor real integrado (decisões D62–D64)
O candidato **SFace + YuNet** foi integrado como motor real no servidor, com o desafio de movimento como prova de presença **básica e não certificada**. Testado com fotos reais em ambiente de desenvolvimento; isso **não** é teste de eficácia (FAR/FRR), nem de ataques de apresentação, nem de viés demográfico. Para uso real: calibrar o limiar com voluntários, decidir se o nível básico é aceitável (política `basic_challenge`) ou contratar motor com vivacidade certificada (o contrato `BiometricEngine` aceita outro adaptador sem mudar o fluxo).
