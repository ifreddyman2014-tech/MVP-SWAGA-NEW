"""
SWAGA VPN — Веб-сайт (аналог Telegram-бота без Telegram).
Позволяет зарегистрироваться через email и получить VPN-подписку.

Маршруты:
  GET  /           — Лендинг
  GET  /register   — Страница регистрации
  POST /api/register — Создать аккаунт (JSON API)
  GET  /login      — Страница входа
  POST /api/login  — Войти (устанавливает cookie)
  GET  /dashboard  — Личный кабинет (требует auth)
  GET  /logout     — Выйти
"""

import asyncio
import collections
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta

import aiosqlite
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

# Импортируем после load_dotenv
from config import (
    WEB_SECRET_KEY, WEB_LISTEN_PORT, WEB_ADMIN_TOKEN,
    SUB_BASE_URL, PLANS, SUPPORT_URL, BOT_TOKEN, BOT_USERNAME,
    DB_PATH,
)
from database import (
    init_web_users_table, create_web_user,
    get_web_user_by_email, get_web_user_by_id,
    set_web_user_sub_id, create_subscription,
    get_all_web_users_with_subs,
    create_payment as db_create_payment,
    create_user as db_create_user,
    get_web_user_by_telegram_id,
    create_web_user_from_telegram,
)
from servers import server_manager
from utils import generate_uuid, generate_sub_id
from xui_api import XUIAPI

logger = logging.getLogger(__name__)

# ── Константы ─────────────────────────────────────────────────────────────────
COOKIE_NAME = "swaga_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 дней
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "7"))

# ── HTML-экранирование ────────────────────────────────────────────────────────

def _h(text: str) -> str:
    """Экранировать HTML-спецсимволы (защита от XSS)."""
    return (str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;"))


# ── Rate limiting (in-memory, per IP) ────────────────────────────────────────

_rl_store: dict[str, collections.deque] = {}


def _rate_limit_ok(ip: str, key: str, max_hits: int, window_secs: int) -> bool:
    """Вернуть True если запрос разрешён, False если лимит превышен."""
    full_key = f"{key}:{ip}"
    now = time.time()
    if full_key not in _rl_store:
        _rl_store[full_key] = collections.deque()
    dq = _rl_store[full_key]
    while dq and dq[0] < now - window_secs:
        dq.popleft()
    if len(dq) >= max_hits:
        return False
    dq.append(now)
    return True


def _client_ip(request: web.Request) -> str:
    """Получить IP клиента (учитывая Cloudflare/nginx X-Forwarded-For)."""
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote
        or "unknown"
    )


# ── Metrics dashboard ─────────────────────────────────────────────────────────

_MDASH_CSS = """
.md-wrap { max-width: 1200px; margin: 0 auto; padding: 28px 24px 80px; }
.md-header { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 32px; }
.md-title { font-size: 1.6rem; font-weight: 700; color: #f1f5f9; margin: 0; }
.md-badge { font-size: 0.72rem; font-weight: 700; letter-spacing: .06em; padding: 4px 10px;
  border-radius: 4px; text-transform: uppercase; }
.md-badge-ro { background: #1e3a5f; color: #60a5fa; }
.md-meta { margin-left: auto; font-size: 0.82rem; color: #64748b; text-align: right; line-height: 1.6; }
.md-refresh { background: #7c3aed; color: #fff; border: none; padding: 8px 18px;
  border-radius: 6px; font-size: 0.85rem; cursor: pointer; }
.md-refresh:hover { background: #6d28d9; }
.md-kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 16px; }
.md-kpi { background: #1e293b; border-radius: 12px; padding: 22px 24px; }
.md-kpi-label { font-size: 0.76rem; color: #64748b; text-transform: uppercase;
  letter-spacing: .06em; margin-bottom: 8px; }
.md-kpi-value { font-size: 1.75rem; font-weight: 700; color: #f1f5f9; line-height: 1.2; }
.md-kpi-sub { font-size: 0.78rem; color: #94a3b8; margin-top: 6px; }
.md-grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
.md-grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 20px; }
.md-card { background: #1e293b; border-radius: 12px; padding: 24px; }
.md-card-title { font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .07em; color: #7c3aed; margin-bottom: 18px; }
.md-card-full { margin-bottom: 20px; }
.md-stat-row { display: flex; justify-content: space-between; align-items: baseline;
  padding: 9px 0; border-bottom: 1px solid #0f172a; }
.md-stat-row:last-child { border-bottom: none; }
.md-stat-label { font-size: 0.85rem; color: #94a3b8; }
.md-stat-value { font-size: 0.95rem; font-weight: 600; color: #f1f5f9; }
.md-stat-value.green { color: #22c55e; }
.md-stat-value.yellow { color: #eab308; }
.md-stat-value.red { color: #ef4444; }
.md-bar-row { margin-bottom: 16px; }
.md-bar-label { font-size: 0.82rem; color: #94a3b8; margin-bottom: 6px; }
.md-bar-wrap { height: 9px; background: #0f172a; border-radius: 4px; overflow: hidden; margin-bottom: 5px; }
.md-bar-fill { height: 100%; border-radius: 4px; }
.md-bar-right { display: flex; justify-content: space-between; }
.md-bar-count { font-size: 0.78rem; color: #f1f5f9; font-weight: 600; }
.md-bar-pct { font-size: 0.78rem; color: #64748b; }
.road-row { display: grid; grid-template-columns: 60px 1fr 52px 160px; gap: 10px;
  align-items: center; margin-bottom: 12px; }
.road-label { font-size: 0.82rem; color: #94a3b8; font-weight: 600; }
.road-track { height: 9px; background: #0f172a; border-radius: 4px; overflow: hidden; }
.road-fill { height: 100%; border-radius: 4px; }
.road-pct { font-size: 0.78rem; color: #f1f5f9; text-align: right; }
.road-mrr { font-size: 0.72rem; color: #475569; text-align: right; }
.md-table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
.md-table th { font-size: 0.74rem; color: #64748b; text-transform: uppercase;
  letter-spacing: .05em; padding: 9px 10px; text-align: left; border-bottom: 1px solid #334155; }
.md-table td { padding: 10px 10px; border-bottom: 1px solid #0f172a; color: #cbd5e1; }
.md-table tr:last-child td { border-bottom: none; }
.td-num { text-align: right; color: #f1f5f9; }
.tr-total td { color: #f1f5f9; font-weight: 600; border-top: 1px solid #334155; padding-top: 12px; }
.tr-note td { color: #eab308; font-size: 0.76rem; padding-top: 8px; }
.md-mini-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; margin-top: 8px; }
.md-mini-table th { color: #64748b; padding: 4px 8px; }
.md-mini-table td { color: #cbd5e1; padding: 5px 8px; border-bottom: 1px solid #0f172a; }
.dq-item { padding: 11px 16px; border-radius: 8px; margin-bottom: 8px; font-size: 0.85rem;
  display: flex; align-items: center; gap: 10px; }
details.dq-item { display: block; }
details.dq-item summary { cursor: pointer; list-style: none; display: flex; align-items: center; gap: 10px; }
.dq-ok { background: #052e16; color: #86efac; }
.dq-warn { background: #2d1e00; color: #fde68a; }
.dq-err { background: #2d0f0f; color: #fca5a5; }
.dq-count { margin-left: auto; font-weight: 700; font-size: 1.05rem; }
.dq-detail { padding: 10px 0 2px 28px; font-size: 0.78rem; color: #94a3b8; }
.dq-detail code { color: #a78bfa; word-break: break-all; }
.ent-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 12px; }
.ent-card { background: #0f172a; border-radius: 10px; padding: 20px 22px; text-align: center; }
.ent-label { font-size: 0.76rem; color: #64748b; text-transform: uppercase;
  letter-spacing: .05em; margin-bottom: 8px; }
.ent-val { font-size: 1.6rem; font-weight: 700; }
.ent-val.green { color: #22c55e; }
.ent-val.blue { color: #60a5fa; }
.ent-val.dim { color: #475569; }
.ent-note { font-size: 0.78rem; color: #475569; margin-top: 12px; line-height: 1.6; }
.sim-form { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }
.sim-label { font-size: 0.8rem; color: #64748b; margin-bottom: 6px; }
.sim-input { width: 100%; box-sizing: border-box; background: #0f172a; color: #f1f5f9;
  border: 1px solid #334155; border-radius: 6px; padding: 10px 12px; font-size: 0.95rem; }
.sim-input:focus { outline: none; border-color: #7c3aed; }
.sim-btn { background: #7c3aed; color: #fff; border: none; padding: 11px 26px;
  border-radius: 6px; font-size: 0.9rem; cursor: pointer; }
.sim-btn:hover { background: #6d28d9; }
.sim-results { background: #0f172a; border-radius: 10px; padding: 18px 20px;
  font-size: 0.85rem; color: #cbd5e1; display: none; margin-top: 16px; }
.sim-results.visible { display: block; }
@media (max-width: 700px) {
  .md-kpi-row { grid-template-columns: repeat(2, 1fr); }
  .md-grid2, .md-grid3 { grid-template-columns: 1fr; }
  .ent-row, .sim-form { grid-template-columns: 1fr; }
  .road-row { grid-template-columns: 52px 1fr 46px; }
  .road-mrr { display: none; }
  .md-scenario-cx { grid-template-columns: repeat(3, 1fr); }
}
.md-alert { border-radius: 10px; padding: 14px 20px; margin-bottom: 20px; }
.md-alert-warn { background: #1c1200; border-left: 4px solid #d97706; color: #fde68a; }
.md-alert-title { font-weight: 700; font-size: 0.9rem; margin-bottom: 4px; }
.md-alert-sub { font-size: 0.82rem; color: #d97706; }
.md-scenario { margin-top: 22px; padding-top: 20px; border-top: 1px solid #334155; }
.md-scenario-title { font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .07em; color: #475569; margin-bottom: 14px; }
.md-scenario-kpis { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }
.md-scenario-kpi { background: #0f172a; border-radius: 8px; padding: 12px 14px; }
.md-scenario-label { font-size: 0.7rem; color: #475569; text-transform: uppercase;
  letter-spacing: .05em; margin-bottom: 4px; }
.md-scenario-val { font-size: 1.1rem; font-weight: 700; color: #a78bfa; }
.md-scenario-cx { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin-bottom: 10px; }
.md-scenario-cx-cell { background: #0f172a; border-radius: 6px; padding: 8px 6px; text-align: center; }
.md-scenario-cx-lbl { font-size: 0.65rem; color: #475569; margin-bottom: 3px; }
.md-scenario-cx-val { font-size: 0.88rem; font-weight: 700; color: #f1f5f9; }
.md-scenario-note { font-size: 0.72rem; color: #475569; }
"""

_MDASH_JS = """
async function runSim() {
  var p1m = document.getElementById('p1m').value;
  var p3m = document.getElementById('p3m').value;
  var p1y = document.getElementById('p1y').value;
  var el  = document.getElementById('sim-results');
  el.className = 'sim-results visible';
  el.textContent = 'Загрузка...';
  try {
    var url = '/api/admin/metrics/simulate?token=' + window.ADMIN_TOKEN
      + '&p1m=' + encodeURIComponent(p1m)
      + '&p3m=' + encodeURIComponent(p3m)
      + '&p1y=' + encodeURIComponent(p1y);
    var resp = await fetch(url);
    var data = await resp.json();
    if (!data.ok) { el.textContent = 'Ошибка: ' + (data.error || 'unknown'); return; }
    var s  = data.simulation;
    var cx = s.customers_for_mrr_target;
    var targets = [10000, 25000, 50000, 100000, 150000, 1000000];
    var html = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px">';
    html += '<div><div style="font-size:.7rem;color:#64748b">ARPU (мес. экв.)</div>'
           + '<div style="font-size:1.2rem;font-weight:700;color:#f1f5f9">' + s.effective_arpu.toFixed(2) + ' ₽</div></div>';
    html += '<div><div style="font-size:.7rem;color:#64748b">Симул. MRR</div>'
           + '<div style="font-size:1.2rem;font-weight:700;color:#22c55e">' + s.simulated_mrr.toFixed(2) + ' ₽</div></div>';
    html += '<div><div style="font-size:.7rem;color:#64748b">Покрытых</div>'
           + '<div style="font-size:1.2rem;font-weight:700;color:#f1f5f9">' + s.covered_users + '</div></div>';
    html += '</div><div style="font-size:.72rem;color:#64748b;margin-bottom:6px">Клиентов для MRR-цели:</div>';
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">';
    targets.forEach(function(t) {
      var lbl  = t >= 1000000 ? '1M' : (t / 1000) + 'K';
      var need = cx[t] !== undefined ? cx[t] : '—';
      html += '<div style="background:#1e293b;border-radius:6px;padding:8px 10px">';
      html += '<div style="font-size:.68rem;color:#64748b">' + lbl + ' ₽/мес</div>';
      html += '<div style="font-size:1rem;font-weight:700;color:#f1f5f9">' + need + '</div></div>';
    });
    html += '</div>';
    el.innerHTML = html;
  } catch(e) {
    el.textContent = 'Ошибка: ' + e.message;
  }
}
"""

_mdash_cache: dict = {}
_mdash_cache_ts: float = 0.0
_MDASH_CACHE_TTL = 60.0


def _require_admin_token(request: web.Request) -> None:
    if not WEB_ADMIN_TOKEN:
        raise web.HTTPForbidden(reason="Admin token not configured")
    token = request.rel_url.query.get("token", "")
    if not hmac.compare_digest(token, WEB_ADMIN_TOKEN):
        raise web.HTTPForbidden(reason="Invalid admin token")


async def _get_dashboard_metrics() -> dict:
    global _mdash_cache, _mdash_cache_ts
    now = time.monotonic()
    if _mdash_cache and now - _mdash_cache_ts < _MDASH_CACHE_TTL:
        return _mdash_cache
    from metrics import collect_metrics as _collect
    data = await _collect(DB_PATH)
    _mdash_cache = data
    _mdash_cache_ts = now
    return data


def _dash_rub(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f} ₽"


def _dash_pct(v) -> str:
    if v is None:
        return "—"
    return f"{v}%"


