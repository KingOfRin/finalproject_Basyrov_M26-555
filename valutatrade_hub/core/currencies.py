"""Иерархия валют: абстрактный Currency, FiatCurrency, CryptoCurrency и реестр."""

from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError

CODE_MIN_LENGTH = 2
CODE_MAX_LENGTH = 5


class Currency(ABC):
    """Абстрактная валюта с единым интерфейсом отображения.

    Инварианты: code — верхний регистр, 2–5 символов без пробелов;
    name — непустая строка.
    """

    def __init__(self, name: str, code: str):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Название валюты не может быть пустым")
        if not is_valid_code(code):
            raise ValueError(
                f"Некорректный код валюты '{code}': нужен верхний регистр, "
                f"{CODE_MIN_LENGTH}–{CODE_MAX_LENGTH} символов без пробелов"
            )
        self.name = name.strip()
        self.code = code

    @abstractmethod
    def get_display_info(self) -> str:
        """Возвращает строковое представление валюты для UI и логов."""

    def __str__(self):
        return self.get_display_info()

    def __repr__(self):
        return f"{type(self).__name__}(code={self.code!r}, name={self.name!r})"


class FiatCurrency(Currency):
    """Фиатная валюта с указанием страны или зоны эмиссии."""

    def __init__(self, name: str, code: str, issuing_country: str):
        super().__init__(name, code)
        self.issuing_country = issuing_country

    def get_display_info(self) -> str:
        """Пример: "[FIAT] USD — US Dollar (Issuing: United States)"."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом консенсуса и рыночной капитализацией."""

    def __init__(self, name: str, code: str, algorithm: str, market_cap: float):
        super().__init__(name, code)
        self.algorithm = algorithm
        self.market_cap = float(market_cap)

    def get_display_info(self) -> str:
        """Пример: "[CRYPTO] BTC — Bitcoin (Algo: SHA-256, MCAP: 1.12e12)"."""
        mantissa, exponent = f"{self.market_cap:.2e}".split("e")
        mcap = f"{mantissa}e{int(exponent)}"
        return (
            f"[CRYPTO] {self.code} — {self.name} (Algo: {self.algorithm}, MCAP: {mcap})"
        )


def is_valid_code(code) -> bool:
    """Проверяет формат кода валюты: верхний регистр, 2–5 символов, без пробелов."""
    return (
        isinstance(code, str)
        and CODE_MIN_LENGTH <= len(code) <= CODE_MAX_LENGTH
        and code.isalnum()
        and code == code.upper()
    )


# Капитализация — последнее известное значение (справочно, в расчётах не участвует).
_REGISTRY: dict[str, Currency] = {
    currency.code: currency
    for currency in (
        FiatCurrency("US Dollar", "USD", "United States"),
        FiatCurrency("Euro", "EUR", "Eurozone"),
        FiatCurrency("British Pound", "GBP", "United Kingdom"),
        FiatCurrency("Russian Ruble", "RUB", "Russia"),
        FiatCurrency("Chinese Yuan", "CNY", "China"),
        CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
        CryptoCurrency("Ethereum", "ETH", "Ethash", 4.5e11),
        CryptoCurrency("Solana", "SOL", "Proof of History", 6.5e10),
    )
}


def get_currency(code: str) -> Currency:
    """Фабрика: возвращает валюту по коду (регистр не важен).

    Raises:
        CurrencyNotFoundError: если код пустой, некорректный или не поддерживается.
    """
    normalized = code.strip().upper() if isinstance(code, str) else ""
    currency = _REGISTRY.get(normalized)
    if currency is None:
        raise CurrencyNotFoundError(normalized or code)
    return currency


def get_supported_codes() -> list[str]:
    """Возвращает отсортированный список поддерживаемых кодов валют."""
    return sorted(_REGISTRY)


def is_crypto(code: str) -> bool:
    """Возвращает True, если код принадлежит известной криптовалюте."""
    return isinstance(_REGISTRY.get(code), CryptoCurrency)
