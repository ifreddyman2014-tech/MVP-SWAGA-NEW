#!/usr/bin/env python3
"""
Калькулятор вместимости VPN-сервера.
Рассчитывает максимальное количество пользователей на основе характеристик сервера.
"""

import os
import subprocess


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


def get_bandwidth_mbps() -> int:
    """
    Примерная пропускная способность сервера (Mbps).
    Возвращает типичное значение для VPS.
    """
    # Для точного измерения нужен speedtest, используем типичные значения
    # Большинство VPS имеют 100-1000 Mbps
    return 200  # Консервативная оценка для типичного VPS


def calculate_capacity(
    cpu_cores: int,
    ram_gb: float,
    bandwidth_mbps: int,
    avg_user_mbps: float = 5.0,  # Средняя скорость на пользователя
    ram_per_user_mb: float = 2.0,  # RAM на пользователя (Xray очень эффективен)
    concurrent_ratio: float = 0.3,  # Обычно онлайн ~30% от всех пользователей
) -> dict:
    """
    Рассчитать вместимость сервера.

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

    # Лимит по bandwidth
    bandwidth_limit = int(bandwidth_mbps / avg_user_mbps)

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
    }


def format_report(
    cpu_cores: int,
    ram_gb: float,
    bandwidth_mbps: int,
    capacity: dict,
) -> str:
    """Форматировать отчёт о вместимости."""
    return f"""
╔══════════════════════════════════════════════════════════════╗
║           SWAGA VPN — Расчёт вместимости сервера             ║
╠══════════════════════════════════════════════════════════════╣
║  ХАРАКТЕРИСТИКИ СЕРВЕРА:                                     ║
║  • CPU ядер: {cpu_cores:<48}║
║  • RAM: {ram_gb} GB{' ' * (46 - len(str(ram_gb)))}║
║  • Bandwidth: ~{bandwidth_mbps} Mbps{' ' * (41 - len(str(bandwidth_mbps)))}║
╠══════════════════════════════════════════════════════════════╣
║  ЛИМИТЫ ПО РЕСУРСАМ:                                         ║
║  • По CPU: {capacity['limits']['CPU']:<50}║
║  • По RAM: {capacity['limits']['RAM']:<50}║
║  • По Bandwidth: {capacity['limits']['Bandwidth']:<43}║
╠══════════════════════════════════════════════════════════════╣
║  РЕКОМЕНДАЦИИ:                                               ║
║                                                              ║
║  Макс. одновременных подключений: {capacity['max_concurrent']:<26}║
║  Макс. всего пользователей: {capacity['max_total']:<32}║
║                                                              ║
║  Ограничивающий фактор: {capacity['limiting_factor']:<36}║
╠══════════════════════════════════════════════════════════════╣
║  ПРИМЕЧАНИЯ:                                                 ║
║  • Расчёт на среднюю скорость 5 Mbps на пользователя         ║
║  • Предполагается ~30% онлайн в любой момент                 ║
║  • Xray/VLESS очень эффективен по ресурсам                   ║
║  • Для точного теста нужен реальный мониторинг               ║
╚══════════════════════════════════════════════════════════════╝
"""


def main():
    cpu = get_cpu_cores()
    ram = get_ram_gb()
    bandwidth = get_bandwidth_mbps()

    capacity = calculate_capacity(cpu, ram, bandwidth)
    report = format_report(cpu, ram, bandwidth, capacity)

    print(report)

    return capacity


if __name__ == "__main__":
    main()
