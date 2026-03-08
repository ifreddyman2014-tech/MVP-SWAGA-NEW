#!/usr/bin/env bash
# ============================================================
# SWAGA VPN Android — one-shot build script
# Требования: Java 17+, Android SDK (ANDROID_HOME / ANDROID_SDK_ROOT)
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== SWAGA VPN Android Build ==="

# ── 1. Проверка Java ────────────────────────────────────────
if ! command -v java &>/dev/null; then
  echo "ERROR: Java не найден. Установи JDK 17:"
  echo "  Ubuntu/Debian: sudo apt install openjdk-17-jdk"
  echo "  macOS:         brew install openjdk@17"
  exit 1
fi
JAVA_VER=$(java -version 2>&1 | head -1)
echo "Java: $JAVA_VER"

# ── 2. Проверка Android SDK ─────────────────────────────────
if [ -z "$ANDROID_HOME" ] && [ -z "$ANDROID_SDK_ROOT" ]; then
  # Попробуем стандартные пути
  if   [ -d "$HOME/Library/Android/sdk" ]; then
    export ANDROID_HOME="$HOME/Library/Android/sdk"          # macOS
  elif [ -d "$HOME/Android/Sdk" ]; then
    export ANDROID_HOME="$HOME/Android/Sdk"                   # Linux
  elif [ -d "/opt/android-sdk" ]; then
    export ANDROID_HOME="/opt/android-sdk"
  else
    echo ""
    echo "ERROR: Android SDK не найден!"
    echo ""
    echo "Установи Android Studio или командную строку:"
    echo "  https://developer.android.com/studio#command-tools"
    echo ""
    echo "После установки укажи переменную:"
    echo "  export ANDROID_HOME=/path/to/android-sdk"
    echo "  ./build.sh"
    exit 1
  fi
fi
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
echo "Android SDK: $ANDROID_HOME"

# ── 3. Установка нужных SDK компонентов ─────────────────────
SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
if [ ! -f "$SDKMANAGER" ]; then
  SDKMANAGER="$ANDROID_HOME/tools/bin/sdkmanager"
fi

if [ -f "$SDKMANAGER" ]; then
  echo "Проверяю SDK компоненты..."
  yes | "$SDKMANAGER" "platform-tools" "build-tools;35.0.0" "platforms;android-35" 2>/dev/null || true
else
  echo "WARN: sdkmanager не найден, предполагаем что SDK уже установлен"
fi

# ── 4. Gradle wrapper ───────────────────────────────────────
if [ ! -f "gradlew" ]; then
  echo "Генерирую Gradle wrapper..."
  if command -v gradle &>/dev/null; then
    gradle wrapper --gradle-version 8.7 --distribution-type bin
  else
    echo "ERROR: gradle не найден. Установи: https://gradle.org/install/"
    exit 1
  fi
fi
chmod +x gradlew

# ── 5. libxray.aar (скачиваем если нет) ─────────────────────
LIBS_DIR="app/libs"
mkdir -p "$LIBS_DIR"

if [ ! -f "$LIBS_DIR/libxray.aar" ]; then
  echo "Скачиваю libxray.aar..."
  RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/xtls/libxray/releases/latest" 2>/dev/null)
  LIBXRAY_URL=$(echo "$RELEASE_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assets = d.get('assets', [])
for a in assets:
    name = a['name'].lower()
    if 'android' in name and name.endswith('.aar'):
        print(a['browser_download_url'])
        break
" 2>/dev/null)

  if [ -n "$LIBXRAY_URL" ]; then
    curl -fL "$LIBXRAY_URL" -o "$LIBS_DIR/libxray.aar"
    echo "  libxray.aar скачан: $(ls -lh $LIBS_DIR/libxray.aar | awk '{print $5}')"

    # Раскомментируем зависимость в build.gradle.kts
    sed -i 's|// compileOnly(fileTree|implementation(fileTree|g' app/build.gradle.kts
    echo "  libxray включён в build.gradle.kts"
  else
    echo "  WARN: libxray.aar не найден в релизах — VPN будет работать в stub-режиме"
  fi
fi

# ── 6. Сборка ───────────────────────────────────────────────
echo ""
echo "Собираю debug APK..."
./gradlew assembleDebug

APK=$(find app/build/outputs/apk/debug -name "*.apk" 2>/dev/null | head -1)
if [ -z "$APK" ]; then
  echo "ERROR: APK не найден после сборки"
  exit 1
fi

echo ""
echo "✅ APK готов:"
echo "   $SCRIPT_DIR/$APK"
ls -lh "$APK"

# ── 7. Установка на устройство (опционально) ─────────────────
ADB="${ANDROID_HOME}/platform-tools/adb"
if [ -f "$ADB" ] && "$ADB" devices 2>/dev/null | grep -q "device$"; then
  echo ""
  read -p "Установить на подключённое устройство? [y/N] " INSTALL
  if [[ "$INSTALL" =~ ^[Yy]$ ]]; then
    "$ADB" install -r "$APK"
    echo "Установлено!"
  fi
fi
