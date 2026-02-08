#!/usr/bin/env python3
"""
Калькулятор вместимости VPN-сервера.
Рассчитывает максимальное количество пользователей на основе характеристик сервера.
"""

import os
import subprocess
import sys


def get_cpu_cores() -> int:
    """Количество CPU ядер."""
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def get_ram_gb() -> float:
    """Объём RAM в GB."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024 / 1024, 1)
    except Exception:
        pass
    return 1.0


def get_bandwidth_mbps(run_speedtest: bool = False) -> tuple[int, int, bool]:
    """
    Получить пропускную способность сервера (Mbps).

    Args:
        run_speedtest: Запустить реальный тест скорости

    Returns:
        (download_mbps, upload_mbps, is_real_test)
    """
    if not run_speedtest:
        return (200, 200, False)  # Консервативная оценка

    print("⏳ Измерение реальной скорости (30-60 сек)...")

    try:
        result = subprocess.run(
            ["speedtest-cli", "--simple"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            download = upload = 0

            for line in lines:
                if line.startswith("Download:"):
                    download = int(float(line.split()[1]))
                elif line.startswith("Upload:"):
                    upload = int(float(line.split()[1]))

            if download > 0 and upload > 0:
                return (download, upload, True)
    except FileNotFoundError:
        print("⚠️  speedtest-cli не установлен. Установите: pip3 install speedtest-cli")
    except subprocess.TimeoutExpired:
        print("⚠️  Тест скорости превысил таймаут")
    except Exception as e:
        print(f"⚠️  Ошибка теста скорости: {e}")

    return (200, 200, False)


def calculate_capacity(
    cpu_cores: int,
    ram_gb: float,
    download_mbps: int,
    upload_mbps: int,
    avg_user_mbps: float = 5.0,  # Средняя скорость на пользователя
    ram_per_user_mb: float = 2.0,  # RAM на пользователя (Xray очень эффективен)
    concurrent_ratio: float = 0.3,  # Обычно онлайн ~30% от всех пользователей
) -> dict:
    """
    Рассчитать вместимость сервера.

    Для VPN важен Upload (пользователи скачивают = сервер отдаёт).

    Возвращает:
        - max_concurrent: максимум одновременных подключений
        - max_total: максимум всего пользователей (с учётом concurrent_ratio)
        - limiting_factor: что является ограничивающим фактором
    """
    # Лимит по CPU (Xray эффективен, ~500 подключений на ядро)
    cpu_limit = cpu_cores * 500

    # Лимит по RAM (оставляем 500MB на систему)
    available_ram_mb = (ram_gb * 1024) - 500
    ram_limit = int(available_ram_mb / ram_per_user_mb)

    # Лимит по bandwidth (для VPN важен Upload — пользователи скачивают через нас)
    bandwidth_limit = int(upload_mbps / avg_user_mbps)

    # Берём минимум из всех лимитов
    limits = {
        "CPU": cpu_limit,
        "RAM": ram_limit,
        "Bandwidth": bandwidth_limit,
    }

    limiting_factor = min(limits, key=limits.get)
    max_concurrent = limits[limiting_factor]

    # Если обычно онлайн 30%, то всего можно иметь больше пользователей
    max_total = int(max_concurrent / concurrent_ratio)

    return {
        "max_concurrent": max_concurrent,
        "max_total": max_total,
        "limiting_factor": limiting_factor,
        "limits": limits,
        "download_mbps": download_mbps,
        "upload_mbps": upload_mbps,
    }


def format_report(
    cpu_cores: int,
    ram_gb: float,
    capacity: dict,
    is_real_test: bool,
) -> str:
    """Форматировать отчёт о вместимости."""
    download = capacity['download_mbps']
    upload = capacity['upload_mbps']
    test_type = "реальный тест" if is_real_test else "оценка"

    return f"""
╔══════════════════════════════════════════════════════════════╗
║           SWAGA VPN — Расчёт вместимости сервера             ║
╠══════════════════════════════════════════════════════════════╣
║  ХАРАКТЕРИСТИКИ СЕРВЕРА:                                     ║
║  • CPU ядер: {cpu_cores:<48}║
║  • RAM: {ram_gb} GB{' ' * (46 - len(str(ram_gb)))}║
║  • Download: {download} Mbps ({test_type}){' ' * (32 - len(str(download)) - len(test_type))}║
║  • Upload: {upload} Mbps ({test_type}){' ' * (34 - len(str(upload)) - len(test_type))}║
╠══════════════════════════════════════════════════════════════╣
║  ЛИМИТЫ ПО РЕСУРСАМ (одновременных подключений):             ║
║  • По CPU: {capacity['limits']['CPU']:<50}║
║  • По RAM: {capacity['limits']['RAM']:<50}║
║  • По Upload: {capacity['limits']['Bandwidth']:<46}║
╠══════════════════════════════════════════════════════════════╣
║  РЕКОМЕНДАЦИИ:                                               ║
║                                                              ║
║  👥 Макс. одновременно: {capacity['max_concurrent']:<36}║
║  👤 Макс. всего пользователей: {capacity['max_total']:<29}║
║                                                              ║
║  ⚠️  Ограничивающий фактор: {capacity['limiting_factor']:<32}║
╠══════════════════════════════════════════════════════════════╣
║  ПРИМЕЧАНИЯ:                                                 ║
║  • Расчёт: 5 Mbps на пользователя                            ║
║  • ~30% пользователей онлайн одновременно                    ║
║  • Для VPN важен Upload (пользователи скачивают через нас)   ║
╚══════════════════════════════════════════════════════════════╝
"""


def main():
    # Проверяем аргументы командной строки
    run_speedtest = "--speedtest" in sys.argv or "-s" in sys.argv

    if not run_speedtest:
        print("💡 Совет: запустите с флагом --speedtest для реального теста скорости")
        print("   python3 capacity.py --speedtest\n")

    cpu = get_cpu_cores()
    ram = get_ram_gb()
    download, upload, is_real = get_bandwidth_mbps(run_speedtest)

    capacity = calculate_capacity(cpu, ram, download, upload)
    report = format_report(cpu, ram, capacity, is_real)

    print(report)

    return capacity


if __name__ == "__main__":
    main()
