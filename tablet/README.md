# Tablet (Flutter, Android)

Validado em 2026-10-27 com Flutter 3.47.8 (Linux): `flutter analyze` sem avisos e `flutter test` com todos os testes passando. O APK **não** foi gerado neste ambiente (Android SDK indisponível na rede da nuvem); a CI gera o APK debug.

```bash
cd tablet
flutter pub get
flutter analyze
flutter test
flutter build apk --debug          # exige Android SDK
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # emulador
flutter run --dart-define=API_BASE_URL=http://<IP-da-máquina>:8000   # dispositivo físico
```

A pasta `android/` está versionada (gerada por `flutter create` e ajustada: nome do app e permissão INTERNET).
O manifesto de debug permite INTERNET e HTTP local. A CI foi preparada para analisar,
testar e gerar APK debug, mas ainda não foi executada. Build release, assinatura e
configuração de rede de produção (INTERNET no manifesto principal e HTTPS) permanecem
fora desta entrega; não use o APK debug em produção.

Para tablet físico, rode o backend com `manage.py runserver 0.0.0.0:8000`, inclua o IP
da máquina em `DJANGO_ALLOWED_HOSTS` e permita a porta apenas na rede de desenvolvimento.
O emulador usa `10.0.2.2`; o backend não aceita automaticamente outros hosts.

## Operação offline (etapa 7)
- Sem conexão, e **somente se a empresa ativar** `offline_policy = registration_only` no painel, a marcação por matrícula é guardada numa fila persistente (armazenamento seguro do Android) e enviada em lote ao reconectar. Reconhecimento facial e código de exceção **não** funcionam offline.
- A confirmação offline é **provisória** (horário do aparelho, sem NSR nem comprovante). Após a sincronização cada marcação recebe NSR; recusas ficam visíveis até alguém confirmar.
- A fila é preservada se o tablet for revogado: ao reativar o mesmo cadastro (novo código), ela é enviada.
- Testes: `test/offline_queue_test.dart` e `test/offline_sync_test.dart` (executados com sucesso em 2026-10-27).

## Reconhecimento facial (2026-10-27)
- Em empresas no modo `face`, o botão **Reconhecer rosto e registrar** abre a câmera frontal e conduz o desafio: olhar para a câmera, virar levemente à esquerda e à direita (3 fotos). As imagens ficam só em memória e vão ao servidor, que faz a verificação 1:1 e devolve um token de uso único usado na marcação.
- Se a política da empresa exigir vivacidade certificada, o tablet informa que a prova de presença não atende e orienta a usar o **código de exceção** com um responsável.
- Permissão `CAMERA` declarada no manifesto principal; a câmera frontal é opcional (`required=false`).
- Testes: `test/face_capture_test.dart` (câmera simulada). Validação em aparelho real pendente.
