"""Вспомогательные функции: валидация, форматирование, расчёт курсов, время."""

import copy
import os
from datetime import datetime, timezone

from valutatrade_hub.core.currencies import is_crypto, is_valid_code

PIVOT_CURRENCY = "USD"
CRYPTO_DECIMALS = 4
FIAT_DECIMALS = 2
RATE_SMALL_DECIMALS = 8


# ---------- Валидация ----------


def validate_amount(amount) -> float:
    """Приводит amount к float и проверяет, что это положительное число."""
    error = ValueError("'amount' должен быть положительным числом")
    if isinstance(amount, bool):
        raise error
    try:
        value = float(amount)
    except (TypeError, ValueError):
        raise error from None
    if value != value or value <= 0 or value == float("inf"):
        raise error
    return value


def validate_currency_code(code) -> str:
    """Нормализует код валюты (strip + upper) и проверяет его формат."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Код валюты не может быть пустым")
    normalized = code.strip().upper()
    if not is_valid_code(normalized):
        raise ValueError(
            f"Некорректный код валюты '{code}': ожидается 2–5 латинских букв/цифр"
        )
    return normalized


# ---------- Форматирование ----------


def format_amount(amount: float, code: str) -> str:
    """Сумма без разделителей: 4 знака для криптовалют, 2 — для фиата."""
    decimals = CRYPTO_DECIMALS if is_crypto(code) else FIAT_DECIMALS
    return f"{amount:.{decimals}f}"


def format_money(amount: float) -> str:
    """Денежная сумма с разделителем тысяч: 3329.0 -> '3,329.00'."""
    return f"{amount:,.{FIAT_DECIMALS}f}"


def format_rate(rate: float) -> str:
    """Курс: 2 знака для значений >= 1, до 8 значащих знаков после точки иначе."""
    if rate >= 1:
        return f"{rate:.{FIAT_DECIMALS}f}"
    return f"{rate:.{RATE_SMALL_DECIMALS}f}".rstrip("0").rstrip(".") or "0"


def format_timestamp(value: str | None) -> str:
    """ISO-время -> 'YYYY-MM-DD HH:MM:SS' для вывода пользователю."""
    if not value:
        return "—"
    try:
        return parse_iso(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


# ---------- Время ----------


def utc_now_iso() -> str:
    """Текущее время UTC в ISO-формате с суффиксом Z (без микросекунд)."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    """Парсит ISO-строку; время без зоны считается UTC."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def is_fresh(updated_at: str | None, ttl_seconds: int) -> bool:
    """True, если с момента updated_at прошло не больше ttl_seconds."""
    if not updated_at:
        return False
    try:
        age = datetime.now(timezone.utc) - parse_iso(updated_at)
    except ValueError:
        return False
    return age.total_seconds() <= ttl_seconds


# ---------- Курсы ----------


def pair_key(from_code: str, to_code: str) -> str:
    """Ключ пары в кэше курсов: ('BTC', 'USD') -> 'BTC_USD'."""
    return f"{from_code}_{to_code}"


def _oldest(*timestamps):
    known = [ts for ts in timestamps if ts]
    return min(known, key=parse_iso) if known else None


def _direct_rate(from_code, to_code, pairs):
    direct = pairs.get(pair_key(from_code, to_code))
    if direct and direct.get("rate"):
        return float(direct["rate"]), direct.get("updated_at")
    inverse = pairs.get(pair_key(to_code, from_code))
    if inverse and inverse.get("rate"):
        return 1 / float(inverse["rate"]), inverse.get("updated_at")
    return None


def resolve_rate(from_code: str, to_code: str, pairs: dict):
    """Находит курс from→to по кэшу пар (напрямую, обратно или через USD).

    Args:
        pairs: {"BTC_USD": {"rate": 59337.21, "updated_at": "..."}, ...}

    Returns:
        (rate, updated_at) либо None, если курс вычислить нельзя.
        updated_at — самое старое время среди использованных пар.
    """
    if from_code == to_code:
        return 1.0, None
    found = _direct_rate(from_code, to_code, pairs)
    if found:
        return found
    to_pivot = _direct_rate(from_code, PIVOT_CURRENCY, pairs)
    from_pivot = _direct_rate(PIVOT_CURRENCY, to_code, pairs)
    if from_code == PIVOT_CURRENCY:
        to_pivot = (1.0, None)
    if to_code == PIVOT_CURRENCY:
        from_pivot = (1.0, None)
    if to_pivot and from_pivot:
        return to_pivot[0] * from_pivot[0], _oldest(to_pivot[1], from_pivot[1])
    return None


# ---------- Кэширование (замыкание) ----------


def create_file_cache(loader):
    """Возвращает get(path) с кэшем в замыкании, сбрасываемым при изменении файла.

    loader(path) вызывается, только если файл ещё не читался или его mtime
    изменился. Так частые запросы курсов не перечитывают rates.json с диска.
    """
    cache = {}

    def get(path):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        cached = cache.get(path)
        if cached is None or cached[0] != mtime:
            cache[path] = (mtime, loader(path))
        return copy.deepcopy(cache[path][1])

    def clear():
        cache.clear()

    get.clear = clear
    return get
