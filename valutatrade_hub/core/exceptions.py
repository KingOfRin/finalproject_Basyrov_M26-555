"""Пользовательские (доменные) исключения ValutaTrade Hub.

Все исключения наследуются от ValutaTradeError, поэтому CLI может
перехватывать их единообразно и печатать str(error) как сообщение.
"""


class ValutaTradeError(Exception):
    """Базовое доменное исключение приложения."""


class InsufficientFundsError(ValutaTradeError):
    """Недостаточно средств на кошельке.

    Возникает в Wallet.withdraw() и в usecases.buy()/sell().
    """

    def __init__(self, available, required, code):
        from valutatrade_hub.core.utils import format_amount

        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {format_amount(available, code)} "
            f"{code}, требуется {format_amount(required, code)} {code}"
        )


class CurrencyNotFoundError(ValutaTradeError):
    """Неизвестная валюта.

    Возникает в currencies.get_currency() и при валидации кодов в usecases.
    """

    def __init__(self, code):
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class UnknownBaseCurrencyError(CurrencyNotFoundError):
    """Неизвестная базовая валюта в show-portfolio."""

    def __init__(self, code):
        super().__init__(code)
        self.args = (f"Неизвестная базовая валюта '{code}'",)


class ApiRequestError(ValutaTradeError):
    """Сбой внешнего API или невозможность обновить курсы.

    Возникает в parser_service (api_clients, updater) и в usecases.get_rate().
    """

    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")


class RateUnavailableError(ValutaTradeError):
    """Курса нет в кэше и получить его не удалось."""

    def __init__(self, from_code, to_code, message=None):
        self.from_code = from_code
        self.to_code = to_code
        super().__init__(
            message
            or f"Курс {from_code}→{to_code} недоступен. Повторите попытку позже."
        )


class RatesCacheEmptyError(ValutaTradeError):
    """Локальный кэш курсов (rates.json) пуст или не найден."""

    def __init__(self):
        super().__init__(
            "Локальный кеш курсов пуст. "
            "Выполните 'update-rates', чтобы загрузить данные."
        )


class UsernameTakenError(ValutaTradeError):
    """Имя пользователя уже занято."""

    def __init__(self, username):
        super().__init__(f"Имя пользователя '{username}' уже занято")


class UserNotFoundError(ValutaTradeError):
    """Пользователь не найден."""

    def __init__(self, username):
        super().__init__(f"Пользователь '{username}' не найден")


class InvalidPasswordError(ValutaTradeError):
    """Неверный пароль при входе."""

    def __init__(self):
        super().__init__("Неверный пароль")


class NotLoggedInError(ValutaTradeError):
    """Команда требует авторизации."""

    def __init__(self):
        super().__init__("Сначала выполните login")


class WalletNotFoundError(ValutaTradeError):
    """У пользователя нет кошелька в указанной валюте."""

    def __init__(self, code):
        self.code = code
        super().__init__(
            f"У вас нет кошелька '{code}'. Добавьте валюту: "
            "она создаётся автоматически при первой покупке."
        )
