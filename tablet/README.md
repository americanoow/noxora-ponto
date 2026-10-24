# Tablet (Flutter, Android)

O SDK do Flutter não estava instalado quando esta etapa foi escrita: **a compilação e os testes não foram executados** (validação pendente).

Primeira execução (com Flutter instalado):

```powershell
cd tablet
flutter create . --platforms=android --org br.com.noxora --project-name noxora_ponto_tablet
# Remova apenas o teste de contador gerado pelo Flutter (não os testes do Noxora):
Remove-Item test/widget_test.dart -ErrorAction SilentlyContinue
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # emulador
flutter run --dart-define=API_BASE_URL=http://<IP-da-máquina>:8000   # dispositivo físico
```

`flutter create .` completa a pasta `android/` sem a opção `--overwrite`; preserve
`lib/`, `pubspec.yaml`, os testes do Noxora e o manifesto de debug versionado.
O teste padrão `test/widget_test.dart` referencia o app de contador do SDK e não se
aplica a este projeto. A CI também remove apenas esse arquivo gerado.

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
- Testes: `test/offline_queue_test.dart` e `test/offline_sync_test.dart` (**escritos, não executados**: Flutter ausente nesta máquina).
