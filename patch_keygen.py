#!/usr/bin/env python3
"""
Патч: добавляет команду /keygen DAYS в bot.py.
Запуск: python3 patch_keygen.py
"""
import re
import sys
import shutil
from pathlib import Path

BOT_PATH = Path(__file__).parent / "bot.py"

KEYGEN_CODE = '''
@dp.message_handler(commands=["keygen"])
async def cmd_keygen(message: types.Message) -> None:
    """
    Создать гивевей-ключ без привязки к реальному пользователю.
    Формат: /keygen DAYS
    Допустимые значения: 7, 30, 90, 365
    Пример: /keygen 30
    """
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    args = message.get_args().split()
    if not args or not args[0].isdigit():
        await message.answer(
            "❌ Формат: <code>/keygen ДНЕЙ</code>\\n\\n"
            "Допустимые значения: <b>7, 30, 90, 365</b>\\n"
            "Пример: <code>/keygen 30</code>"
        )
        return

    days = int(args[0])
    if days not in {7, 30, 90, 365}:
        await message.answer(
            f"❌ Недопустимое значение: <b>{days}</b>\\n"
            "Разрешено: <b>7, 30, 90, 365</b>"
        )
        return

    from servers import server_manager
    if not server_manager.servers:
        server_manager.load_config()

    servers = server_manager.get_healthy_servers()
    if not servers:
        await message.answer("❌ Нет доступных серверов. Проверьте health check.")
        return

    now = datetime.utcnow()
    end_date = now + timedelta(days=days)
    expiry_ms = int(end_date.timestamp() * 1000)

    import uuid as _uuid_lib
    import time as _time

    # Уникальный гивевей-ID (не пересекается с реальными Telegram ID)
    GIVEAWAY_BASE = 9_000_000_000
    giveaway_id = GIVEAWAY_BASE + (int(_time.time() * 1000) % 1_000_000_000)
    new_uuid = str(_uuid_lib.uuid4())
    sub_id_value = _uuid_lib.uuid4().hex[:16]
    email = f"giveaway_{giveaway_id}"

    await message.answer("⏳ Создаю ключи на серверах...")

    try:
        # Создаём фиктивного пользователя в БД
        await create_user(giveaway_id, f"giveaway_{giveaway_id}")

        selected_server = servers[0]

        from xui_api import XUIAPI
        srv_xui = XUIAPI()
        protocol = "https" if selected_server.xui_host not in ("127.0.0.1", "localhost") else "http"
        srv_xui.base_url = (
            f"{protocol}://{selected_server.xui_host}"
            f":{selected_server.xui_port}{selected_server.xui_web_path}"
        )

        login_resp = srv_xui.session.post(
            f"{srv_xui.base_url}/login",
            json={"username": selected_server.xui_username, "password": selected_server.xui_password},
            verify=False, timeout=10,
        )
        if not login_resp.json().get("success"):
            await message.answer(f"❌ Ошибка авторизации на сервере {selected_server.name}.")
            return
        srv_xui._logged_in = True

        success = srv_xui.add_client(
            selected_server.inbound_id,
            new_uuid, email,
            sub_id=sub_id_value,
            expiry_time=expiry_ms,
            flow=selected_server.flow,
        )
        if not success:
            await message.answer(f"❌ Не удалось создать ключ на {selected_server.name}.")
            return

        # Сохраняем подписку в БД
        await create_subscription(
            user_id=giveaway_id,
            plan=f"giveaway_{days}d",
            vless_uuid=new_uuid,
            start_date=now.isoformat(),
            end_date=end_date.isoformat(),
            server_id=selected_server.id,
            xui_email=email,
            xui_sub_id=sub_id_value,
        )

        # Синхронизируем на остальные серверы
        other_servers = [
            s for s in server_manager.get_all_servers()
            if s.enabled and s.id != selected_server.id
        ]
        if other_servers:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                _sync_client_to_other_servers,
                new_uuid, email, sub_id_value, expiry_ms,
                selected_server.id, other_servers,
            )

        sub_url = f"{SUB_BASE_URL}{sub_id_value}"
        connect_url = SUB_BASE_URL.replace("/sub/", "/connect/") + sub_id_value if SUB_BASE_URL else ""

        reply = (
            f"✅ <b>Гивевей-ключ создан</b>\\n\\n"
            f"⏱ Дней: <b>{days}</b>\\n"
            f"📅 Действует до: <b>{end_date.strftime('%d.%m.%Y')}</b>\\n\\n"
        )
        if connect_url:
            reply += f"🔗 <b>Быстрое подключение:</b>\\n{connect_url}\\n\\n"
        reply += f"📋 <b>Ссылка на подписку:</b>\\n<code>{sub_url}</code>"

        await message.answer(reply, disable_web_page_preview=True)
        logger.info(f"Admin {user_id} created giveaway key: {days}d, id={giveaway_id}")

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
        logger.error(f"keygen error: {e}")
        logger.error(traceback.format_exc())

'''

MARKER = '@dp.message_handler(commands=["broadcast"])'


def main():
    if not BOT_PATH.exists():
        print(f"❌ Файл не найден: {BOT_PATH}")
        sys.exit(1)

    source = BOT_PATH.read_text(encoding="utf-8")

    if 'commands=["keygen"]' in source:
        print("ℹ️  Команда /keygen уже присутствует в bot.py — патч не нужен.")
        sys.exit(0)

    if MARKER not in source:
        print(f"❌ Маркер не найден в bot.py:\n  {MARKER}")
        sys.exit(1)

    # Бэкап
    backup = BOT_PATH.with_suffix(".py.bak")
    shutil.copy2(BOT_PATH, backup)
    print(f"✅ Бэкап сохранён: {backup}")

    patched = source.replace(MARKER, KEYGEN_CODE + MARKER, 1)
    BOT_PATH.write_text(patched, encoding="utf-8")
    print("✅ Патч применён: команда /keygen добавлена в bot.py")
    print("👉 Перезапустите сервис: systemctl restart vpnbot")


if __name__ == "__main__":
    main()
