"""Декоратор @log_action — логирование доменных операций.

Поля записи: timestamp (ISO, из форматтера), action, user, currency, amount,
rate, base, result (OK/ERROR), error_type/error_message при исключении.
При verbose=True добавляется состояние кошелька «было→стало».

Пример:
    INFO 2025-10-09T12:05:22 BUY user='alice' currency='BTC' amount=0.0500
    rate=59300.00 base='USD' result=OK
"""

import functools
import inspect

from valutatrade_hub.core.utils import format_rate
from valutatrade_hub.logging_config import get_actions_logger

AMOUNT_DECIMALS = 4


def _format_amount(value) -> str:
    try:
        return f"{float(value):.{AMOUNT_DECIMALS}f}"
    except (TypeError, ValueError):
        return repr(value)


def _collect_context(func, args, kwargs) -> dict:
    try:
        bound = inspect.signature(func).bind(*args, **kwargs)
    except TypeError:
        return dict(kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def _build_message(action, context, result, verbose) -> str:
    result = result if isinstance(result, dict) else {}
    user = result.get("username") or context.get("username")

    parts = [action]
    if user is not None:
        parts.append(f"user='{user}'")
    elif context.get("user_id") is not None:
        parts.append(f"user_id={context['user_id']}")
    currency = result.get("currency_code") or context.get("currency_code")
    if currency:
        parts.append(f"currency='{currency}'")
    amount = result.get("amount", context.get("amount"))
    if amount is not None:
        parts.append(f"amount={_format_amount(amount)}")
    if result.get("rate") is not None:
        parts.append(f"rate={format_rate(result['rate'])}")
    if result.get("base"):
        parts.append(f"base='{result['base']}'")
    if verbose and "before" in result and "after" in result:
        parts.append(
            f"wallet={_format_amount(result['before'])}"
            f"→{_format_amount(result['after'])}"
        )
    return " ".join(parts)


def log_action(action: str, verbose: bool = False):
    """Логирует вызов операции на уровне INFO и пробрасывает исключения дальше.

    Args:
        action: имя операции в логе (BUY, SELL, REGISTER, LOGIN).
        verbose: добавлять ли контекст «было→стало» из результата операции.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_actions_logger()
            context = _collect_context(func, args, kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception as error:
                message = _build_message(action, context, None, verbose)
                logger.info(
                    "%s result=ERROR error_type=%s error_message='%s'",
                    message,
                    type(error).__name__,
                    error,
                )
                raise
            logger.info(
                "%s result=OK", _build_message(action, context, result, verbose)
            )
            return result

        return wrapper

    return decorator
