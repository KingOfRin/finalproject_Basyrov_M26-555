"""Доменные модели: пользователь (User), кошелёк (Wallet), портфель (Portfolio)."""

import hashlib
import hmac
import secrets
from datetime import datetime

from valutatrade_hub.core.exceptions import (
    InsufficientFundsError,
    RateUnavailableError,
)
from valutatrade_hub.core.utils import (
    format_amount,
    resolve_rate,
    validate_amount,
    validate_currency_code,
)

MIN_PASSWORD_LENGTH = 4
SALT_BYTES = 8


class User:
    """Пользователь системы. Пароль хранится только как sha256(password + salt)."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime | str,
    ):
        self._user_id = int(user_id)
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        if isinstance(registration_date, str):
            registration_date = datetime.fromisoformat(registration_date)
        self._registration_date = registration_date

    @classmethod
    def create(cls, user_id: int, username: str, password: str) -> "User":
        """Создаёт нового пользователя: генерирует соль и хеширует пароль."""
        _validate_password(password)
        salt = secrets.token_hex(SALT_BYTES)
        return cls(
            user_id=user_id,
            username=username,
            hashed_password=_hash_password(password, salt),
            salt=salt,
            registration_date=datetime.now().replace(microsecond=0),
        )

    # ---------- Свойства ----------

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, value: str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        return self._hashed_password

    @property
    def salt(self) -> str:
        return self._salt

    @property
    def registration_date(self) -> datetime:
        return self._registration_date

    # ---------- Методы ----------

    def get_user_info(self) -> dict:
        """Возвращает информацию о пользователе без пароля и соли."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "registration_date": self._registration_date.isoformat(),
        }

    def change_password(self, new_password: str) -> None:
        """Меняет пароль: генерирует новую соль и сохраняет новый хеш."""
        _validate_password(new_password)
        self._salt = secrets.token_hex(SALT_BYTES)
        self._hashed_password = _hash_password(new_password, self._salt)

    def verify_password(self, password: str) -> bool:
        """Проверяет пароль сравнением хешей за постоянное время."""
        if not isinstance(password, str):
            return False
        candidate = _hash_password(password, self._salt)
        return hmac.compare_digest(candidate, self._hashed_password)

    def to_dict(self) -> dict:
        """Сериализация для users.json (дата регистрации — ISO-строка)."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "hashed_password": self._hashed_password,
            "salt": self._salt,
            "registration_date": self._registration_date.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        return cls(
            user_id=data["user_id"],
            username=data["username"],
            hashed_password=data["hashed_password"],
            salt=data["salt"],
            registration_date=data["registration_date"],
        )

    def __repr__(self):
        return f"User(user_id={self._user_id}, username={self._username!r})"


class Wallet:
    """Кошелёк пользователя для одной валюты."""

    def __init__(self, currency_code: str, balance: float = 0.0):
        self.currency_code = validate_currency_code(currency_code)
        self.balance = balance

    @property
    def balance(self) -> float:
        return self._balance

    @balance.setter
    def balance(self, value: float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Баланс должен быть числом")
        if value < 0:
            raise ValueError("Баланс не может быть отрицательным")
        self._balance = float(value)

    def deposit(self, amount: float) -> float:
        """Пополняет баланс на положительную сумму, возвращает новый баланс."""
        amount = validate_amount(amount)
        self.balance = self._balance + amount
        return self._balance

    def withdraw(self, amount: float) -> float:
        """Списывает положительную сумму, если её хватает на балансе.

        Raises:
            InsufficientFundsError: если сумма больше текущего баланса.
        """
        amount = validate_amount(amount)
        if amount > self._balance:
            raise InsufficientFundsError(self._balance, amount, self.currency_code)
        self.balance = self._balance - amount
        return self._balance

    def get_balance_info(self) -> str:
        """Строка вида 'BTC: 0.0500'."""
        amount = format_amount(self._balance, self.currency_code)
        return f"{self.currency_code}: {amount}"

    def to_dict(self) -> dict:
        return {"currency_code": self.currency_code, "balance": self._balance}

    def __repr__(self):
        return f"Wallet({self.currency_code!r}, balance={self._balance})"


class Portfolio:
    """Все кошельки одного пользователя."""

    def __init__(
        self,
        user_id: int,
        wallets: dict[str, Wallet] | None = None,
        user: User | None = None,
    ):
        self._user_id = int(user_id)
        self._wallets: dict[str, Wallet] = dict(wallets or {})
        self._user = user

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def user(self) -> User | None:
        """Владелец портфеля (только чтение)."""
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Копия словаря кошельков: изменение копии не меняет портфель."""
        return dict(self._wallets)

    def add_currency(self, currency_code: str) -> Wallet:
        """Создаёт пустой кошелёк для новой валюты.

        Raises:
            ValueError: если кошелёк в этой валюте уже есть.
        """
        code = validate_currency_code(currency_code)
        if code in self._wallets:
            raise ValueError(f"Кошелёк '{code}' уже есть в портфеле")
        wallet = Wallet(code)
        self._wallets[code] = wallet
        return wallet

    def get_wallet(self, currency_code: str) -> Wallet | None:
        """Возвращает кошелёк по коду валюты или None."""
        return self._wallets.get(validate_currency_code(currency_code))

    def get_or_create_wallet(self, currency_code: str) -> Wallet:
        """Возвращает кошелёк, создавая его при отсутствии (как add_currency)."""
        return self.get_wallet(currency_code) or self.add_currency(currency_code)

    def get_wallet_values(self, base_currency: str, rates: dict) -> dict[str, float]:
        """Стоимость каждого кошелька в base_currency.

        Args:
            rates: кэш пар {"BTC_USD": {"rate": ..., "updated_at": ...}, ...}

        Raises:
            RateUnavailableError: если для какой-то валюты нет курса.
        """
        base = validate_currency_code(base_currency)
        values = {}
        for code, wallet in self._wallets.items():
            found = resolve_rate(code, base, rates)
            if found is None:
                raise RateUnavailableError(code, base)
            values[code] = wallet.balance * found[0]
        return values

    def get_total_value(self, base_currency: str = "USD", rates=None) -> float:
        """Общая стоимость всех кошельков в base_currency по кэшу курсов."""
        return sum(self.get_wallet_values(base_currency, rates or {}).values())

    def to_dict(self) -> dict:
        """Сериализация для portfolios.json."""
        return {
            "user_id": self._user_id,
            "wallets": {code: w.to_dict() for code, w in self._wallets.items()},
        }

    @classmethod
    def from_dict(cls, data: dict, user: User | None = None) -> "Portfolio":
        wallets = {
            code: Wallet(code, float(info.get("balance", 0.0)))
            for code, info in data.get("wallets", {}).items()
        }
        return cls(data["user_id"], wallets, user)


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()
