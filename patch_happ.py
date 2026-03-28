#!/usr/bin/env python3
"""
Патч: добавляет вкладку Happ на страницу /connect/ в sub_app.py.
Запуск: python3 patch_happ.py
"""
import shutil
import sys
from pathlib import Path

SUB_APP = Path(__file__).parent / "sub_app.py"

# ── Новый HTML с табами ────────────────────────────────────────────────────────

NEW_HTML = '''CONNECT_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SWAGA VPN</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         text-align: center; padding: 30px 16px; background: #0d1117; color: #e6edf3;
         margin: 0; }}
  h2 {{ margin: 0 0 6px; font-size: 22px; }}
  .logo {{ font-size: 40px; margin-bottom: 8px; }}
  .step {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px;
           padding: 16px; margin: 14px auto; max-width: 380px; text-align: left; }}
  .step-num {{ display: inline-block; width: 28px; height: 28px; line-height: 28px;
               border-radius: 50%; background: #238636; color: #fff; text-align: center;
               font-weight: 700; font-size: 14px; margin-right: 8px; flex-shrink: 0; }}
  .step-row {{ display: flex; align-items: center; margin-bottom: 6px; }}
  .step-text {{ font-size: 15px; }}
  .btn {{ display: block; margin: 14px auto; padding: 16px 28px; border-radius: 12px;
          text-decoration: none; font-size: 17px; font-weight: 600; cursor: pointer;
          border: none; max-width: 380px; width: 100%; text-align: center; }}
  .btn-primary {{ background: #238636; color: #fff; }}
  .btn-primary:active {{ background: #1a7f37; }}
  .btn-happ {{ background: #7c3aed; color: #fff; }}
  .btn-happ:active {{ background: #6d28d9; }}
  .btn-secondary {{ background: #21262d; color: #e6edf3; border: 1px solid #30363d; }}
  .btn-app {{ background: #21262d; color: #e6edf3; border: 1px solid #30363d;
              display: inline-block; width: auto; margin: 6px; padding: 12px 20px;
              font-size: 14px; border-radius: 10px; }}
  .apps {{ margin-top: 16px; }}
  .hint {{ color: #8b949e; font-size: 13px; margin-top: 8px; }}
  .hidden {{ display: none; }}
  .or {{ color: #8b949e; font-size: 14px; margin: 10px 0; }}

  /* Табы */
  .tabs {{ display: flex; max-width: 380px; margin: 20px auto 4px; border-radius: 12px;
           background: #161b22; border: 1px solid #30363d; overflow: hidden; }}
  .tab {{ flex: 1; padding: 12px; font-size: 15px; font-weight: 600; cursor: pointer;
          background: none; border: none; color: #8b949e; transition: all .2s; }}
  .tab.active {{ background: #21262d; color: #e6edf3; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
</style>
</head>
<body>

<div class="logo">&#x26A1;</div>
<h2>SWAGA VPN</h2>
<p style="color:#8b949e; margin-top:4px;">Быстрое подключение</p>

<div class="tabs">
  <button class="tab active" onclick="switchTab('v2raytun', this)">V2RayTun</button>
  <button class="tab" onclick="switchTab('happ', this)">Happ</button>
</div>

<!-- V2RayTun -->
<div id="tab-v2raytun" class="tab-content active">
  <a class="btn btn-primary" id="openAppBtn" href="{deeplink}">
    &#x1F680; Добавить подписку в V2RayTun
  </a>
  <p class="hint">Нажмите, чтобы автоматически добавить VPN</p>

  <p class="or">— или —</p>

  <button class="btn btn-secondary" id="copyBtn" onclick="copyConfig()">
    &#x1F4CB; Скопировать конфиг вручную
  </button>
  <p class="hint" id="copyHint"></p>

  <div class="step">
    <p style="color:#8b949e; font-size:14px; margin:0 0 10px;">Если автоматически не открылось:</p>
    <div class="step-row"><span class="step-num">1</span>
      <span class="step-text">Нажмите <b>«Скопировать конфиг»</b></span></div>
    <div class="step-row"><span class="step-num">2</span>
      <span class="step-text">Откройте <b>V2RayTun</b></span></div>
    <div class="step-row"><span class="step-num">3</span>
      <span class="step-text">Приложение предложит <b>импортировать</b></span></div>
  </div>

  <div class="apps">
    <p style="color:#8b949e; font-size:14px; margin-bottom:4px;">Нет приложения? Скачайте:</p>
    <a class="btn btn-app" href="https://apps.apple.com/app/v2raytun/id6476628951">iOS</a>
    <a class="btn btn-app" href="https://play.google.com/store/apps/details?id=com.v2raytun.android">Android</a>
  </div>
</div>

<!-- Happ -->
<div id="tab-happ" class="tab-content">
  <a class="btn btn-happ" href="{happ_deeplink}">
    &#x1F7E3; Добавить подписку в Happ
  </a>
  <p class="hint">Нажмите, чтобы автоматически добавить VPN в Happ</p>

  <p class="or">— или —</p>

  <button class="btn btn-secondary" onclick="copySubUrl()">
    &#x1F4CB; Скопировать ссылку подписки
  </button>
  <p class="hint" id="copyHintHapp"></p>

  <div class="step">
    <p style="color:#8b949e; font-size:14px; margin:0 0 10px;">Если автоматически не открылось:</p>
    <div class="step-row"><span class="step-num">1</span>
      <span class="step-text">Нажмите <b>«Скопировать ссылку»</b></span></div>
    <div class="step-row"><span class="step-num">2</span>
      <span class="step-text">Откройте <b>Happ</b> → Подписки</span></div>
    <div class="step-row"><span class="step-num">3</span>
      <span class="step-text">Нажмите <b>«+»</b> и вставьте ссылку</span></div>
  </div>

  <div class="apps">
    <p style="color:#8b949e; font-size:14px; margin-bottom:4px;">Нет приложения? Скачайте:</p>
    <a class="btn btn-app" href="https://apps.apple.com/app/happ-proxy-utility/id6504287480">iOS</a>
    <a class="btn btn-app" href="https://play.google.com/store/apps/details?id=com.happproxy.app">Android</a>
  </div>
</div>

<input type="text" id="configData" value="{vless_link}" class="hidden">
<input type="text" id="subUrlData" value="{sub_url}" class="hidden">

<script>
function switchTab(name, el) {{
  document.querySelectorAll('.tab-content').forEach(function(t) {{ t.classList.remove('active'); }});
  document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
  document.getElementById('tab-' + name).classList.add('active');
  el.classList.add('active');
}}

function copyConfig() {{
  var config = document.getElementById('configData').value;
  var btn = document.getElementById('copyBtn');
  var hint = document.getElementById('copyHint');
  copyText(config, btn, hint, 'Откройте V2RayTun — он предложит импорт');
}}

function copySubUrl() {{
  var url = document.getElementById('subUrlData').value;
  var btn = event.target;
  var hint = document.getElementById('copyHintHapp');
  copyText(url, btn, hint, 'Вставьте в Happ → Подписки → +');
}}

function copyText(text, btn, hint, successHint) {{
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(function() {{
      btn.innerHTML = '&#x2705; Скопировано!';
      hint.textContent = successHint;
    }}).catch(function() {{ fallback(text, btn, hint, successHint); }});
  }} else {{
    fallback(text, btn, hint, successHint);
  }}
}}

function fallback(text, btn, hint, successHint) {{
  var inp = document.createElement('textarea');
  inp.value = text;
  document.body.appendChild(inp);
  inp.select();
  try {{
    document.execCommand('copy');
    btn.innerHTML = '&#x2705; Скопировано!';
    hint.textContent = successHint;
  }} catch(e) {{
    hint.textContent = 'Скопируйте вручную';
  }}
  document.body.removeChild(inp);
}}
</script>
<p style="color:#8b949e; font-size:13px; margin-top:24px;">Telegram: <a href="https://t.me/Swaga_vpnbot" style="color:#58a6ff; text-decoration:none;">@Swaga_vpnbot</a></p>
</body>
</html>"""'''