def _dash_bar(label: str, count: int, total: int, color: str) -> str:
    pct = round(count / total * 100, 1) if total else 0.0
    return (
        '<div class="md-bar-row">'
        f'<div class="md-bar-label">{_h(label)}</div>'
        '<div class="md-bar-wrap">'
        f'<div class="md-bar-fill" style="width:{pct}%;background:{_h(color)}"></div>'
        '</div>'
        '<div class="md-bar-right">'
        f'<span class="md-bar-count">{count}</span>'
        f'<span class="md-bar-pct">{pct}%</span>'
        '</div></div>'
    )


def _dq_item(label: str, count: int, severity: str, detail_html: str = "") -> str:
    icon = {"ok": "✅", "warn": "⚠️", "error": "🔴"}.get(severity, "ℹ️")
    cls  = {"ok": "dq-ok", "warn": "dq-warn", "error": "dq-err"}.get(severity, "")
    badge = f'<span class="dq-count">{count}</span>'
    if detail_html:
        return (
            f'<details class="dq-item {cls}">'
            f'<summary>{icon} {_h(label)} {badge}</summary>'
            f'<div class="dq-detail">{detail_html}</div></details>'
        )
    return f'<div class="dq-item {cls}">{icon} {_h(label)} {badge}</div>'


def _render_metrics_dashboard(m: dict, token: str) -> str:
    meta   = m.get("meta", {})
    u      = m.get("users", {})
    cs     = m.get("customer_status", {})
    cash   = m.get("cash_revenue", {})
    mrr_d  = m.get("estimated_mrr", {})
    np_    = m.get("new_payers", {})
    rv     = m.get("renewals", {})
    bm     = m.get("buyer_metrics", {})
    ppm    = m.get("purchase_plan_mix", {})
    apm    = m.get("active_plan_mix", {})
    ent    = m.get("payment_entitlement", {})
    di     = m.get("data_integrity", {})
    sanity = m.get("sanity", [])

    generated = _h((meta.get("generated_at_utc") or "")[:16])
    biz_date  = _h(meta.get("business_date", "?"))
    biz_tz    = _h(meta.get("business_timezone", ""))
    token_js  = json.dumps(token)

    ap_count  = u.get("active_paid", {}).get("total", 0)
    total_mrr = mrr_d.get("known_mrr", 0.0)
    coverage  = mrr_d.get("coverage_pct", 0.0)
    covered   = mrr_d.get("covered_users", 0)
    arppu_cov = mrr_d.get("arppu_covered")
    total_r   = u.get("total_real", 0)
    ever_p    = u.get("ever_paid", 0)
    bc_ever   = (bm.get("buyer_conversion") or {}).get("ever_paid_of_real")
    abr       = bm.get("active_buyer_rate")
    rbr       = bm.get("repeat_buyer_rate")
    ca_hist   = bm.get("cash_arppu_historical")

    cash_today = cash.get("today", 0.0)
    cash_7d    = cash.get("last_7d", 0.0)
    cash_30d   = cash.get("last_30d", 0.0)
    cash_month = cash.get("current_month", 0.0)
    cash_all   = cash.get("all_time", 0.0)

    rv_ev = rv.get("events", {})
    rv_us = rv.get("users", {})
    hfb   = bm.get("high_frequency_buyers", {})

    # KPI row 1
    ap_pct = round(ap_count / total_r * 100, 1) if total_r else 0.0
    kpi1 = (
        f'<div class="md-kpi"><div class="md-kpi-label">Активных платящих</div>'
        f'<div class="md-kpi-value">{ap_count}</div>'
        f'<div class="md-kpi-sub">из {total_r} реальных ({ap_pct}%)</div></div>'

        f'<div class="md-kpi"><div class="md-kpi-label">MRR (расчётный)</div>'
        f'<div class="md-kpi-value">{_dash_rub(total_mrr)}</div>'
        f'<div class="md-kpi-sub">покрытие {covered}/{ap_count} ({coverage}%)</div></div>'

        f'<div class="md-kpi"><div class="md-kpi-label">ARPPU (покрытые)</div>'
        f'<div class="md-kpi-value">{_dash_rub(arppu_cov)}</div>'
        f'<div class="md-kpi-sub">в месяц, по платёжам</div></div>'

        f'<div class="md-kpi"><div class="md-kpi-label">Cash этот месяц</div>'
        f'<div class="md-kpi-value">{_dash_rub(cash_month)}</div>'
        f'<div class="md-kpi-sub">Всё время: {_dash_rub(cash_all)}</div></div>'
    )

    # KPI row 2
    inactive_p = cs.get("inactive_paid", 0)
    kpi2 = (
        f'<div class="md-kpi"><div class="md-kpi-label">Реальных пользователей</div>'
        f'<div class="md-kpi-value">{total_r}</div>'
        f'<div class="md-kpi-sub">TG: {u.get("real_tg",0)}, Web: {u.get("web",0)}</div></div>'

        f'<div class="md-kpi"><div class="md-kpi-label">Когда-либо платили</div>'
        f'<div class="md-kpi-value">{ever_p}</div>'
        f'<div class="md-kpi-sub">Неактивных: {inactive_p}</div></div>'

        f'<div class="md-kpi"><div class="md-kpi-label">Buyer Conversion</div>'
        f'<div class="md-kpi-value">{_dash_pct(bc_ever)}</div>'
        f'<div class="md-kpi-sub">платящих от реальных</div></div>'

        f'<div class="md-kpi"><div class="md-kpi-label">Active Buyer Rate</div>'
        f'<div class="md-kpi-value">{_dash_pct(abr)}</div>'
        f'<div class="md-kpi-sub">активных от платящих</div></div>'
    )

    # Growth cards
    today_cls = ' class="md-stat-value green"' if np_.get("today", 0) > 0 else ' class="md-stat-value"'
    new_payers_card = (
        '<div class="md-card"><div class="md-card-title">Новые покупатели (first pay)</div>'
        f'<div class="md-stat-row"><span class="md-stat-label">Сегодня</span>'
        f'<span{today_cls}>{np_.get("today",0)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">7 дней</span>'
        f'<span class="md-stat-value">{np_.get("last_7d",0)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">30 дней</span>'
        f'<span class="md-stat-value">{np_.get("last_30d",0)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">Текущий месяц</span>'
        f'<span class="md-stat-value">{np_.get("current_month",0)}</span></div></div>'
    )

    renewals_card = (
        '<div class="md-card"><div class="md-card-title">Продления</div>'
        f'<div class="md-stat-row"><span class="md-stat-label">События 30д</span>'
        f'<span class="md-stat-value">{rv_ev.get("last_30d",0)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">Пользователей 30д</span>'
        f'<span class="md-stat-value">{rv_us.get("last_30d",0)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">События 7д</span>'
        f'<span class="md-stat-value">{rv_ev.get("last_7d",0)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">Текущий месяц</span>'
        f'<span class="md-stat-value">{rv_ev.get("current_month",0)}</span></div></div>'
    )

    buyer_card = (
        '<div class="md-card"><div class="md-card-title">Buyer Metrics</div>'
        f'<div class="md-stat-row"><span class="md-stat-label">Repeat Buyer Rate</span>'
        f'<span class="md-stat-value">{_dash_pct(rbr)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">3+ покупок</span>'
        f'<span class="md-stat-value">{hfb.get("3plus",{}).get("count",0)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">5+ покупок</span>'
        f'<span class="md-stat-value">{hfb.get("5plus",{}).get("count",0)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label" title="Вся полученная выручка / все когда-либо платившие">Выручка на покупателя</span>'
        f'<span class="md-stat-value">{_dash_rub(ca_hist)}</span></div></div>'
    )

    # Customer status bars
    cs_total = cs.get("total_real", 1) or 1
    cs_html = (
        _dash_bar("Активные платящие", cs.get("active_paid", 0), cs_total, "#7c3aed") +
        _dash_bar("Неактивные платящие (бывшие)", cs.get("inactive_paid", 0), cs_total, "#a855f7") +
        _dash_bar("Активные бесплатные (trial/giveaway)", cs.get("active_free", 0), cs_total, "#06b6d4") +
        _dash_bar("Никогда не платили", cs.get("never_paid", 0), cs_total, "#475569")
    )

    # Active plan mix table
    by_plan = apm.get("by_plan", {})
    plan_names = {"1m": "1 месяц", "3m": "3 месяца", "1y": "1 год"}
    plan_rows_html = ""
    t_ex = t_inf = t_tot = 0
    for pk in ("1m", "3m", "1y"):
        ex  = by_plan.get(pk, {}).get("exact", 0)
        inf = by_plan.get(pk, {}).get("inferred", 0)
        tot = ex + inf
        t_ex += ex; t_inf += inf; t_tot += tot
        plan_rows_html += (
            f'<tr><td>{plan_names[pk]}</td>'
            f'<td class="td-num">{ex}</td><td class="td-num">{inf}</td>'
            f'<td class="td-num"><b>{tot}</b></td></tr>'
        )
    unres = apm.get("unresolved", 0)
    plan_rows_html += (
        f'<tr class="tr-total"><td>Итого</td>'
        f'<td class="td-num">{t_ex}</td><td class="td-num">{t_inf}</td>'
        f'<td class="td-num"><b>{t_tot}</b></td></tr>'
    )
    if unres:
        plan_rows_html += f'<tr class="tr-note"><td colspan="4">Неопределённый текущий тариф: {unres} (plan mismatch, платёж есть)</td></tr>'

    # Purchase mix table
    def _ppm_row(label, key):
        d = ppm.get(key, {}); m1 = d.get("1m", 0); m3 = d.get("3m", 0); y1 = d.get("1y", 0)
        return (
            f'<tr><td>{_h(label)}</td>'
            f'<td class="td-num">{m1}</td><td class="td-num">{m3}</td>'
            f'<td class="td-num">{y1}</td><td class="td-num"><b>{m1+m3+y1}</b></td></tr>'
        )

    ppm_rows_html = (
        _ppm_row("Сегодня", "today") + _ppm_row("7 дней", "last_7d") +
        _ppm_row("30 дней", "last_30d") + _ppm_row("Месяц", "current_month") +
        _ppm_row("Всё время", "all_time")
    )

    # Revenue
    revenue_html = (
        f'<div class="md-stat-row"><span class="md-stat-label">Сегодня</span>'
        f'<span class="md-stat-value">{_dash_rub(cash_today)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">7 дней</span>'
        f'<span class="md-stat-value">{_dash_rub(cash_7d)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">30 дней</span>'
        f'<span class="md-stat-value">{_dash_rub(cash_30d)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">Текущий месяц</span>'
        f'<span class="md-stat-value">{_dash_rub(cash_month)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label">Всё время</span>'
        f'<span class="md-stat-value">{_dash_rub(cash_all)}</span></div>'
        '<div class="md-stat-row" style="border-top:1px solid #334155;margin-top:4px">'
        f'<span class="md-stat-label">MRR расчётный</span>'
        f'<span class="md-stat-value green">{_dash_rub(total_mrr)}</span></div>'
        f'<div class="md-stat-row"><span class="md-stat-label" title="Вся полученная выручка / все когда-либо платившие">Выручка / покупатель (all-time)</span>'
        f'<span class="md-stat-value">{_dash_rub(ca_hist)}</span></div>'
        '<div style="font-size:0.72rem;color:#475569;margin-top:2px;padding-bottom:2px">'
        'Вся полученная выручка / все когда-либо платившие</div>'
    )

    # Road to MRR
    road_html = ""
    for t in (10_000, 25_000, 50_000, 100_000, 150_000, 1_000_000):
        pct_t = min(round(total_mrr / t * 100, 1) if t else 0, 100.0)
        color = "#22c55e" if pct_t >= 100 else "#7c3aed"
        lbl   = f"{t // 1000}K ₽" if t < 1_000_000 else "1M ₽"
        road_html += (
            f'<div class="road-row">'
            f'<div class="road-label">{lbl}</div>'
            f'<div class="road-track"><div class="road-fill" style="width:{pct_t}%;background:{color}"></div></div>'
            f'<div class="road-pct">{pct_t}%</div>'
            f'<div class="road-mrr">{_dash_rub(total_mrr)} / {_dash_rub(float(t))}</div>'
            f'</div>'
        )

    # Scenario 199/449/1690 (server-side, pure function, no DB)
    try:
        from metrics import simulate_pricing as _sim_pricing
        _sc = _sim_pricing(apm, [199.0, 449.0, 1690.0])
    except Exception:
        _sc = None
    if _sc:
        _sc_arpu = _sc.get("effective_arpu", 0)
        _sc_mrr  = _sc.get("simulated_mrr", 0)
        _sc_cx   = _sc.get("customers_for_mrr_target", {})
        _cx_cells = "".join(
            f'<div class="md-scenario-cx-cell">'
            f'<div class="md-scenario-cx-lbl">{t // 1000}K</div>'
            f'<div class="md-scenario-cx-val">{_sc_cx.get(t, "—")}</div>'
            f'</div>'
            for t in (10_000, 25_000, 50_000, 100_000, 150_000)
        )
        scenario_section_html = (
            '<div class="md-scenario">'
            '<div class="md-scenario-title">Сценарий новых цен (199 / 449 / 1690 ₽)</div>'
            '<div class="md-scenario-kpis">'
            f'<div class="md-scenario-kpi"><div class="md-scenario-label">Effective ARPU</div>'
            f'<div class="md-scenario-val">{_sc_arpu:.2f} ₽</div></div>'
            f'<div class="md-scenario-kpi"><div class="md-scenario-label">Симул. MRR</div>'
            f'<div class="md-scenario-val">{_sc_mrr:,.2f} ₽</div></div>'
            '</div>'
            '<div style="font-size:0.72rem;color:#475569;margin-bottom:8px">Клиентов для MRR-цели:</div>'
            f'<div class="md-scenario-cx">{_cx_cells}</div>'
            '<div class="md-scenario-note">Модель при текущем plan mix. Не фактический MRR.</div>'
            '</div>'
        )
    else:
        scenario_section_html = ""

    # Growth alert
    growth_alert_html = ""
    if np_.get("last_30d", 0) == 0:
        growth_alert_html = (
            '<div class="md-alert md-alert-warn">'
            '<div class="md-alert-title">📉 Новых покупателей за 30 дней: 0</div>'
            '<div class="md-alert-sub">Основная текущая точка роста — привлечение новых платящих пользователей.</div>'
            '</div>'
        )

    # Payment entitlement
    ent_total = ent.get("total_payments", 0)
    ent_conf  = ent.get("confirmed", 0)
    ent_susp  = ent.get("suspicious", 0)
    ent_unver = ent.get("unverifiable", 0)
    ent_cpct  = ent.get("confirmed_pct", 0.0)
    ent_spct  = ent.get("suspicious_pct", 0.0)

    ent_html = (
        '<div class="ent-row">'
        '<div class="ent-card"><div class="ent-label">Точное сопоставление</div>'
        f'<div class="ent-val green">{ent_conf}</div>'
        f'<div style="font-size:0.76rem;color:#64748b">{ent_cpct}%</div></div>'
        '<div class="ent-card"><div class="ent-label">Продление / историч.</div>'
        f'<div class="ent-val blue">{ent_susp}</div>'
        f'<div style="font-size:0.76rem;color:#64748b">{ent_spct}%</div></div>'
        '<div class="ent-card"><div class="ent-label">Требует проверки</div>'
        f'<div class="ent-val dim">{ent_unver}</div></div>'
        '</div>'
        '<div class="ent-note">'
        'Точное сопоставление: start_date подписки в окне [-1h, +24h] от paid_at. '
        'При продлении существующая subscription обычно не получает новую start_date: '
        'изменяется end_date, поэтому такие платежи не являются ошибкой.'
        '</div>'
    )

    # Data quality
    ppwp   = di.get("paid_plan_without_payment", {})
    ppwp_c = ppwp.get("count", 0)
    ppwp_ids = ppwp.get("user_ids", [])
    ppwp_detail = (
        f'<code>User IDs: {_h(", ".join(str(x) for x in ppwp_ids))}</code>'
    ) if ppwp_ids else ""

    afwp   = di.get("active_free_without_payment", {})
    afwp_c = afwp.get("count", 0)

    buga   = di.get("paid_user_with_active_plan_trial", {})
    buga_c = buga.get("count", 0)
    buga_ids = buga.get("user_ids", [])
    buga_detail = (
        f'<code>User IDs: {_h(", ".join(str(x) for x in buga_ids[:20]))}</code>'
    ) if buga_ids else ""

    dup_c  = di.get("duplicate_active_subscriptions_per_user", {}).get("count", 0)
    gt400_c = di.get("suspicious_subscription_duration_gt_400_days", {}).get("count", 0)
    nopa_c  = di.get("succeeded_payments_without_paid_at", {}).get("count", 0)
    expa_c  = di.get("active_subscription_expired_by_date", {}).get("count", 0)

    mis    = di.get("plan_mismatch_needs_manual_review", {})
    mis_c  = mis.get("count", 0)
    mis_rows = "".join(
        f'<tr><td>{r.get("user_id","")}</td>'
        f'<td>{_h(str(r.get("sub_plan","")))}</td>'
        f'<td>{_h(str(r.get("pay_plan","")))}</td></tr>'
        for r in mis.get("detail", [])[:10]
    )
    mis_detail = (
        '<table class="md-mini-table">'
        '<tr><th>user_id</th><th>sub_plan</th><th>pay_plan</th></tr>'
        + mis_rows + '</table>'
    ) if mis_rows else ""

    dq_html = (
        _dq_item("Платный план без платежа (ERROR)", ppwp_c,
                 "ok" if ppwp_c == 0 else "error", ppwp_detail) +
        _dq_item("Бесплатные без платежа (trial/giveaway — норма)", afwp_c, "ok") +
        _dq_item("Bug A: plan=trial несмотря на платёж", buga_c,
                 "warn" if buga_c > 0 else "ok", buga_detail) +
        _dq_item("Дублирующиеся активные подписки", dup_c,
                 "ok" if dup_c == 0 else "error") +
        _dq_item("Подозрительная длительность >400 дней", gt400_c,
                 "ok" if gt400_c == 0 else "warn") +
        _dq_item("Успешные платежи без paid_at", nopa_c,
                 "ok" if nopa_c == 0 else "warn") +
        _dq_item("Активные подписки с истёкшей датой", expa_c,
                 "ok" if expa_c == 0 else "error") +
        _dq_item("Несоответствие плана sub↔pay", mis_c,
                 "ok" if mis_c == 0 else "warn", mis_detail)
    )

    sanity_html = "".join(
        f'<div class="dq-item {"dq-ok" if "All key counts" in note else "dq-warn"}">'
        f'{"✅" if "All key counts" in note else "⚠️"} {_h(note)}</div>'
        for note in sanity
    )

    return (
        '<!DOCTYPE html><html lang="ru"><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>SWAGA Metrics Dashboard</title>'
        f'<style>{_BASE_STYLE}\n{_MDASH_CSS}</style>'
        '</head><body><div class="md-wrap">'

        # Header
        '<div class="md-header">'
        '<h1 class="md-title">SWAGA Metrics</h1>'
        '<span class="md-badge md-badge-ro">READ ONLY</span>'
        f'<div class="md-meta">'
        f'<div>Дата: <b>{biz_date}</b> ({biz_tz})</div>'
        f'<div>Сгенерировано: {generated} UTC</div></div>'
        '<button class="md-refresh" onclick="location.reload()">↻ Обновить</button>'
        '</div>'

        # KPIs
        f'<div class="md-kpi-row">{kpi1}</div>'
        f'<div class="md-kpi-row">{kpi2}</div>'
        f'{growth_alert_html}'

        # Growth row
        f'<div class="md-grid3">{new_payers_card}{renewals_card}{buyer_card}</div>'

        # Main 2-col grid
        '<div class="md-grid2">'
        '<div>'
        f'<div class="md-card" style="margin-bottom:16px">'
        f'<div class="md-card-title">Customer Status (из {cs.get("total_real",0)} реальных)</div>'
        f'{cs_html}</div>'
        '<div class="md-card">'
        '<div class="md-card-title">Активный план-микс</div>'
        '<table class="md-table"><tr><th>Тариф</th><th class="td-num">Точно</th>'
        '<th class="td-num">Косвенно</th><th class="td-num">Итого</th></tr>'
        f'{plan_rows_html}</table>'
        '<div style="font-size:0.7rem;color:#475569;margin-top:8px">'
        'Точно = sub.plan совпадает с pay.plan_key; косвенно = Bug A (план=trial с платежом)'
        '</div></div>'
        '</div>'
        '<div>'
        f'<div class="md-card" style="margin-bottom:16px">'
        f'<div class="md-card-title">Выручка (cash)</div>{revenue_html}</div>'
        f'<div class="md-card"><div class="md-card-title">Road to MRR</div>{road_html}{scenario_section_html}</div>'
        '</div>'
        '</div>'

        # Purchase mix
        '<div class="md-card md-card-full">'
        '<div class="md-card-title">Purchase Mix (транзакции по тарифу)</div>'
        '<table class="md-table">'
        '<tr><th>Период</th><th class="td-num">1 мес</th><th class="td-num">3 мес</th>'
        '<th class="td-num">1 год</th><th class="td-num">Всего</th></tr>'
        f'{ppm_rows_html}</table></div>'

        # Payment entitlement
        f'<div class="md-card md-card-full">'
        f'<div class="md-card-title">Payment Entitlement ({ent_total} платежей)</div>'
        f'{ent_html}</div>'

        # Data quality
        '<div class="md-card md-card-full">'
        '<div class="md-card-title">Data Quality</div>'
        f'{dq_html}{sanity_html}</div>'

        # Pricing simulator
        '<div class="md-card md-card-full">'
        '<div class="md-card-title">Pricing Simulator</div>'
        f'<div style="font-size:0.78rem;color:#64748b;margin-bottom:12px">'
        f'Рассчитывает гипотетический MRR на основе текущего план-микса ({covered} покрытых).'
        '</div>'
        '<div class="sim-form">'
        '<div><div class="sim-label">Цена 1 мес (₽)</div>'
        '<input id="p1m" class="sim-input" type="number" min="1" value="199"></div>'
        '<div><div class="sim-label">Цена 3 мес (₽)</div>'
        '<input id="p3m" class="sim-input" type="number" min="1" value="449"></div>'
        '<div><div class="sim-label">Цена 1 год (₽)</div>'
        '<input id="p1y" class="sim-input" type="number" min="1" value="1690"></div>'
        '</div>'
        '<button class="sim-btn" onclick="runSim()">Рассчитать</button>'
        '<div id="sim-results" class="sim-results"></div>'
        '</div>'

        '</div>'  # /md-wrap
        f'<script>window.ADMIN_TOKEN={token_js};</script>'
        f'<script>{_MDASH_JS}</script>'
        '</body></html>'
    )


