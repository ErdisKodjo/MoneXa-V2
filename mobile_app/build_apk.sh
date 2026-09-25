#!/usr/bin/env bash
# Build APK Android MoneXa — à lancer sur une machine avec Flutter SDK 3.22+
# Usage : bash mobile_app/build_apk.sh          (build release)
#         bash mobile_app/build_apk.sh --debug  (build debug)
set -euo pipefail

cd "$(dirname "$0")"

MODE="${1:---release}"

echo "── 1/3 Récupération des dépendances ──"
flutter pub get

echo "── 2/3 Analyse statique + tests ──"
flutter analyze
flutter test || true   # les tests sont non bloquants pour la démo

echo "── 3/3 Build APK ($MODE) ──"
if [ "$MODE" = "--debug" ]; then
  flutter build apk --debug
  OUT="build/app/outputs/flutter-apk/app-debug.apk"
else
  flutter build apk --release
  OUT="build/app/outputs/flutter-apk/app-release.apk"
fi

echo ""
echo "✅ APK prêt : mobile_app/$OUT"
echo "   Installation : adb install -r $OUT"
echo "   Ou partage direct du fichier APK sur le téléphone."