# ── Новая строка deeplink (добавляем happ_deeplink) ────────────────────────────

OLD_DEEPLINK = '    deeplink = f"v2raytun://import/{sub_url}"'
NEW_DEEPLINK = (
    '    deeplink = f"v2raytun://import/{sub_url}"\n'
    '    happ_deeplink = f"happ://install-sub?url={sub_url}"'
)

OLD_FORMAT = 'html = CONNECT_HTML.format(vless_link=first_vless_link, sub_url=sub_url, deeplink=deeplink)'
NEW_FORMAT = 'html = CONNECT_HTML.format(vless_link=first_vless_link, sub_url=sub_url, deeplink=deeplink, happ_deeplink=happ_deeplink)'

# ── Старый HTML (маркеры начала и конца) ──────────────────────────────────────

OLD_HTML_START = 'CONNECT_HTML = """<!DOCTYPE html>'
OLD_HTML_END = '</html>"""'


def main():
    if not SUB_APP.exists():
        print(f"❌ Файл не найден: {SUB_APP}")
        sys.exit(1)

    source = SUB_APP.read_text(encoding="utf-8")

    if 'tab-happ' in source:
        print("ℹ️  Вкладка Happ уже присутствует — патч не нужен.")
        sys.exit(0)

    if OLD_HTML_START not in source:
        print("❌ Не найден маркер CONNECT_HTML в sub_app.py")
        sys.exit(1)

    # Бэкап
    backup = SUB_APP.with_suffix(".py.bak")
    shutil.copy2(SUB_APP, backup)
    print(f"✅ Бэкап сохранён: {backup}")

    # Заменяем HTML блок целиком
    start = source.index(OLD_HTML_START)
    end = source.index(OLD_HTML_END, start) + len(OLD_HTML_END)
    source = source[:start] + NEW_HTML + source[end:]

    # Добавляем happ_deeplink переменную
    if OLD_DEEPLINK in source:
        source = source.replace(OLD_DEEPLINK, NEW_DEEPLINK, 1)
        print("✅ Добавлена переменная happ_deeplink")
    else:
        print("⚠️  Строка deeplink не найдена — проверьте вручную")

    # Обновляем format() вызов
    if OLD_FORMAT in source:
        source = source.replace(OLD_FORMAT, NEW_FORMAT, 1)
        print("✅ Обновлён вызов CONNECT_HTML.format()")
    else:
        print("⚠️  Строка format() не найдена — проверьте вручную")

    SUB_APP.write_text(source, encoding="utf-8")
    print("✅ Патч применён: вкладка Happ добавлена на страницу /connect/")
    print("👉 Перезапустите сервис: systemctl restart vpnbot")


if __name__ == "__main__":
    main()