# ── Security headers middleware ───────────────────────────────────────────────

@web.middleware
async def security_headers_middleware(request: web.Request, handler) -> web.Response:
    response = await handler(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


# ── Сессии (HMAC-подписанный cookie) ─────────────────────────────────────────

def _sign(value: str) -> str:
    """Подписать строку HMAC-SHA256."""
    sig = hmac.new(WEB_SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{sig}"


def _verify(signed: str) -> str | None:
    """Проверить подпись и вернуть исходное значение или None."""
    if "." not in signed:
        return None
    value, sig = signed.rsplit(".", 1)
    expected = hmac.new(WEB_SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return value
    return None


def set_session_cookie(response: web.Response, web_user_id: int) -> None:
    value = _sign(str(web_user_id))
    response.set_cookie(
        COOKIE_NAME, value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="Lax",
    )


def get_session_user_id(request: web.Request) -> int | None:
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    raw = _verify(cookie)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# ── Хеширование паролей ───────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, dk_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ── Telegram Login Widget verification ───────────────────────────────────────

def verify_telegram_auth_data(data: dict) -> bool:
    """
    Проверить подпись данных от Telegram Login Widget.
    https://core.telegram.org/widgets/login#checking-authorization
    """
    if not BOT_TOKEN:
        return False
    hash_val = data.get("hash", "")
    check_data = {k: v for k, v in data.items() if k != "hash"}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(check_data.items()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    # Данные не должны быть старше 1 часа
    try:
        if time.time() - int(data.get("auth_date", 0)) > 3600:
            return False
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(computed, hash_val)


# ── Создание VPN-подписки ─────────────────────────────────────────────────────

def _create_trial_subscription_sync(user_id: int) -> tuple[str | None, str | None]:
    """
    Синхронно создаёт trial-подписку на всех серверах.
    Возвращает (xui_sub_id, error_message).
    Запускается в thread executor.
    """
    if not server_manager.servers:
        server_manager.load_config()

    servers = server_manager.get_all_servers()
    active_servers = [s for s in servers if s.enabled]

    if not active_servers:
        return None, "Нет доступных серверов"

    # Выбираем первый доступный сервер как основной
    selected = active_servers[0]

    new_uuid = generate_uuid()
    sub_id_value = generate_sub_id(16)
    email = f"web_{user_id}_{int(time.time())}"

    now = datetime.utcnow()
    end_date = now + timedelta(days=TRIAL_DAYS)
    expiry_ms = int(end_date.timestamp() * 1000)

    # Создаём клиента на основном сервере
    xui = XUIAPI.__new__(XUIAPI)
    xui.session = __import__("requests").Session()
    # HTTPS для внешних хостов, HTTP для localhost — как в bot.py
    protocol = "https" if selected.xui_host not in ("127.0.0.1", "localhost") else "http"
    xui.base_url = f"{protocol}://{selected.xui_host}:{selected.xui_port}{selected.xui_web_path}"
    xui._logged_in = False

    login_payload = {"username": selected.xui_username, "password": selected.xui_password}
    try:
        resp = xui.session.post(f"{xui.base_url}/login", json=login_payload, verify=False, timeout=10)
        if not resp.json().get("success"):
            return None, "Ошибка подключения к VPN-серверу"
        xui._logged_in = True
    except Exception as e:
        logger.error("Web registration: XUI login failed: %s", e)
        return None, "Ошибка подключения к VPN-серверу"

    ok = xui.add_client(
        selected.inbound_id, new_uuid, email,
        sub_id=sub_id_value, expiry_time=expiry_ms,
        flow=selected.flow or "",
    )
    if not ok:
        return None, "Не удалось создать VPN-аккаунт"

    # Синхронизируем с остальными серверами (best effort)
    for srv in active_servers[1:]:
        try:
            srv_xui = XUIAPI.__new__(XUIAPI)
            srv_xui.session = __import__("requests").Session()
            proto = "https" if srv.xui_host not in ("127.0.0.1", "localhost") else "http"
            srv_xui.base_url = f"{proto}://{srv.xui_host}:{srv.xui_port}{srv.xui_web_path}"
            srv_xui._logged_in = False
            login_resp = srv_xui.session.post(
                f"{srv_xui.base_url}/login",
                json={"username": srv.xui_username, "password": srv.xui_password},
                verify=False, timeout=10,
            )
            if login_resp.json().get("success"):
                srv_xui._logged_in = True
                srv_xui.add_client(
                    srv.inbound_id, new_uuid, email,
                    sub_id=sub_id_value, expiry_time=expiry_ms,
                    flow=srv.flow or "",
                )
        except Exception as e:
            logger.warning("Web registration: sync to %s failed: %s", srv.id, e)

    return (sub_id_value, new_uuid, email, selected.id,
            now.isoformat(), end_date.isoformat())


async def provision_trial(user_id: int) -> tuple[str | None, str | None]:
    """
    Асинхронная обёртка над синхронным созданием VPN-подписки.
    Возвращает (xui_sub_id, error) или создаёт запись в БД при успехе.
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _create_trial_subscription_sync, user_id)

    if isinstance(result, tuple) and len(result) == 2 and result[0] is None:
        # Вернулась ошибка: (None, error_msg)
        return None, result[1]

    sub_id_value, new_uuid, email, server_id, start_date, end_date = result

    # Сохраняем в БД
    await create_subscription(
        user_id=user_id,
        plan="trial",
        start_date=start_date,
        end_date=end_date,
        vless_uuid=new_uuid,
        xui_sub_id=sub_id_value,
        server_id=server_id,
        xui_email=email,
    )

    return sub_id_value, None


def _create_giveaway_key_sync(days: int) -> dict:
    """
    Синхронно создаёт гивей-ключ на всех серверах (без привязки к пользователю).
    Возвращает dict с ключами: sub_id, connect_url, sub_url, end_date, error.
    Запускается в thread executor.
    """
    import uuid as _uuid_lib
    import time as _time

    if not server_manager.servers:
        server_manager.load_config()

    servers = [s for s in server_manager.get_all_servers() if s.enabled]
    if not servers:
        return {"error": "Нет доступных серверов"}

    GIVEAWAY_BASE = 9_000_000_000
    giveaway_id = GIVEAWAY_BASE + (int(_time.time() * 1000) % 1_000_000_000)

    new_uuid = str(_uuid_lib.uuid4())
    sub_id_value = _uuid_lib.uuid4().hex[:16]
    email = f"giveaway_{giveaway_id}"

    now = datetime.utcnow()
    end_date = now + timedelta(days=days)
    expiry_ms = int(end_date.timestamp() * 1000)

    selected = servers[0]

    xui = XUIAPI.__new__(XUIAPI)
    xui.session = __import__("requests").Session()
    protocol = "https" if selected.xui_host not in ("127.0.0.1", "localhost") else "http"
    xui.base_url = f"{protocol}://{selected.xui_host}:{selected.xui_port}{selected.xui_web_path}"
    xui._logged_in = False

    try:
        resp = xui.session.post(
            f"{xui.base_url}/login",
            json={"username": selected.xui_username, "password": selected.xui_password},
            verify=False, timeout=10,
        )
        if not resp.json().get("success"):
            return {"error": f"Ошибка авторизации на сервере {selected.name}"}
        xui._logged_in = True
    except Exception as e:
        return {"error": f"Ошибка подключения к серверу: {e}"}

    ok = xui.add_client(
        selected.inbound_id, new_uuid, email,
        sub_id=sub_id_value, expiry_time=expiry_ms,
        flow=selected.flow or "",
    )
    if not ok:
        return {"error": f"Не удалось создать ключ на {selected.name}"}

    # Синхронизируем с остальными серверами
    for srv in servers[1:]:
        try:
            srv_xui = XUIAPI.__new__(XUIAPI)
            srv_xui.session = __import__("requests").Session()
            proto = "https" if srv.xui_host not in ("127.0.0.1", "localhost") else "http"
            srv_xui.base_url = f"{proto}://{srv.xui_host}:{srv.xui_port}{srv.xui_web_path}"
            srv_xui._logged_in = False
            lr = srv_xui.session.post(
                f"{srv_xui.base_url}/login",
                json={"username": srv.xui_username, "password": srv.xui_password},
                verify=False, timeout=10,
            )
            if lr.json().get("success"):
                srv_xui._logged_in = True
                srv_xui.add_client(
                    srv.inbound_id, new_uuid, email,
                    sub_id=sub_id_value, expiry_time=expiry_ms,
                    flow=srv.flow or "",
                )
        except Exception as e:
            logger.warning("keygen: sync to %s failed: %s", srv.id, e)

    return {
        "error": None,
        "giveaway_id": giveaway_id,
        "sub_id": sub_id_value,
        "new_uuid": new_uuid,
        "email": email,
        "server_id": selected.id,
        "now": now.isoformat(),
        "end_date": end_date.isoformat(),
        "end_display": end_date.strftime("%d.%m.%Y"),
    }


async def provision_giveaway_key(days: int) -> dict:
    """Async wrapper над _create_giveaway_key_sync."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _create_giveaway_key_sync, days)
    if result.get("error"):
        return result

    # Создаём фиктивного пользователя и подписку в БД
    giveaway_id = result["giveaway_id"]
    await db_create_user(giveaway_id, f"giveaway_{giveaway_id}")
    await create_subscription(
        user_id=giveaway_id,
        plan=f"giveaway_{days}d",
        vless_uuid=result["new_uuid"],
        start_date=result["now"],
        end_date=result["end_date"],
        server_id=result["server_id"],
        xui_email=result["email"],
        xui_sub_id=result["sub_id"],
    )

    connect_url = f"https://swaga-vpn.ru/connect/{result['sub_id']}"
    sub_url = f"https://sub.swaga-vpn.ru/sub/{result['sub_id']}"
    return {
        "error": None,
        "sub_id": result["sub_id"],
        "connect_url": connect_url,
        "sub_url": sub_url,
        "end_display": result["end_display"],
        "days": days,
    }


# ── HTML-шаблоны ──────────────────────────────────────────────────────────────

_BASE_STYLE = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0 }
  body {
    background: #0d1117;
    color: #e6edf3;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    min-height: 100vh;
    padding: 0;
  }
  a { color: #58a6ff; text-decoration: none }
  a:hover { text-decoration: underline }

  .nav {
    background: #161b22;
    border-bottom: 1px solid #30363d;
    padding: 14px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .nav-logo { font-size: 20px; font-weight: 700; color: #e6edf3 }
  .nav-links a {
    color: #8b949e;
    margin-left: 20px;
    font-size: 14px;
  }
  .nav-links a:hover { color: #e6edf3 }

  .container {
    max-width: 440px;
    margin: 0 auto;
    padding: 30px 16px 60px;
  }

  .card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 16px;
    padding: 28px 24px;
    margin-bottom: 16px;
  }

  .btn {
    display: block;
    width: 100%;
    padding: 14px 20px;
    border-radius: 12px;
    font-size: 16px;
    font-weight: 600;
    text-align: center;
    cursor: pointer;
    border: none;
    text-decoration: none;
    transition: opacity 0.15s;
  }
  .btn:hover { opacity: 0.88; text-decoration: none }
  .btn-primary { background: #238636; color: #fff }
  .btn-secondary {
    background: transparent;
    border: 1px solid #30363d;
    color: #8b949e;
    margin-top: 10px;
  }
  .btn-secondary:hover { color: #e6edf3; border-color: #8b949e }

  .input-group { margin-bottom: 14px }
  .input-group label {
    display: block;
    font-size: 13px;
    color: #8b949e;
    margin-bottom: 6px;
  }
  .input-group input {
    width: 100%;
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 12px 14px;
    color: #e6edf3;
    font-size: 15px;
    outline: none;
    transition: border-color 0.15s;
  }
  .input-group input:focus { border-color: #58a6ff }

  .error-box {
    background: rgba(244,63,94,0.08);
    border: 1px solid rgba(244,63,94,0.3);
    border-radius: 10px;
    padding: 12px 14px;
    color: #f44336;
    font-size: 14px;
    margin-bottom: 16px;
    display: none;
  }
  .error-box.visible { display: block }

  h1 { font-size: 26px; font-weight: 700; margin-bottom: 8px }
  h2 { font-size: 20px; font-weight: 600; margin-bottom: 14px }
  .sub { color: #8b949e; font-size: 14px; margin-bottom: 20px; line-height: 1.5 }
  .divider { border: none; border-top: 1px solid #30363d; margin: 18px 0 }
  .text-center { text-align: center }
  .text-sm { font-size: 13px; color: #8b949e }

  .feature-list { list-style: none; margin-bottom: 20px }
  .feature-list li {
    padding: 8px 0;
    font-size: 14px;
    color: #e6edf3;
    display: flex;
    align-items: center;
    gap: 10px;
    border-bottom: 1px solid #21262d;
  }
  .feature-list li:last-child { border-bottom: none }

  .plans-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px }
  .plan-card {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 14px 12px;
    text-align: center;
  }
  .plan-card.featured { border-color: #238636 }
  .plan-name { font-size: 12px; color: #8b949e; margin-bottom: 4px }
  .plan-price { font-size: 20px; font-weight: 700; color: #e6edf3 }
  .plan-price span { font-size: 12px; color: #8b949e; font-weight: 400 }
  .plan-badge {
    display: inline-block;
    background: #064e1e;
    color: #4caf50;
    font-size: 11px;
    border-radius: 6px;
    padding: 2px 7px;
    margin-top: 4px;
  }

  .steps { counter-reset: step }
  .step {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 10px;
    display: flex;
    align-items: flex-start;
    gap: 14px;
  }
  .step-num {
    width: 28px; height: 28px;
    border-radius: 50%;
    background: #238636;
    color: #fff;
    font-weight: 700;
    font-size: 14px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }
  .step-text { font-size: 14px; line-height: 1.5; color: #e6edf3 }
  .step-text small { color: #8b949e; font-size: 12px }

  .status-card {
    background: #161b22;
    border-radius: 12px;
    padding: 16px;
    border: 1px solid #30363d;
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .status-icon { font-size: 22px }
  .status-label { font-size: 12px; color: #8b949e }
  .status-val { font-size: 15px; font-weight: 600 }

  .tg-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 14px 16px;
    margin-top: 14px;
    text-align: center;
    font-size: 13px;
    color: #8b949e;
  }
</style>
"""

LANDING_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <title>SWAGA VPN — Быстрый и надёжный VPN</title>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0 }}
    :root {{
      --purple: #7c3aed; --purple-light: #a78bfa;
      --cyan: #06b6d4; --pink: #ec4899; --green: #10b981;
      --bg: #07071a; --card-bg: rgba(255,255,255,0.04);
      --card-border: rgba(255,255,255,0.08);
      --text: #f1f5f9; --muted: #94a3b8;
    }}
    html {{ scroll-behavior: smooth }}
    body {{
      background: var(--bg); color: var(--text);
      font-family: 'Inter', -apple-system, sans-serif;
      min-height: 100vh; overflow-x: hidden;
    }}
    body::before {{
      content: ''; position: fixed; inset: 0;
      background:
        radial-gradient(ellipse 80% 60% at 20% 10%, rgba(124,58,237,0.22) 0%, transparent 60%),
        radial-gradient(ellipse 60% 50% at 80% 90%, rgba(6,182,212,0.15) 0%, transparent 55%),
        radial-gradient(ellipse 50% 40% at 50% 50%, rgba(236,72,153,0.08) 0%, transparent 60%);
      pointer-events: none; z-index: 0;
    }}
    nav {{
      position: relative; z-index: 10;
      display: flex; align-items: center; justify-content: space-between;
      padding: 18px 24px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      backdrop-filter: blur(12px);
      background: rgba(7,7,26,0.7);
    }}
    .nav-logo {{
      font-size: 22px; font-weight: 900; letter-spacing: -0.5px;
      background: linear-gradient(135deg, #fff 0%, var(--purple-light) 60%, var(--cyan) 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text; text-decoration: none;
    }}
    .nav-links {{ display: flex; gap: 8px }}
    .nav-links a {{
      color: var(--muted); font-size: 14px; font-weight: 500;
      text-decoration: none; padding: 8px 16px; border-radius: 8px;
      transition: all 0.2s;
    }}
    .nav-links a:hover {{ color: #fff; background: rgba(255,255,255,0.07); text-decoration: none }}
    .nav-cta {{
      background: linear-gradient(135deg, var(--purple), #6d28d9) !important;
      color: #fff !important;
      box-shadow: 0 0 20px rgba(124,58,237,0.4);
    }}
    .nav-cta:hover {{ box-shadow: 0 0 28px rgba(124,58,237,0.6) !important }}
    .wrap {{
      position: relative; z-index: 1;
      max-width: 480px; margin: 0 auto; padding: 0 16px 60px;
    }}
    .hero {{ text-align: center; padding: 52px 0 36px }}
    .hero-badge {{
      display: inline-flex; align-items: center; gap: 6px;
      background: rgba(124,58,237,0.15);
      border: 1px solid rgba(124,58,237,0.4);
      border-radius: 100px; padding: 5px 14px;
      font-size: 12px; font-weight: 600; color: var(--purple-light);
      margin-bottom: 22px; letter-spacing: 0.03em;
    }}
    .hero-badge-dot {{
      width: 6px; height: 6px; border-radius: 50%;
      background: var(--purple-light);
      box-shadow: 0 0 8px var(--purple-light);
      animation: pulse 2s ease-in-out infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; transform: scale(1) }}
      50% {{ opacity: 0.6; transform: scale(0.8) }}
    }}
    .hero-mascot {{
      font-size: 72px; line-height: 1; margin-bottom: 18px; display: block;
      filter: drop-shadow(0 0 24px rgba(124,58,237,0.7)) drop-shadow(0 0 48px rgba(6,182,212,0.35));
      animation: float 4s ease-in-out infinite;
    }}
    @keyframes float {{
      0%, 100% {{ transform: translateY(0) }}
      50% {{ transform: translateY(-10px) }}
    }}
    .hero h1 {{
      font-size: 34px; font-weight: 900; line-height: 1.15;
      letter-spacing: -1px; margin-bottom: 14px;
    }}
    .grad {{
      background: linear-gradient(135deg, #fff 0%, var(--purple-light) 40%, var(--cyan) 80%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .hero-sub {{
      color: var(--muted); font-size: 15px; line-height: 1.6; margin-bottom: 28px;
    }}
    .hero-sub b {{ color: #cbd5e1 }}
    .btn-hero {{
      display: block; width: 100%; max-width: 380px; margin: 0 auto 12px;
      padding: 16px 24px; border-radius: 14px;
      font-size: 16px; font-weight: 700; text-align: center;
      cursor: pointer; border: none; text-decoration: none;
      background: linear-gradient(135deg, var(--purple), #9333ea, var(--cyan));
      background-size: 200% 200%;
      color: #fff;
      box-shadow: 0 4px 24px rgba(124,58,237,0.5);
      transition: all 0.3s;
      animation: gradshift 4s ease infinite;
    }}
    @keyframes gradshift {{
      0% {{ background-position: 0% 50% }}
      50% {{ background-position: 100% 50% }}
      100% {{ background-position: 0% 50% }}
    }}
    .btn-hero:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 32px rgba(124,58,237,0.65);
      text-decoration: none; color: #fff;
    }}
    .btn-ghost {{
      display: block; width: 100%; max-width: 380px; margin: 0 auto;
      padding: 14px 24px; border-radius: 14px;
      font-size: 15px; font-weight: 600; text-align: center;
      text-decoration: none; background: transparent;
      border: 1px solid rgba(255,255,255,0.12); color: var(--muted);
      transition: all 0.2s;
    }}
    .btn-ghost:hover {{
      border-color: rgba(255,255,255,0.25); color: #fff;
      background: rgba(255,255,255,0.04); text-decoration: none;
    }}
    .section-label {{
      font-size: 11px; text-transform: uppercase;
      letter-spacing: 0.15em; color: var(--muted);
      text-align: center; margin-bottom: 14px;
    }}
    .feat-grid {{
      display: grid; grid-template-columns: 1fr 1fr 1fr;
      gap: 10px; margin-bottom: 28px;
    }}
    .feat-card {{
      background: var(--card-bg); border: 1px solid var(--card-border);
      border-radius: 18px; padding: 20px 10px 16px; text-align: center;
      transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
    }}
    .feat-card:hover {{
      transform: translateY(-3px);
      border-color: rgba(124,58,237,0.4);
      box-shadow: 0 8px 28px rgba(124,58,237,0.15);
    }}
    .feat-icon {{
      font-size: 28px; margin-bottom: 8px; display: block;
      filter: drop-shadow(0 0 10px rgba(124,58,237,0.6));
    }}
    .feat-title {{ font-size: 11px; font-weight: 700; color: #fff; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px }}
    .feat-desc {{ font-size: 11px; color: var(--muted); line-height: 1.4 }}
    .info-row {{
      display: grid; grid-template-columns: 1fr 1fr;
      gap: 10px; margin-bottom: 28px;
    }}
    .info-card {{
      background: var(--card-bg); border: 1px solid var(--card-border);
      border-radius: 14px; padding: 16px 12px; text-align: center;
    }}
    .info-val {{ font-size: 20px; font-weight: 800; color: #fff; margin-bottom: 3px }}
    .info-val.gp {{
      background: linear-gradient(135deg, var(--purple-light), var(--cyan));
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .info-lbl {{ font-size: 12px; color: var(--muted) }}
    .pricing-title {{
      font-size: 26px; font-weight: 800; text-align: center;
      letter-spacing: -0.5px; margin-bottom: 18px;
    }}
    .price-grid {{
      display: grid; grid-template-columns: 1fr 1fr;
      gap: 12px; margin-bottom: 14px;
    }}
    .price-card {{
      background: var(--card-bg); border: 1px solid var(--card-border);
      border-radius: 20px; padding: 22px 14px 18px; text-align: center;
      transition: transform 0.2s, border-color 0.2s;
    }}
    .price-card:hover {{ transform: translateY(-3px) }}
    .price-card.feat-p {{
      background: linear-gradient(145deg, rgba(124,58,237,0.18), rgba(6,182,212,0.1));
      border-color: rgba(124,58,237,0.5);
      box-shadow: 0 0 30px rgba(124,58,237,0.2);
    }}
    .price-card.feat-t {{
      background: linear-gradient(145deg, rgba(16,185,129,0.12), rgba(6,182,212,0.08));
      border-color: rgba(16,185,129,0.4);
    }}
    .price-name {{ font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em; color: var(--muted); margin-bottom: 10px }}
    .price-val {{ font-size: 30px; font-weight: 900; color: #fff; line-height: 1; margin-bottom: 4px }}
    .price-val sup {{ font-size: 16px; vertical-align: super; font-weight: 700 }}
    .price-free {{
      background: linear-gradient(135deg, #10b981, #06b6d4);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text; font-size: 24px;
    }}
    .price-per {{ font-size: 11px; color: var(--muted); margin-bottom: 10px }}
    .pbadge {{
      display: inline-block; font-size: 10px; font-weight: 700;
      padding: 3px 10px; border-radius: 100px;
      text-transform: uppercase; letter-spacing: 0.08em;
    }}
    .pb-green {{ background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.35); color: #34d399 }}
    .pb-purple {{ background: rgba(124,58,237,0.15); border: 1px solid rgba(124,58,237,0.4); color: var(--purple-light) }}
    .pb-cyan {{ background: rgba(6,182,212,0.15); border: 1px solid rgba(6,182,212,0.35); color: #22d3ee }}
    .btn-price {{
      display: block; width: 100%; padding: 15px; border-radius: 12px;
      font-size: 15px; font-weight: 700; text-align: center;
      cursor: pointer; border: none; text-decoration: none;
      background: linear-gradient(135deg, var(--purple), #9333ea);
      color: #fff; box-shadow: 0 4px 20px rgba(124,58,237,0.4);
      transition: all 0.2s;
    }}
    .btn-price:hover {{
      transform: translateY(-1px);
      box-shadow: 0 6px 28px rgba(124,58,237,0.55);
      text-decoration: none; color: #fff;
    }}
    .steps-section {{ margin-bottom: 28px }}
    .step {{
      display: flex; align-items: flex-start; gap: 16px;
      padding: 16px 0; border-bottom: 1px solid rgba(255,255,255,0.05);
    }}
    .step:last-child {{ border-bottom: none }}
    .step-num {{
      width: 34px; height: 34px; flex-shrink: 0; border-radius: 10px;
      background: linear-gradient(135deg, var(--purple), #6d28d9);
      color: #fff; font-weight: 800; font-size: 15px;
      display: flex; align-items: center; justify-content: center;
      box-shadow: 0 0 16px rgba(124,58,237,0.5);
    }}
    .step-text b {{ font-size: 15px; font-weight: 700; display: block; margin-bottom: 3px }}
    .step-text small {{ font-size: 13px; color: var(--muted) }}
    .tg-card {{
      background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07);
      border-radius: 16px; padding: 18px; text-align: center;
      font-size: 14px; color: var(--muted);
    }}
    .tg-card a {{ color: var(--purple-light); font-weight: 600; text-decoration: none }}
    .tg-card a:hover {{ color: var(--cyan) }}
  </style>
</head>
<body>
  <nav>
    <a href="/" class="nav-logo">⚡ SWAGA</a>
    <div class="nav-links">
      <a href="/login">Войти</a>
      <a href="/register" class="nav-cta">Попробовать</a>
    </div>
  </nav>

  <div class="wrap">

    <!-- Hero -->
    <div class="hero">
      <div class="hero-badge">
        <span class="hero-badge-dot"></span>
        Работает в России прямо сейчас
      </div>
      <span class="hero-mascot">🐱</span>
      <h1><span class="grad">SWAGA VPN</span><br>стабильный и быстрый</h1>
      <p class="hero-sub">
        Зарегистрируйся, оплати и подключись<br>
        <b>прямо на сайте — без Telegram</b>
      </p>
      <a href="/register" class="btn-hero">🚀 Начать бесплатно — 7 дней</a>
      <div style="height:12px"></div>
      <a href="/login" class="btn-ghost">Уже есть аккаунт — Войти</a>
    </div>

    <!-- Features -->
    <p class="section-label">Почему SWAGA</p>
    <div class="feat-grid">
      <div class="feat-card">
        <span class="feat-icon">🔐</span>
        <div class="feat-title">Защита</div>
        <div class="feat-desc">VLESS-Reality — не блокируется</div>
      </div>
      <div class="feat-card">
        <span class="feat-icon">⚡</span>
        <div class="feat-title">Скорость</div>
        <div class="feat-desc">Серверы в Европе и США</div>
      </div>
      <div class="feat-card">
        <span class="feat-icon">🌍</span>
        <div class="feat-title">3 страны</div>
        <div class="feat-desc">FR · US · UK · 4 сервера</div>
      </div>
    </div>

    <!-- Stats -->
    <div class="info-row">
      <div class="info-card">
        <div class="info-val gp">3</div>
        <div class="info-lbl">устройства одновременно</div>
      </div>
      <div class="info-card">
        <div class="info-val gp">&lt;60мс</div>
        <div class="info-lbl">пинг до серверов</div>
      </div>
      <div class="info-card">
        <div class="info-val gp">0 логов</div>
        <div class="info-lbl">активность не хранится</div>
      </div>
      <div class="info-card">
        <div class="info-val gp">iOS/Android</div>
        <div class="info-lbl">Windows / Mac / Linux</div>
      </div>
    </div>

    <!-- Pricing -->
    <p class="pricing-title"><span class="grad">Тарифы</span></p>
    <div class="price-grid">
      <div class="price-card feat-t">
        <div class="price-name">Пробный</div>
        <div class="price-val"><span class="price-free">FREE</span></div>
        <div class="price-per">7 дней бесплатно</div>
        <span class="pbadge pb-green">Попробуй</span>
      </div>
      <div class="price-card">
        <div class="price-name">Месяц</div>
        <div class="price-val"><sup>₽</sup>130</div>
        <div class="price-per">в месяц</div>
        <span class="pbadge pb-cyan">Monthly</span>
      </div>
      <div class="price-card feat-p">
        <div class="price-name">3 месяца</div>
        <div class="price-val"><sup>₽</sup>350</div>
        <div class="price-per">~117 ₽/мес</div>
        <span class="pbadge pb-purple">Выгодно</span>
      </div>
      <div class="price-card">
        <div class="price-name">Год</div>
        <div class="price-val"><sup>₽</sup>900</div>
        <div class="price-per">~75 ₽/мес</div>
        <span class="pbadge pb-green">Yearly</span>
      </div>
    </div>
    <a href="/register" class="btn-price">🐱 Получить SWAGA — бесплатно</a>
    <div style="height:28px"></div>

    <!-- Steps -->
    <div class="steps-section">
      <p class="section-label">Как подключиться</p>
      <div class="step">
        <div class="step-num">1</div>
        <div class="step-text">
          <b>Создай аккаунт</b>
          <small>Только email и пароль — никакого Telegram</small>
        </div>
      </div>
      <div class="step">
        <div class="step-num">2</div>
        <div class="step-text">
          <b>Скачай приложение</b>
          <small>Happ Plus, Karing, V2RayTun (iOS) · Hiddify, Karing (Android)</small>
        </div>
      </div>
      <div class="step">
        <div class="step-num">3</div>
        <div class="step-text">
          <b>Подключись одной кнопкой</b>
          <small>Deeplink сам добавит все серверы в приложение</small>
        </div>
      </div>
    </div>

    <div class="tg-card">
      Также доступен Telegram-бот &nbsp;
      <a href="https://t.me/Swaga_vpnbot">🚀 @Swaga_vpnbot</a>
    </div>

  </div>
</body>
</html>"""
REGISTER_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <title>SWAGA VPN — Регистрация</title>
  {style}
</head>
<body>
  <nav class="nav">
    <a href="/" class="nav-logo" style="text-decoration:none">⚡ SWAGA VPN</a>
    <div class="nav-links">
      <a href="/login">Войти</a>
    </div>
  </nav>

  <div class="container">
    <div style="padding-top:24px"></div>
    <div class="card">
      <h2>Создать аккаунт</h2>
      <p class="sub">Получите <b>7 дней бесплатно</b> — никакой привязки к Telegram не нужно.</p>

      <div class="error-box" id="err"></div>

      <div class="input-group">
        <label>Email</label>
        <input type="email" id="email" placeholder="you@example.com" autocomplete="email">
      </div>
      <div class="input-group">
        <label>Пароль</label>
        <input type="password" id="pw" placeholder="Минимум 8 символов" autocomplete="new-password">
      </div>
      <div class="input-group">
        <label>Повторите пароль</label>
        <input type="password" id="pw2" placeholder="" autocomplete="new-password">
      </div>

      <button class="btn btn-primary" id="submit-btn" onclick="doRegister()">
        Создать аккаунт и получить доступ
      </button>
      <hr class="divider">
      <p class="text-center text-sm">Уже есть аккаунт? <a href="/login">Войти</a></p>
    </div>
  </div>

  <script>
    async function doRegister() {{
      const btn = document.getElementById('submit-btn');
      const err = document.getElementById('err');
      const email = document.getElementById('email').value.trim();
      const pw = document.getElementById('pw').value;
      const pw2 = document.getElementById('pw2').value;

      err.classList.remove('visible');
      if (!email) {{ err.textContent = 'Введите email'; err.classList.add('visible'); return; }}
      if (pw.length < 8) {{ err.textContent = 'Пароль должен быть не менее 8 символов'; err.classList.add('visible'); return; }}
      if (pw !== pw2) {{ err.textContent = 'Пароли не совпадают'; err.classList.add('visible'); return; }}

      btn.disabled = true;
      btn.textContent = 'Создаём аккаунт…';

      try {{
        const res = await fetch('/api/register', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{email, password: pw}})
        }});
        const data = await res.json();
        if (data.ok) {{
          window.location.href = data.redirect;
        }} else {{
          err.textContent = data.error || 'Ошибка регистрации';
          err.classList.add('visible');
          btn.disabled = false;
          btn.textContent = 'Создать аккаунт и получить доступ';
        }}
      }} catch(e) {{
        err.textContent = 'Ошибка сети, попробуйте ещё раз';
        err.classList.add('visible');
        btn.disabled = false;
        btn.textContent = 'Создать аккаунт и получить доступ';
      }}
    }}

    // Enter key
    document.addEventListener('keydown', e => {{
      if (e.key === 'Enter') doRegister();
    }});
  </script>
</body>
</html>"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <title>SWAGA VPN — Вход</title>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0 }}
    :root {{
      --purple: #7c3aed; --purple-light: #a78bfa;
      --cyan: #06b6d4; --bg: #07071a;
      --card-bg: rgba(255,255,255,0.04); --card-border: rgba(255,255,255,0.08);
      --text: #f1f5f9; --muted: #94a3b8;
    }}
    body {{
      background: var(--bg); color: var(--text);
      font-family: 'Inter', -apple-system, sans-serif;
      min-height: 100vh; overflow-x: hidden;
    }}
    body::before {{
      content: ''; position: fixed; inset: 0;
      background:
        radial-gradient(ellipse 70% 50% at 15% 5%, rgba(124,58,237,0.18) 0%, transparent 55%),
        radial-gradient(ellipse 50% 40% at 85% 95%, rgba(6,182,212,0.12) 0%, transparent 50%);
      pointer-events: none; z-index: 0;
    }}
    nav {{
      position: relative; z-index: 10;
      display: flex; align-items: center; justify-content: space-between;
      padding: 18px 24px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      backdrop-filter: blur(12px); background: rgba(7,7,26,0.7);
    }}
    .nav-logo {{
      font-size: 20px; font-weight: 900;
      background: linear-gradient(135deg, #fff 0%, var(--purple-light) 60%, var(--cyan) 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text; text-decoration: none;
    }}
    .nav-link {{
      color: var(--muted); font-size: 14px; font-weight: 500;
      text-decoration: none; padding: 8px 14px; border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.1); transition: all 0.2s;
    }}
    .nav-link:hover {{ color: #fff; border-color: rgba(255,255,255,0.25); text-decoration: none }}
    .wrap {{
      position: relative; z-index: 1;
      max-width: 420px; margin: 0 auto; padding: 40px 16px 60px;
    }}
    .card {{
      background: var(--card-bg); border: 1px solid var(--card-border);
      border-radius: 24px; padding: 30px 24px;
    }}
    .card-title {{
      font-size: 22px; font-weight: 800; margin-bottom: 6px;
      background: linear-gradient(135deg, #fff, var(--purple-light));
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .card-sub {{ font-size: 13px; color: var(--muted); margin-bottom: 22px; line-height: 1.5 }}
    .err-box {{
      background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.25);
      border-radius: 10px; padding: 11px 14px; color: #f87171;
      font-size: 13px; margin-bottom: 14px; display: none;
    }}
    .err-box.visible {{ display: block }}
    .tg-wrap {{ display: flex; justify-content: center; margin-bottom: 6px }}
    .or-divider {{
      display: flex; align-items: center; gap: 10px;
      margin: 18px 0; color: var(--muted); font-size: 12px;
    }}
    .or-divider::before, .or-divider::after {{
      content: ''; flex: 1; height: 1px;
      background: rgba(255,255,255,0.08);
    }}
    .field {{ margin-bottom: 14px }}
    .field label {{ display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; font-weight: 500 }}
    .field input {{
      width: 100%; background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 12px; padding: 13px 16px;
      color: var(--text); font-size: 15px; outline: none;
      transition: border-color 0.15s; font-family: inherit;
    }}
    .field input:focus {{ border-color: var(--purple) }}
    .btn-submit {{
      display: block; width: 100%; padding: 15px;
      border-radius: 12px; font-size: 16px; font-weight: 700;
      text-align: center; cursor: pointer; border: none; color: #fff;
      background: linear-gradient(135deg, var(--purple), #9333ea);
      box-shadow: 0 4px 20px rgba(124,58,237,0.4);
      transition: all 0.2s; font-family: inherit; margin-top: 4px;
    }}
    .btn-submit:hover {{ transform: translateY(-1px); box-shadow: 0 6px 28px rgba(124,58,237,0.55) }}
    .btn-submit:disabled {{ opacity: 0.4; cursor: not-allowed; transform: none }}
    .footer-link {{
      text-align: center; margin-top: 18px;
      font-size: 13px; color: var(--muted);
    }}
    .footer-link a {{ color: var(--purple-light); font-weight: 600; text-decoration: none }}
    .footer-link a:hover {{ color: var(--cyan) }}
  </style>
</head>
<body>
  <nav>
    <a href="/" class="nav-logo">⚡ SWAGA</a>
    <a href="/register" class="nav-link">Регистрация</a>
  </nav>

  <div class="wrap">
    <div class="card">
      <div class="card-title">Войти в аккаунт</div>
      <div class="card-sub">Пользователь бота? Войди через Telegram — подписка подтянется автоматически.</div>

      <div class="err-box" id="err"></div>

      <!-- Telegram Login Widget -->
      <div class="tg-wrap">
        <script async src="https://telegram.org/js/telegram-widget.js?22"
          data-telegram-login="{bot_username}"
          data-size="large"
          data-radius="10"
          data-onauth="onTelegramAuth(user)"
          data-request-access="write">
        </script>
      </div>

      <div class="or-divider">или войдите по email</div>

      <div class="field">
        <label>Email</label>
        <input type="email" id="email" placeholder="you@example.com" autocomplete="email">
      </div>
      <div class="field">
        <label>Пароль</label>
        <input type="password" id="pw" placeholder="••••••••" autocomplete="current-password">
      </div>

      <button class="btn-submit" id="submit-btn">Войти</button>

      <div class="footer-link">Нет аккаунта? <a href="/register">Зарегистрироваться</a></div>
    </div>
  </div>

  <script data-cfasync="false">
    async function onTelegramAuth(user) {{
      const err = document.getElementById('err');
      err.classList.remove('visible');
      try {{
        const res = await fetch('/api/login/telegram', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify(user)
        }});
        const data = await res.json();
        if (data.ok) {{ window.location.href = data.redirect; }}
        else {{ err.textContent = data.error || 'Ошибка входа через Telegram'; err.classList.add('visible'); }}
      }} catch(e) {{ err.textContent = 'Ошибка сети'; err.classList.add('visible'); }}
    }}

    async function doLogin() {{
      const btn = document.getElementById('submit-btn');
      const err = document.getElementById('err');
      const email = document.getElementById('email').value.trim();
      const pw = document.getElementById('pw').value;
      err.classList.remove('visible');
      if (!email || !pw) {{ err.textContent = 'Заполните все поля'; err.classList.add('visible'); return; }}
      btn.disabled = true; btn.textContent = 'Входим…';
      try {{
        const res = await fetch('/api/login', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{email, password: pw}})
        }});
        const data = await res.json();
        if (data.ok) {{ window.location.href = data.redirect; }}
        else {{
          err.textContent = data.error || 'Неверный email или пароль';
          err.classList.add('visible');
          btn.disabled = false; btn.textContent = 'Войти';
        }}
      }} catch(e) {{
        err.textContent = 'Ошибка сети'; err.classList.add('visible');
        btn.disabled = false; btn.textContent = 'Войти';
      }}
    }}

    document.getElementById('submit-btn').addEventListener('click', doLogin);
    document.addEventListener('keydown', e => {{ if (e.key === 'Enter') doLogin(); }});
    {autofill_msg}
  </script>
</body>
</html>"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <title>SWAGA VPN — Личный кабинет</title>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0 }}
    :root {{
      --purple: #7c3aed; --purple-light: #a78bfa;
      --cyan: #06b6d4; --green: #10b981;
      --bg: #07071a; --card-bg: rgba(255,255,255,0.04);
      --card-border: rgba(255,255,255,0.08);
      --text: #f1f5f9; --muted: #94a3b8;
    }}
    body {{
      background: var(--bg); color: var(--text);
      font-family: 'Inter', -apple-system, sans-serif;
      min-height: 100vh; overflow-x: hidden;
    }}
    body::before {{
      content: ''; position: fixed; inset: 0;
      background:
        radial-gradient(ellipse 70% 50% at 15% 5%, rgba(124,58,237,0.18) 0%, transparent 55%),
        radial-gradient(ellipse 50% 40% at 85% 95%, rgba(6,182,212,0.12) 0%, transparent 50%);
      pointer-events: none; z-index: 0;
    }}
    nav {{
      position: relative; z-index: 10;
      display: flex; align-items: center; justify-content: space-between;
      padding: 18px 24px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      backdrop-filter: blur(12px);
      background: rgba(7,7,26,0.7);
    }}
    .nav-logo {{
      font-size: 20px; font-weight: 900;
      background: linear-gradient(135deg, #fff 0%, var(--purple-light) 60%, var(--cyan) 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text; text-decoration: none;
    }}
    .nav-out {{
      color: var(--muted); font-size: 14px; font-weight: 500;
      text-decoration: none; padding: 8px 14px; border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.1);
      transition: all 0.2s;
    }}
    .nav-out:hover {{ color: #fff; border-color: rgba(255,255,255,0.25); text-decoration: none }}
    .wrap {{
      position: relative; z-index: 1;
      max-width: 480px; margin: 0 auto; padding: 24px 16px 60px;
    }}

    /* ── Cards ── */
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      padding: 22px 20px;
      margin-bottom: 14px;
    }}
    .card-label {{
      font-size: 11px; text-transform: uppercase;
      letter-spacing: 0.12em; color: var(--muted); margin-bottom: 12px;
    }}

    /* ── Account card ── */
    .acct-row {{
      display: flex; align-items: center; gap: 12px;
    }}
    .acct-avatar {{
      width: 42px; height: 42px; border-radius: 12px; flex-shrink: 0;
      background: linear-gradient(135deg, var(--purple), #9333ea);
      display: flex; align-items: center; justify-content: center;
      font-size: 20px;
      box-shadow: 0 0 16px rgba(124,58,237,0.4);
    }}
    .acct-name {{ font-size: 16px; font-weight: 700; color: #fff; word-break: break-all }}
    .acct-sub {{ font-size: 12px; color: var(--muted); margin-top: 2px }}

    /* ── Status card ── */
    .status-card {{
      border-radius: 20px; padding: 20px;
      margin-bottom: 14px;
      display: flex; align-items: center; gap: 16px;
    }}
    .status-card.active {{
      background: linear-gradient(135deg, rgba(16,185,129,0.12), rgba(6,182,212,0.07));
      border: 1px solid rgba(16,185,129,0.3);
    }}
    .status-card.warn {{
      background: linear-gradient(135deg, rgba(245,158,11,0.12), rgba(239,68,68,0.07));
      border: 1px solid rgba(245,158,11,0.3);
    }}
    .status-card.expired {{
      background: rgba(239,68,68,0.07);
      border: 1px solid rgba(239,68,68,0.25);
    }}
    .status-card.none {{
      background: var(--card-bg); border: 1px solid var(--card-border);
      justify-content: center; text-align: center;
    }}
    .status-icon {{ font-size: 34px; flex-shrink: 0; line-height: 1 }}
    .status-lbl {{ font-size: 12px; color: var(--muted); margin-bottom: 3px }}
    .status-val {{ font-size: 18px; font-weight: 800 }}
    .status-val.green {{ color: #34d399 }}
    .status-val.yellow {{ color: #fbbf24 }}
    .status-val.red {{ color: #f87171 }}
    .status-until {{ font-size: 12px; color: var(--muted); margin-top: 3px }}

    /* ── Connect button ── */
    .btn-connect {{
      display: flex; align-items: center; justify-content: center; gap: 10px;
      width: 100%; padding: 16px; border-radius: 14px; margin-bottom: 14px;
      font-size: 16px; font-weight: 700; text-decoration: none; color: #fff;
      background: linear-gradient(135deg, var(--purple), #9333ea, var(--cyan));
      background-size: 200% 200%;
      box-shadow: 0 4px 24px rgba(124,58,237,0.45);
      transition: all 0.2s;
      animation: gradshift 4s ease infinite;
    }}
    @keyframes gradshift {{
      0% {{ background-position: 0% 50% }}
      50% {{ background-position: 100% 50% }}
      100% {{ background-position: 0% 50% }}
    }}
    .btn-connect:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 32px rgba(124,58,237,0.6);
      text-decoration: none; color: #fff;
    }}

    /* ── Pay plans ── */
    .pay-grid {{
      display: grid; grid-template-columns: repeat(3, 1fr);
      gap: 10px; margin-bottom: 14px;
    }}
    .pay-plan {{
      background: rgba(255,255,255,0.03);
      border: 2px solid rgba(255,255,255,0.07);
      border-radius: 16px; padding: 16px 10px;
      text-align: center; cursor: pointer; position: relative;
      transition: border-color 0.15s, background 0.15s, transform 0.1s;
      user-select: none;
    }}
    .pay-plan:hover {{ border-color: rgba(124,58,237,0.5); transform: translateY(-2px) }}
    .pay-plan.selected {{
      border-color: var(--purple);
      background: rgba(124,58,237,0.12);
      box-shadow: 0 0 20px rgba(124,58,237,0.2);
    }}
    .pay-plan.selected .pay-plan-price {{ color: var(--purple-light) }}
    .pay-check {{
      position: absolute; top: 7px; right: 8px;
      width: 16px; height: 16px; border-radius: 50%;
      background: var(--purple); color: #fff;
      font-size: 10px; font-weight: 700;
      display: none; align-items: center; justify-content: center;
      box-shadow: 0 0 8px rgba(124,58,237,0.6);
    }}
    .pay-plan.selected .pay-check {{ display: flex }}
    .pay-plan-name {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px }}
    .pay-plan-price {{ font-size: 20px; font-weight: 800; color: #fff; transition: color 0.15s }}
    .pay-plan-price span {{ font-size: 11px; color: var(--muted); font-weight: 400 }}
    .pay-plan-hint {{ font-size: 10px; color: #34d399; margin-top: 4px }}
    .pay-btn {{
      display: block; width: 100%;
      padding: 15px; border-radius: 12px;
      font-size: 16px; font-weight: 700; text-align: center;
      cursor: pointer; border: none; color: #fff;
      background: linear-gradient(135deg, var(--purple), #9333ea);
      box-shadow: 0 4px 20px rgba(124,58,237,0.4);
      transition: all 0.2s;
    }}
    .pay-btn:hover {{ transform: translateY(-1px); box-shadow: 0 6px 28px rgba(124,58,237,0.55) }}
    .pay-btn:disabled {{ opacity: 0.4; cursor: not-allowed; transform: none; box-shadow: none }}
    .pay-error {{
      background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.25);
      border-radius: 10px; padding: 10px 14px; color: #f87171;
      font-size: 13px; margin-bottom: 12px; display: none;
    }}
    .pay-error.visible {{ display: block }}
    .section-label {{
      font-size: 11px; text-transform: uppercase;
      letter-spacing: 0.12em; color: var(--muted); margin-bottom: 14px;
    }}

    /* ── Success banner ── */
    .paid-banner {{
      background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(6,182,212,0.08));
      border: 1px solid rgba(16,185,129,0.35);
      border-radius: 14px; padding: 14px 16px; margin-bottom: 14px;
      font-size: 14px; color: #34d399; font-weight: 600; text-align: center;
    }}
  </style>
</head>
<body>
  <nav>
    <a href="/" class="nav-logo">⚡ SWAGA</a>
    <a href="/logout" class="nav-out">Выйти</a>
  </nav>

  <div class="wrap">

    {paid_banner}

    <!-- Аккаунт -->
    <div class="card">
      <div class="card-label">Аккаунт</div>
      <div class="acct-row">
        <div class="acct-avatar">👤</div>
        <div>
          <div class="acct-name">{email_safe}</div>
          <div class="acct-sub">SWAGA VPN</div>
        </div>
      </div>
    </div>

    <!-- Статус подписки -->
    {sub_block}

    <!-- Кнопка подключения -->
    {action_block}

    <!-- Оплата -->
    <div class="card" id="pay-section">
      <div class="section-label">{pay_title}</div>
      <div class="pay-error" id="pay-err"></div>
      <div class="pay-grid">
        <div class="pay-plan" data-plan="1m" data-price="130" data-label="1 месяц">
          <div class="pay-check">✓</div>
          <div class="pay-plan-name">1 мес</div>
          <div class="pay-plan-price">130 <span>₽</span></div>
        </div>
        <div class="pay-plan" data-plan="3m" data-price="350" data-label="3 месяца">
          <div class="pay-check">✓</div>
          <div class="pay-plan-name">3 мес</div>
          <div class="pay-plan-price">350 <span>₽</span></div>
          <div class="pay-plan-hint">~117₽/мес</div>
        </div>
        <div class="pay-plan" data-plan="1y" data-price="900" data-label="1 год">
          <div class="pay-check">✓</div>
          <div class="pay-plan-name">1 год</div>
          <div class="pay-plan-price">900 <span>₽</span></div>
          <div class="pay-plan-hint">~75₽/мес</div>
        </div>
      </div>
      <button class="pay-btn" id="pay-btn" onclick="doPay()">Оплатить 130 ₽</button>
    </div>

  </div>

  <script data-cfasync="false">
    let selectedPlan = null;

    function selectPlan(el) {{
      document.querySelectorAll('.pay-plan').forEach(p => p.classList.remove('selected'));
      el.classList.add('selected');
      selectedPlan = {{ key: el.dataset.plan, price: el.dataset.price, label: el.dataset.label }};
      document.getElementById('pay-btn').textContent = 'Оплатить ' + selectedPlan.price + ' ₽';
    }}

    // Назначаем обработчики напрямую — не через onclick в HTML
    document.addEventListener('DOMContentLoaded', function() {{
      document.querySelectorAll('.pay-plan').forEach(function(el) {{
        el.addEventListener('click', function() {{ selectPlan(el); }});
      }});
      var first = document.querySelector('.pay-plan');
      if (first) selectPlan(first);
    }});

    async function doPay() {{
      if (!selectedPlan) return;
      const btn = document.getElementById('pay-btn');
      const err = document.getElementById('pay-err');
      err.classList.remove('visible');
      btn.disabled = true;
      btn.textContent = 'Создаём платёж…';
      try {{
        const res = await fetch('/api/pay', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{ plan_key: selectedPlan.key }})
        }});
        const data = await res.json();
        if (data.ok) {{
          window.location.href = data.pay_url;
        }} else {{
          err.textContent = data.error || 'Ошибка при создании платежа';
          err.classList.add('visible');
          btn.disabled = false;
          btn.textContent = 'Оплатить ' + selectedPlan.price + ' ₽';
        }}
      }} catch(e) {{
        err.textContent = 'Ошибка сети, попробуйте ещё раз';
        err.classList.add('visible');
        btn.disabled = false;
        btn.textContent = 'Оплатить ' + selectedPlan.price + ' ₽';
      }}
    }}
  </script>
</body>
</html>"""
# ── Admin panel HTML ──────────────────────────────────────────────────────────

ADMIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <title>SWAGA — Админ</title>
  {style}
  <style>
    .admin-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 18px;
    }}
    .admin-header h2 {{ margin: 0; font-size: 20px }}
    .badge-count {{
      background: rgba(35,134,54,0.18);
      border: 1px solid rgba(35,134,54,0.35);
      border-radius: 100px;
      color: #3fb950;
      font-size: 12px;
      font-weight: 600;
      padding: 3px 12px;
    }}
    .search-row {{
      margin-bottom: 16px;
    }}
    .search-row input {{
      width: 100%;
      background: #0d1117;
      border: 1px solid #30363d;
      border-radius: 10px;
      padding: 10px 14px;
      color: #e6edf3;
      font-size: 14px;
      outline: none;
    }}
    .search-row input:focus {{ border-color: #58a6ff }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th {{
      text-align: left;
      color: #6e7681;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      padding: 0 8px 10px;
      border-bottom: 1px solid #21262d;
    }}
    td {{
      padding: 10px 8px;
      border-bottom: 1px solid #161b22;
      color: #c9d1d9;
      vertical-align: middle;
    }}
    tr:last-child td {{ border-bottom: none }}
    tr:hover td {{ background: rgba(255,255,255,0.02) }}
    .status-active {{
      display: inline-block;
      background: rgba(35,134,54,0.18);
      border: 1px solid rgba(35,134,54,0.35);
      color: #3fb950;
      border-radius: 6px;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 600;
    }}
    .status-expired {{
      display: inline-block;
      background: rgba(244,63,94,0.1);
      border: 1px solid rgba(244,63,94,0.25);
      color: #f44336;
      border-radius: 6px;
      padding: 2px 8px;
      font-size: 11px;
    }}
    .status-none {{
      display: inline-block;
      color: #6e7681;
      font-size: 11px;
    }}
    .plan-tag {{
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 5px;
      padding: 1px 6px;
      font-size: 11px;
      color: #8b949e;
    }}
    .days-num {{ font-weight: 700; color: #e6edf3 }}
    .days-warn {{ font-weight: 700; color: #f0883e }}
    .days-over {{ color: #6e7681 }}
    .connect-link {{ color: #58a6ff; font-size: 12px }}

    /* ── keygen section ── */
    .kg-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      margin-bottom: 14px;
    }}
    .kg-btn {{
      background: #0d1117;
      border: 2px solid #21262d;
      border-radius: 12px;
      padding: 12px 8px;
      text-align: center;
      cursor: pointer;
      transition: border-color 0.12s, background 0.12s;
      font-size: 13px;
      color: #c9d1d9;
      font-weight: 600;
    }}
    .kg-btn:hover {{ border-color: #388bfd }}
    .kg-btn.kg-selected {{
      border-color: #238636;
      background: rgba(35,134,54,0.1);
      color: #3fb950;
    }}
    .kg-sub {{ font-size: 10px; color: #6e7681; margin-top: 2px }}
    .kg-action {{
      display: block; width: 100%;
      padding: 12px; border-radius: 10px;
      background: linear-gradient(135deg, #238636, #0ea271);
      box-shadow: 0 3px 14px rgba(35,134,54,0.3);
      color: #fff; font-size: 15px; font-weight: 700;
      cursor: pointer; border: none; transition: opacity 0.15s;
    }}
    .kg-action:hover {{ opacity: 0.88 }}
    .kg-action:disabled {{ opacity: 0.4; cursor: not-allowed }}
    .kg-result {{
      margin-top: 14px;
      background: rgba(35,134,54,0.07);
      border: 1px solid rgba(35,134,54,0.25);
      border-radius: 12px;
      padding: 14px 16px;
      display: none;
    }}
    .kg-result.visible {{ display: block }}
    .kg-result-title {{ font-size: 13px; font-weight: 700; color: #3fb950; margin-bottom: 10px }}
    .kg-link-label {{ font-size: 11px; color: #6e7681; margin-bottom: 3px }}
    .kg-link-row {{
      display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
    }}
    .kg-link-val {{
      flex: 1; background: #0d1117; border: 1px solid #30363d;
      border-radius: 8px; padding: 8px 10px;
      font-size: 12px; color: #58a6ff; word-break: break-all;
      font-family: monospace;
    }}
    .kg-copy {{
      background: #21262d; border: 1px solid #30363d;
      border-radius: 8px; padding: 7px 12px;
      color: #8b949e; font-size: 12px; cursor: pointer;
      white-space: nowrap; transition: color 0.1s;
    }}
    .kg-copy:hover {{ color: #e6edf3 }}
    .kg-err {{ color: #f44336; font-size: 13px; margin-top: 10px; display: none }}
    .kg-err.visible {{ display: block }}
  </style>
</head>
<body>
  <nav class="nav">
    <a href="/" style="text-decoration:none" class="nav-logo">⚡ SWAGA VPN</a>
    <div class="nav-links" style="font-size:12px;color:#6e7681">🔒 Admin</div>
  </nav>

  <div class="container" style="max-width:900px">
    <div style="padding-top:20px"></div>

    <!-- Keygen -->
    <div class="card">
      <div class="admin-header" style="margin-bottom:14px">
        <h2>🔑 Создать ключ</h2>
      </div>
      <div class="kg-grid">
        <div class="kg-btn kg-selected" data-days="7" onclick="kgSelect(this)">
          7 дней<div class="kg-sub">trial</div>
        </div>
        <div class="kg-btn" data-days="30" onclick="kgSelect(this)">
          1 месяц<div class="kg-sub">30 дн.</div>
        </div>
        <div class="kg-btn" data-days="90" onclick="kgSelect(this)">
          3 месяца<div class="kg-sub">90 дн.</div>
        </div>
        <div class="kg-btn" data-days="365" onclick="kgSelect(this)">
          1 год<div class="kg-sub">365 дн.</div>
        </div>
      </div>
      <button class="kg-action" id="kg-go" onclick="kgCreate()">Создать ключ на 7 дней</button>
      <div class="kg-err" id="kg-err"></div>
      <div class="kg-result" id="kg-result">
        <div class="kg-result-title" id="kg-result-title"></div>
        <div class="kg-link-label">Страница подключения</div>
        <div class="kg-link-row">
          <div class="kg-link-val" id="kg-connect"></div>
          <button class="kg-copy" onclick="kgCopy('kg-connect', this)">Копировать</button>
        </div>
        <div class="kg-link-label">Ссылка на подписку (sub)</div>
        <div class="kg-link-row">
          <div class="kg-link-val" id="kg-sub"></div>
          <button class="kg-copy" onclick="kgCopy('kg-sub', this)">Копировать</button>
        </div>
      </div>
    </div>

    <!-- Users table -->
    <div class="card">
      <div class="admin-header">
        <h2>Web-пользователи</h2>
        <span class="badge-count">{total} чел.</span>
      </div>
      <div class="search-row">
        <input type="text" id="search" placeholder="Поиск по email…" oninput="filterTable()">
      </div>
      <div style="overflow-x:auto">
        <table id="users-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Email</th>
              <th>Зарегистрирован</th>
              <th>Тариф</th>
              <th>Статус</th>
              <th>Осталось</th>
              <th>До</th>
              <th>Сервер</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    const ADMIN_TOKEN = {admin_token};
    let kgDays = 7;

    function kgSelect(el) {{
      document.querySelectorAll('.kg-btn').forEach(b => b.classList.remove('kg-selected'));
      el.classList.add('kg-selected');
      kgDays = parseInt(el.dataset.days);
      const label = el.firstChild.textContent.trim();
      document.getElementById('kg-go').textContent = 'Создать ключ на ' + label;
      document.getElementById('kg-result').classList.remove('visible');
      document.getElementById('kg-err').classList.remove('visible');
    }}

    async function kgCreate() {{
      const btn = document.getElementById('kg-go');
      const err = document.getElementById('kg-err');
      err.classList.remove('visible');
      document.getElementById('kg-result').classList.remove('visible');
      btn.disabled = true;
      btn.textContent = 'Создаём…';

      try {{
        const res = await fetch('/api/admin/keygen', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{ token: ADMIN_TOKEN, days: kgDays }})
        }});
        const data = await res.json();
        if (data.ok) {{
          document.getElementById('kg-result-title').textContent =
            '✅ Ключ создан — действует до ' + data.end_display;
          document.getElementById('kg-connect').textContent = data.connect_url;
          document.getElementById('kg-sub').textContent = data.sub_url;
          document.getElementById('kg-result').classList.add('visible');
        }} else {{
          err.textContent = data.error || 'Ошибка создания ключа';
          err.classList.add('visible');
        }}
      }} catch(e) {{
        err.textContent = 'Ошибка сети';
        err.classList.add('visible');
      }}

      const label = document.querySelector('.kg-btn.kg-selected').firstChild.textContent.trim();
      btn.disabled = false;
      btn.textContent = 'Создать ключ на ' + label;
    }}

    function kgCopy(id, btn) {{
      const text = document.getElementById(id).textContent;
      navigator.clipboard.writeText(text).then(() => {{
        const orig = btn.textContent;
        btn.textContent = '✓ Скопировано';
        setTimeout(() => btn.textContent = orig, 1500);
      }});
    }}

    function filterTable() {{
      const q = document.getElementById('search').value.toLowerCase();
      document.querySelectorAll('#users-table tbody tr').forEach(tr => {{
        tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
      }});
    }}
  </script>
</body>
</html>"""


# ── Маршруты ──────────────────────────────────────────────────────────────────

routes = web.RouteTableDef()


@routes.get("/")
async def handle_landing(request: web.Request) -> web.Response:
    html = LANDING_HTML.format(style=_BASE_STYLE)
    return web.Response(text=html, content_type="text/html")


@routes.post("/api/admin/keygen")
async def handle_admin_keygen(request: web.Request) -> web.Response:
    """Создать гивей-ключ через admin-панель. Защищён токеном в теле запроса."""
    if not WEB_ADMIN_TOKEN:
        return web.json_response({"ok": False, "error": "Admin token not configured"}, status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Bad request"}, status=400)

    token = body.get("token", "")
    if not hmac.compare_digest(token, WEB_ADMIN_TOKEN):
        return web.json_response({"ok": False, "error": "Неверный токен"}, status=403)

    days = body.get("days")
    if days not in (7, 30, 90, 365):
        return web.json_response({"ok": False, "error": "Допустимые значения: 7, 30, 90, 365"})

    logger.info("Admin keygen: days=%s", days)
    result = await provision_giveaway_key(days)
    if result.get("error"):
        return web.json_response({"ok": False, "error": result["error"]})

    return web.json_response({"ok": True, **result})


@routes.get("/admin")
async def handle_admin(request: web.Request) -> web.Response:
    """Admin-панель со списком всех web-пользователей. Защищена токеном ?token=..."""
    if not WEB_ADMIN_TOKEN:
        raise web.HTTPForbidden(reason="Admin token not configured")
    token = request.rel_url.query.get("token", "")
    if not hmac.compare_digest(token, WEB_ADMIN_TOKEN):
        raise web.HTTPForbidden(reason="Invalid token")

    users = await get_all_web_users_with_subs()

    rows_html = []
    for u in users:
        email = _h(u["email"] or "")
        reg = _h((u["created_at"] or "")[:10])
        plan = _h(u.get("plan") or "")
        end_date_str = u.get("end_date") or ""
        sub_id = _h(u.get("sub_id") or "")
        server = _h(u.get("server_id") or "—")

        if plan and end_date_str:
            try:
                end_dt = datetime.fromisoformat(end_date_str)
                days_left = (end_dt - datetime.utcnow()).days
            except ValueError:
                days_left = None

            if days_left is not None and days_left > 3:
                status_html = '<span class="status-active">активна</span>'
                days_html = f'<span class="days-num">{days_left} дн.</span>'
            elif days_left is not None and days_left >= 0:
                status_html = '<span class="status-active">активна</span>'
                days_html = f'<span class="days-warn">{days_left} дн.</span>'
            else:
                status_html = '<span class="status-expired">истекла</span>'
                days_html = '<span class="days-over">—</span>'

            end_display = end_date_str[:10]
            plan_html = f'<span class="plan-tag">{plan}</span>'
        else:
            status_html = '<span class="status-none">нет</span>'
            days_html = '<span class="days-over">—</span>'
            end_display = "—"
            plan_html = "—"

        connect_html = (
            f'<a href="/connect/{sub_id}" class="connect-link" target="_blank">→ connect</a>'
            if sub_id else "—"
        )

        rows_html.append(
            f"<tr>"
            f"<td>{u['id']}</td>"
            f"<td>{email}</td>"
            f"<td>{reg}</td>"
            f"<td>{plan_html}</td>"
            f"<td>{status_html}</td>"
            f"<td>{days_html}</td>"
            f"<td>{end_display}</td>"
            f"<td>{server}</td>"
            f"<td>{connect_html}</td>"
            f"</tr>"
        )

    html = ADMIN_HTML.format(
        style=_BASE_STYLE,
        total=len(users),
        rows="\n".join(rows_html),
        admin_token=json.dumps(WEB_ADMIN_TOKEN),
    )
    return web.Response(text=html, content_type="text/html")


@routes.get("/register")
async def handle_register_page(request: web.Request) -> web.Response:
    # Уже залогинен — в кабинет
    if get_session_user_id(request):
        raise web.HTTPFound("/dashboard")
    html = REGISTER_HTML.format(style=_BASE_STYLE)
    return web.Response(text=html, content_type="text/html")


@routes.post("/api/register")
async def handle_register_api(request: web.Request) -> web.Response:
    # Rate limit: 5 регистраций в час с одного IP
    ip = _client_ip(request)
    if not _rate_limit_ok(ip, "register", max_hits=5, window_secs=3600):
        return web.json_response(
            {"ok": False, "error": "Слишком много попыток. Попробуйте через час."},
            status=429,
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Неверный формат запроса"}, status=400)

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    # Валидация
    if len(email) > 254 or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return web.json_response({"ok": False, "error": "Неверный формат email"})
    if len(password) < 8:
        return web.json_response({"ok": False, "error": "Пароль должен быть не менее 8 символов"})
    if len(password) > 128:
        return web.json_response({"ok": False, "error": "Пароль не должен превышать 128 символов"})

    # Проверяем дубликат
    existing = await get_web_user_by_email(email)
    if existing:
        return web.json_response({"ok": False, "error": "Аккаунт с таким email уже существует"})

    # Создаём web_user и синтетического users-пользователя
    pw_hash = hash_password(password)
    web_user_id, synthetic_uid = await create_web_user(email, pw_hash)

    # Создаём VPN-подписку
    sub_id, error = await provision_trial(synthetic_uid)
    if error:
        logger.error("provision_trial failed for web_user %s: %s", web_user_id, error)
        # Всё равно пускаем пользователя, просто без подписки
    else:
        await set_web_user_sub_id(web_user_id, sub_id)

    # Выдаём session cookie
    # Используем относительный путь, чтобы /connect/ работал на том же домене
    # (nginx проксирует /connect/ → sub_app.py:8888)
    if sub_id:
        redirect = f"/connect/{sub_id}"
    else:
        redirect = "/dashboard"

    resp = web.json_response({"ok": True, "redirect": redirect})
    set_session_cookie(resp, web_user_id)
    return resp


@routes.get("/login")
async def handle_login_page(request: web.Request) -> web.Response:
    if get_session_user_id(request):
        raise web.HTTPFound("/dashboard")
    msg = request.rel_url.query.get("msg", "")
    autofill_msg = ""
    if msg == "registered":
        autofill_msg = "// show success note (handled by server redirect to /connect directly)"
    html = LOGIN_HTML.format(
        style=_BASE_STYLE,
        autofill_msg=autofill_msg,
        bot_username=BOT_USERNAME,
    )
    return web.Response(text=html, content_type="text/html")


@routes.post("/api/login")
async def handle_login_api(request: web.Request) -> web.Response:
    # Rate limit: 10 попыток в минуту с одного IP (защита от брутфорса)
    ip = _client_ip(request)
    if not _rate_limit_ok(ip, "login", max_hits=10, window_secs=60):
        return web.json_response(
            {"ok": False, "error": "Слишком много попыток входа. Подождите минуту."},
            status=429,
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Неверный формат запроса"}, status=400)

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return web.json_response({"ok": False, "error": "Заполните все поля"})
    if len(email) > 254 or len(password) > 128:
        return web.json_response({"ok": False, "error": "Неверный email или пароль"})

    web_user = await get_web_user_by_email(email)
    if not web_user or not verify_password(password, web_user["password_hash"]):
        return web.json_response({"ok": False, "error": "Неверный email или пароль"})

    resp = web.json_response({"ok": True, "redirect": "/dashboard"})
    set_session_cookie(resp, web_user["id"])
    return resp


@routes.post("/api/login/telegram")
async def handle_login_telegram(request: web.Request) -> web.Response:
    """Вход через Telegram Login Widget. Верифицирует подпись, создаёт/находит web_user."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Неверный формат запроса"}, status=400)

    if not verify_telegram_auth_data(data):
        return web.json_response({"ok": False, "error": "Неверная подпись Telegram"}, status=403)

    tg_user_id = int(data.get("id", 0))
    if not tg_user_id:
        return web.json_response({"ok": False, "error": "Нет user_id"}, status=400)

    # Формируем display_name из данных виджета
    first = data.get("first_name", "")
    last = data.get("last_name", "")
    username = data.get("username", "")
    if first or last:
        display_name = f"{first} {last}".strip()
        if username:
            display_name += f" (@{username})"
    elif username:
        display_name = f"@{username}"
    else:
        display_name = f"Telegram {tg_user_id}"

    # Ищем или создаём web_user
    web_user = await get_web_user_by_telegram_id(tg_user_id)
    if web_user:
        web_user_id = web_user["id"]
        # Обновляем display_name через create (внутри делает UPDATE)
        await create_web_user_from_telegram(tg_user_id, display_name)
    else:
        web_user_id = await create_web_user_from_telegram(tg_user_id, display_name)
        if not web_user_id:
            return web.json_response({"ok": False, "error": "Ошибка создания аккаунта"})

        # Для нового TG-пользователя создаём trial если у него нет подписки в боте
        web_user = await get_web_user_by_id(web_user_id)
        if web_user:
            from database import get_active_sub
            existing_sub = await get_active_sub(tg_user_id)
            if not existing_sub:
                # Нет активной подписки — даём trial
                sub_id_val, err = await provision_trial(tg_user_id)
                if sub_id_val:
                    await set_web_user_sub_id(web_user_id, sub_id_val)
            else:
                # Уже есть подписка в боте — просто сохраняем sub_id
                if not web_user.get("sub_id") and existing_sub.get("xui_sub_id"):
                    await set_web_user_sub_id(web_user_id, existing_sub["xui_sub_id"])

    resp = web.json_response({"ok": True, "redirect": "/dashboard"})
    set_session_cookie(resp, web_user_id)
    return resp


@routes.get("/dashboard")
async def handle_dashboard(request: web.Request) -> web.Response:
    web_user_id = get_session_user_id(request)
    if not web_user_id:
        raise web.HTTPFound("/login")

    web_user = await get_web_user_by_id(web_user_id)
    if not web_user:
        raise web.HTTPFound("/login")

    email = web_user["email"]
    sub_id = web_user.get("sub_id")

    # Определяем отображаемое имя: для Telegram-пользователей — display_name вместо placeholder email
    display_name = web_user.get("display_name")
    if display_name:
        display_identity = display_name
    elif email.endswith("@telegram.auth"):
        tg_id = web_user.get("telegram_user_id") or web_user.get("user_id", "")
        display_identity = f"Telegram ID {tg_id}"
    else:
        display_identity = email

    # Получаем активную подписку
    from database import get_active_sub
    sub = await get_active_sub(web_user["user_id"])

    if sub:
        try:
            end_dt = datetime.fromisoformat(sub["end_date"])
            days_left = max((end_dt - datetime.utcnow()).days, 0)
            end_display = end_dt.strftime("%d.%m.%Y")
        except Exception:
            days_left = 0
            end_display = "—"

        is_active = bool(sub.get("is_active"))

        if not is_active:
            css_cls, val_cls, status_text = "expired", "red", "Подписка неактивна"
        elif days_left == 0:
            css_cls, val_cls, status_text = "warn", "yellow", "Истекает сегодня"
        elif days_left <= 3:
            css_cls, val_cls, status_text = "warn", "yellow", f"Осталось {days_left} дн."
        else:
            css_cls, val_cls, status_text = "active", "green", f"Осталось {days_left} дн."

        sub_block = f"""
        <div class="status-card {css_cls}">
          <div class="status-icon">{'🟢' if css_cls == 'active' else ('🟡' if css_cls == 'warn' else '🔴')}</div>
          <div>
            <div class="status-lbl">Подписка активна</div>
            <div class="status-val {val_cls}">{status_text}</div>
            <div class="status-until">до {end_display}</div>
          </div>
        </div>"""

        xui_sub_id = sub.get("xui_sub_id") or sub_id
        if xui_sub_id:
            action_block = f'<a href="/connect/{xui_sub_id}" class="btn-connect">⚡ Открыть страницу подключения</a>'
        else:
            action_block = ""
        pay_title = "Продлить подписку"
    else:
        sub_block = """
        <div class="status-card none">
          <div>
            <div style="font-size:32px;margin-bottom:8px">😔</div>
            <div style="font-size:15px;color:#94a3b8">Активная подписка не найдена</div>
          </div>
        </div>"""
        action_block = ""
        pay_title = "Купить подписку"

    paid_banner = ""
    if request.rel_url.query.get("paid") == "1":
        paid_banner = '<div class="paid-banner">✅ Оплата прошла успешно — подписка активирована!</div>'

    html = DASHBOARD_HTML.format(
        email_safe=_h(display_identity),
        sub_block=sub_block,
        action_block=action_block,
        pay_title=pay_title,
        paid_banner=paid_banner,
    )
    return web.Response(text=html, content_type="text/html")


@routes.post("/api/pay")
async def handle_api_pay(request: web.Request) -> web.Response:
    """Создать платёж YooKassa для web-пользователя."""
    web_user_id = get_session_user_id(request)
    if not web_user_id:
        return web.json_response({"ok": False, "error": "Не авторизован"}, status=401)

    web_user = await get_web_user_by_id(web_user_id)
    if not web_user:
        return web.json_response({"ok": False, "error": "Пользователь не найден"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Неверный запрос"}, status=400)

    plan_key = (body.get("plan_key") or "").strip()
    plan = PLANS.get(plan_key)
    if not plan or plan["price"] <= 0:
        return web.json_response({"ok": False, "error": "Неверный тариф"})

    synthetic_uid = web_user.get("user_id")
    if not synthetic_uid:
        return web.json_response({"ok": False, "error": "Ошибка аккаунта, обратитесь в поддержку"})

    # Создаём платёж в YooKassa в thread executor (синхронная библиотека)
    from yookassa_payment import create_payment as yookassa_create_payment
    loop = asyncio.get_event_loop()
    try:
        payment_result = await loop.run_in_executor(
            None,
            lambda: yookassa_create_payment(
                amount=plan["price"],
                user_id=synthetic_uid,
                plan_key=plan_key,
                server_id="",
                description=f"SWAGA VPN — {plan['name']}",
                return_url="https://swaga-vpn.ru/dashboard?paid=1",
            )
        )
    except Exception as e:
        logger.error("YooKassa create_payment error: %s", e)
        return web.json_response({"ok": False, "error": "Ошибка платёжного сервиса, попробуйте позже"})

    if not payment_result:
        return web.json_response({"ok": False, "error": "Не удалось создать платёж, попробуйте позже"})

    # Сохраняем платёж в БД
    await db_create_payment(
        payment_id=payment_result["payment_id"],
        user_id=synthetic_uid,
        amount=plan["price"],
        plan_key=plan_key,
        server_id="",
    )

    logger.info(
        "Web pay: web_user=%s synthetic_uid=%s plan=%s amount=%s payment_id=%s",
        web_user_id, synthetic_uid, plan_key, plan["price"], payment_result["payment_id"],
    )

    return web.json_response({"ok": True, "pay_url": payment_result["confirmation_url"]})


@routes.get("/logout")
async def handle_logout(request: web.Request) -> web.Response:
    resp = web.HTTPFound("/")
    resp.del_cookie(COOKIE_NAME)
    return resp


@routes.get("/admin/metrics")
async def handle_admin_metrics(request: web.Request) -> web.Response:
    """Metrics dashboard — same auth as /admin."""
    _require_admin_token(request)
    try:
        m = await _get_dashboard_metrics()
    except Exception as exc:
        logger.error("Metrics dashboard error: %s", exc)
        return web.Response(
            text=f"<h1>Error computing metrics</h1><pre>{_h(str(exc))}</pre>",
            content_type="text/html",
            status=500,
        )
    token = request.rel_url.query.get("token", "")
    html = _render_metrics_dashboard(m, token)
    return web.Response(text=html, content_type="text/html")


@routes.get("/api/admin/metrics")
async def handle_api_admin_metrics(request: web.Request) -> web.Response:
    """Return full metrics as JSON."""
    _require_admin_token(request)
    try:
        m = await _get_dashboard_metrics()
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)
    return web.json_response({"ok": True, "data": m})


@routes.get("/api/admin/metrics/simulate")
async def handle_api_admin_metrics_simulate(request: web.Request) -> web.Response:
    """Pricing simulator AJAX endpoint. Query params: p1m, p3m, p1y (prices in rubles)."""
    _require_admin_token(request)
    try:
        p1m = float(request.rel_url.query.get("p1m", "") or "0")
        p3m = float(request.rel_url.query.get("p3m", "") or "0")
        p1y = float(request.rel_url.query.get("p1y", "") or "0")
    except ValueError:
        return web.json_response({"ok": False, "error": "Invalid price values"}, status=400)
    if p1m <= 0 or p3m <= 0 or p1y <= 0:
        return web.json_response({"ok": False, "error": "Prices must be > 0"}, status=400)
    try:
        m = await _get_dashboard_metrics()
        from metrics import simulate_pricing as _sim
        result = _sim(m["active_plan_mix"], [p1m, p3m, p1y])
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)
    return web.json_response({"ok": True, "simulation": result})


# ── Запуск ────────────────────────────────────────────────────────────────────

async def on_startup(app: web.Application) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    await init_web_users_table()
    if not server_manager.servers:
        server_manager.load_config()
    logger.info("SWAGA Web started on port %d", WEB_LISTEN_PORT)


def main() -> None:
    app = web.Application(middlewares=[security_headers_middleware])
    app.add_routes(routes)
    app.on_startup.append(on_startup)
    web.run_app(app, host="127.0.0.1", port=WEB_LISTEN_PORT, access_log=logger)


if __name__ == "__main__":
    main()
