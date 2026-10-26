"""Бизнес-логика Core Service: пользователи, портфель, торговля, курсы.

CLI вызывает только функции этого модуля. Здесь же используются синглтоны:
SettingsLoader (TTL курсов, базовая валюта) и DatabaseManager (JSON-хранилище).
Операции с хранилищем выполняются по схеме «прочитать -> изменить в памяти ->
атомарно записать», поэтому при исключении на диск ничего не попадает.

Экономика торговли: все сделки идут через USD-кошелёк.
    buy  X — списывает amount * rate(X→USD) с USD и зачисляет amount на X;
    sell X — списывает amount с X и зачисляет amount * rate(X→USD) на USD;
    buy/sell USD — пополнение/вывод USD без конвертации.
"""

from valutatrade_hub.core.currencies import (
    CryptoCurrency,
    get_currency,
    get_supported_codes,
)
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    InvalidPasswordError,
    NotLoggedInError,
    RatesCacheEmptyError,
    RateUnavailableError,
    UnknownBaseCurrencyError,
    UsernameTakenError,
    UserNotFoundError,
    WalletNotFoundError,
)
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import (
    PIVOT_CURRENCY,
    is_fresh,
    parse_iso,
    resolve_rate,
    validate_amount,
    validate_currency_code,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.updater import RatesUpdater, UpdateResult

TRADE_CURRENCY = PIVOT_CURRENCY


def _db() -> DatabaseManager:
    return DatabaseManager()


def _ttl() -> int:
    return int(SettingsLoader().get("rates_ttl_seconds"))


def _validated_currency(code: str) -> str:
    """Проверяет формат кода и наличие валюты в реестре; возвращает код."""
    return get_currency(validate_currency_code(code)).code


# ---------- Пользователи ----------


def _find_user_record(username: str) -> dict | None:
    wanted = username.strip().lower()
    for record in _db().load_users():
        if record["username"].lower() == wanted:
            return record
    return None


def _require_user(user_id: int | None) -> User:
    if user_id is None:
        raise NotLoggedInError()
    for record in _db().load_users():
        if record["user_id"] == user_id:
            return User.from_dict(record)
    raise NotLoggedInError()


@log_action("REGISTER")
def register(username: str, password: str) -> dict:
    """Регистрирует пользователя и создаёт ему пустой портфель.

    Raises:
        ValueError: пустое имя или пароль короче 4 символов.
        UsernameTakenError: имя уже занято.
    """
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Имя пользователя не может быть пустым")
    if _find_user_record(username):
        raise UsernameTakenError(username.strip())

    db = _db()
    users = db.load_users()
    user_id = max((record["user_id"] for record in users), default=0) + 1
    user = User.create(user_id, username, password)
    users.append(user.to_dict())
    db.save_users(users)

    portfolios = db.load_portfolios()
    portfolios.append(Portfolio(user_id).to_dict())
    db.save_portfolios(portfolios)
    return {"user_id": user.user_id, "username": user.username}


@log_action("LOGIN")
def login(username: str, password: str) -> dict:
    """Проверяет имя и пароль; возвращает данные для сессии CLI.

    Raises:
        UserNotFoundError, InvalidPasswordError.
    """
    record = _find_user_record(username or "")
    if record is None:
        raise UserNotFoundError(username)
    user = User.from_dict(record)
    if not user.verify_password(password):
        raise InvalidPasswordError()
    return {"user_id": user.user_id, "username": user.username}


# ---------- Портфель ----------


def _load_portfolio(user: User) -> Portfolio:
    for record in _db().load_portfolios():
        if record["user_id"] == user.user_id:
            return Portfolio.from_dict(record, user)
    return Portfolio(user.user_id, user=user)


def _save_portfolio(portfolio: Portfolio) -> None:
    db = _db()
    portfolios = [
        record
        for record in db.load_portfolios()
        if record["user_id"] != portfolio.user_id
    ]
    portfolios.append(portfolio.to_dict())
    portfolios.sort(key=lambda record: record["user_id"])
    db.save_portfolios(portfolios)


def get_portfolio(user_id: int | None, base: str | None = None) -> dict:
    """Кошельки пользователя и их стоимость в базовой валюте по кэшу курсов.

    Returns:
        {"username", "base", "rows": [{"code", "balance", "value"}], "total",
         "stale": bool, "oldest_rate_update"}

    Raises:
        NotLoggedInError, UnknownBaseCurrencyError, RateUnavailableError.
    """
    user = _require_user(user_id)
    base = base or SettingsLoader().get("default_base_currency")
    try:
        base = _validated_currency(base)
    except (CurrencyNotFoundError, ValueError):
        raise UnknownBaseCurrencyError(str(base).strip().upper()) from None

    portfolio = _load_portfolio(user)
    rates = _db().load_rates()
    pairs = rates["pairs"]
    values = portfolio.get_wallet_values(base, pairs)
    rows = []
    timestamps = []
    for code, wallet in sorted(portfolio.wallets.items()):
        updated_at = resolve_rate(code, base, pairs)[1]
        if updated_at:
            timestamps.append(updated_at)
        rows.append({"code": code, "balance": wallet.balance, "value": values[code]})
    oldest = min(timestamps, key=parse_iso) if timestamps else None
    return {
        "username": user.username,
        "base": base,
        "rows": rows,
        "total": sum(values.values()),
        "stale": oldest is not None and not is_fresh(oldest, _ttl()),
        "oldest_rate_update": oldest,
    }


# ---------- Курсы ----------


def update_rates(source: str | None = None) -> UpdateResult:
    """Запускает Parser Service немедленно (все источники или один)."""
    return RatesUpdater().run_update(source)


def get_rate(from_code: str, to_code: str) -> dict:
    """Курс from→to из кэша с учётом TTL; устаревший кэш пробует обновить.

    Returns:
        {"from", "to", "rate", "reverse_rate", "updated_at", "refreshed"}

    Raises:
        CurrencyNotFoundError: неизвестный код валюты.
        ApiRequestError: курс устарел, а обновить его не удалось.
        RateUnavailableError: курса нет в кэше и Parser Service недоступен.
    """
    from_code = get_currency(from_code).code
    to_code = get_currency(to_code).code
    ttl = _ttl()

    found = resolve_rate(from_code, to_code, _db().load_rates()["pairs"])
    refreshed = False
    refresh_error = None
    if found is None or (found[1] is not None and not is_fresh(found[1], ttl)):
        try:
            result = update_rates()
            refreshed = True
            refresh_error = "; ".join(result.errors.values()) or None
        except ApiRequestError as error:
            refresh_error = error.reason
        found = resolve_rate(from_code, to_code, _db().load_rates()["pairs"])

    if found is None:
        raise RateUnavailableError(from_code, to_code)
    rate, updated_at = found
    if updated_at is not None and not is_fresh(updated_at, ttl):
        raise ApiRequestError(
            f"курс {from_code}→{to_code} устарел (обновлён {updated_at}), "
            f"обновить не удалось: {refresh_error or 'нет свежих данных'}"
        )
    return {
        "from": from_code,
        "to": to_code,
        "rate": rate,
        "reverse_rate": 1 / rate,
        "updated_at": updated_at,
        "refreshed": refreshed,
    }


def _trade_rate(code: str) -> float:
    if code == TRADE_CURRENCY:
        return 1.0
    try:
        return get_rate(code, TRADE_CURRENCY)["rate"]
    except RateUnavailableError:
        raise RateUnavailableError(
            code,
            TRADE_CURRENCY,
            f"Не удалось получить курс для {code}→{TRADE_CURRENCY}",
        ) from None


def show_rates(
    currency: str | None = None, top: int | None = None, base: str | None = None
) -> dict:
    """Курсы из локального кэша с фильтрами (без обращения к API).

    Args:
        currency: показать только пары с этой валютой.
        top: показать N самых дорогих криптовалют.
        base: пересчитать все курсы относительно этой валюты.

    Returns:
        {"last_refresh", "base", "rows": [{"pair", "rate", "updated_at",
         "source", "stale"}]}

    Raises:
        RatesCacheEmptyError, CurrencyNotFoundError, RateUnavailableError.
    """
    rates = _db().load_rates()
    pairs = rates["pairs"]
    if not pairs:
        raise RatesCacheEmptyError()

    base = _validated_currency(base) if base else TRADE_CURRENCY
    codes = {key.split("_", 1)[0] for key in pairs} | {TRADE_CURRENCY}
    rows = []
    for code in sorted(codes - {base}):
        found = resolve_rate(code, base, pairs)
        if found is None:
            continue
        source_entry = pairs.get(f"{code}_{TRADE_CURRENCY}") or pairs.get(
            f"{base}_{TRADE_CURRENCY}", {}
        )
        rows.append(
            {
                "code": code,
                "pair": f"{code}_{base}",
                "rate": found[0],
                "updated_at": found[1],
                "source": source_entry.get("source", "—"),
                "stale": not is_fresh(found[1], _ttl()),
            }
        )

    if currency:
        code = validate_currency_code(currency)
        rows = [row for row in rows if row["code"] == code]
        if not rows:
            raise RateUnavailableError(
                code, base, f"Курс для '{code}' не найден в кеше."
            )
    if top is not None:
        if top <= 0:
            raise ValueError("'top' должен быть целым положительным числом")
        crypto = [row for row in rows if _is_crypto_code(row["code"])]
        rows = sorted(crypto, key=lambda row: row["rate"], reverse=True)[:top]
    return {"last_refresh": rates.get("last_refresh"), "base": base, "rows": rows}


def _is_crypto_code(code: str) -> bool:
    try:
        return isinstance(get_currency(code), CryptoCurrency)
    except CurrencyNotFoundError:
        return False


def list_currencies() -> list[str]:
    """Описания всех поддерживаемых валют (get_display_info)."""
    return [get_currency(code).get_display_info() for code in get_supported_codes()]


# ---------- Торговля ----------


@log_action("BUY", verbose=True)
def buy(user_id: int | None, currency_code: str, amount: float) -> dict:
    """Покупает amount единиц валюты за USD (кошелёк создаётся автоматически).

    Raises:
        NotLoggedInError, ValueError (amount/код), CurrencyNotFoundError,
        RateUnavailableError, ApiRequestError, InsufficientFundsError (USD).
    """
    user = _require_user(user_id)
    amount = validate_amount(amount)
    code = _validated_currency(currency_code)
    portfolio = _load_portfolio(user)

    rate = _trade_rate(code)
    cost = amount * rate
    usd_wallet = portfolio.get_wallet(TRADE_CURRENCY)
    usd_before = usd_wallet.balance if usd_wallet else 0.0
    if code != TRADE_CURRENCY:
        if usd_wallet is None or cost > usd_wallet.balance:
            raise InsufficientFundsError(usd_before, cost, TRADE_CURRENCY)
        usd_wallet.withdraw(cost)

    wallet = portfolio.get_or_create_wallet(code)
    before = wallet.balance
    wallet.deposit(amount)
    _save_portfolio(portfolio)

    usd_after = portfolio.get_wallet(TRADE_CURRENCY).balance
    return {
        "username": user.username,
        "currency_code": code,
        "amount": amount,
        "rate": rate,
        "base": TRADE_CURRENCY,
        "before": before,
        "after": wallet.balance,
        "estimated_value": cost,
        "usd_before": usd_before,
        "usd_after": usd_after,
    }


@log_action("SELL", verbose=True)
def sell(user_id: int | None, currency_code: str, amount: float) -> dict:
    """Продаёт amount единиц валюты, выручка зачисляется на USD-кошелёк.

    Raises:
        NotLoggedInError, ValueError (amount/код), CurrencyNotFoundError,
        WalletNotFoundError, InsufficientFundsError, RateUnavailableError,
        ApiRequestError.
    """
    user = _require_user(user_id)
    amount = validate_amount(amount)
    code = _validated_currency(currency_code)
    portfolio = _load_portfolio(user)

    wallet = portfolio.get_wallet(code)
    if wallet is None:
        raise WalletNotFoundError(code)
    if amount > wallet.balance:
        raise InsufficientFundsError(wallet.balance, amount, code)

    rate = _trade_rate(code)
    revenue = amount * rate
    usd_wallet = portfolio.get_wallet(TRADE_CURRENCY)
    usd_before = usd_wallet.balance if usd_wallet else 0.0
    before = wallet.balance
    wallet.withdraw(amount)
    if code != TRADE_CURRENCY:
        portfolio.get_or_create_wallet(TRADE_CURRENCY).deposit(revenue)
    _save_portfolio(portfolio)

    usd_wallet = portfolio.get_wallet(TRADE_CURRENCY)
    return {
        "username": user.username,
        "currency_code": code,
        "amount": amount,
        "rate": rate,
        "base": TRADE_CURRENCY,
        "before": before,
        "after": wallet.balance,
        "estimated_value": revenue,
        "usd_before": usd_before,
        "usd_after": usd_wallet.balance if usd_wallet else 0.0,
    }
