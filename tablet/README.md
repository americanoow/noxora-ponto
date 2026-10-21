# Tablet (Flutter, Android)

O SDK do Flutter não estava instalado quando esta etapa foi escrita: **a compilação e os testes não foram executados** (validação pendente).

Primeira execução (com Flutter instalado):

```powershell
cd tablet
flutter create . --platforms=android --org br.com.noxora --project-name noxora_ponto_tablet
flutter pub get
flutter analyze
flutter test
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # emulador
flutter run --dart-define=API_BASE_URL=http://<IP-da-máquina>:8000   # dispositivo físico
```

`flutter create .` gera a pasta `android/` sem sobrescrever `lib/` e `pubspec.yaml`. Em Android com HTTP puro (somente desenvolvimento) pode ser necessário `android:usesCleartextTraffic="true"` no manifesto de debug; em produção use HTTPS.
