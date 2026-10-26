"""Клиенты внешних API курсов с единым интерфейсом fetch_rates().

Все клиенты возвращают курсы в стандартном формате {"BTC_USD": 59337.21, ...},
где значение — сколько единиц базовой валюты (USD) стоит 1 единица валюты.
Любая сетевая ошибка, неуспешный HTTP-статус или некорректный ответ
превращаются в ApiRequestError с понятным сообщением.
"""

import time
from abc import ABC, abstractmethod
from email.utils import parsedate_to_datetime

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.config import API_KEY_ENV, ParserConfig

HTTP_OK = 200
HTTP_STATUS_MESSAGES = {
    400: "некорректный запрос",
    401: "неверный или отсутствующий API-ключ",
    403: "доступ запрещён (проверьте API-ключ)",
    404: "ресурс не найден (проверьте URL или API-ключ)",
    429: "превышен лимит запросов, подождите и повторите позже",
}
EXCHANGERATE_ERROR_MESSAGES = {
    "invalid-key": "неверный API-ключ",
    "inactive-account": "аккаунт ExchangeRate-API не активирован",
    "quota-reached": "исчерпан лимит запросов по тарифу",
    "unsupported-code": "неподдерживаемый код валюты",
    "malformed-request": "некорректный запрос",
}


class BaseApiClient(ABC):
    """Базовый клиент: HTTP-запрос, замер времени и обработка ошибок."""

    #: Человекочитаемое имя источника (пишется в source и в логи).
    name: str = ""
    #: Ключ источника для CLI-опции update-rates --source.
    source_key: str = ""

    def __init__(self, config: ParserConfig | None = None):
        self.config = config or ParserConfig()
        self.last_fetch_meta: dict = {}

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Возвращает курсы {"<CODE>_<BASE>": rate}.

        Raises:
            ApiRequestError: при любой ошибке получения или разбора данных.
        """

    def _request_json(self, url: str, params: dict | None = None) -> dict:
        started = time.perf_counter()
        try:
            response = requests.get(
                url, params=params, timeout=self.config.REQUEST_TIMEOUT
            )
        except requests.exceptions.Timeout:
            raise ApiRequestError(
                f"превышено время ожидания ответа ({self.config.REQUEST_TIMEOUT} с)"
            ) from None
        except requests.exceptions.ConnectionError:
            raise ApiRequestError(
                "нет соединения с сервером (проверьте сеть)"
            ) from None
        except requests.exceptions.RequestException as error:
            # Текст исключения не выводим: он может содержать URL с API-ключом.
            raise ApiRequestError(f"сетевая ошибка ({type(error).__name__})") from None

        self.last_fetch_meta = {
            "request_ms": round((time.perf_counter() - started) * 1000),
            "status_code": response.status_code,
            "etag": response.headers.get("ETag"),
        }
        payload = self._parse_json(response)
        if response.status_code != HTTP_OK:
            raise ApiRequestError(self._describe_http_error(response, payload))
        return payload

    def _parse_json(self, response) -> dict | None:
        try:
            payload = response.json()
        except ValueError:
            if response.status_code == HTTP_OK:
                raise ApiRequestError("ответ не является корректным JSON") from None
            return None
        return payload if isinstance(payload, dict) else None

    def _describe_http_error(self, response, payload) -> str:
        status = response.status_code
        if status >= 500:
            text = "сервер API временно недоступен"
        else:
            text = HTTP_STATUS_MESSAGES.get(status, "неожиданный ответ сервера")
        return f"{text} (HTTP {status})"

    @staticmethod
    def _positive_number(value) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if value > 0 else None


class CoinGeckoClient(BaseApiClient):
    """Курсы криптовалют из CoinGecko (публичный доступ без ключа)."""

    name = "CoinGecko"
    source_key = "coingecko"

    def fetch_rates(self) -> dict[str, float]:
        base = self.config.BASE_CURRENCY
        id_map = {
            code: self.config.CRYPTO_ID_MAP[code]
            for code in self.config.CRYPTO_CURRENCIES
            if code in self.config.CRYPTO_ID_MAP
        }
        params = {"ids": ",".join(id_map.values()), "vs_currencies": base.lower()}
        payload = self._request_json(self.config.COINGECKO_URL, params)

        rates = {}
        raw_ids = {}
        for code, raw_id in id_map.items():
            value = self._positive_number(payload.get(raw_id, {}).get(base.lower()))
            if value is not None:
                rates[f"{code}_{base}"] = value
                raw_ids[f"{code}_{base}"] = raw_id
        if not rates:
            raise ApiRequestError("в ответе нет ожидаемых курсов")
        self.last_fetch_meta["raw_ids"] = raw_ids
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Курсы фиатных валют из ExchangeRate-API (нужен API-ключ)."""

    name = "ExchangeRate-API"
    source_key = "exchangerate"

    def fetch_rates(self) -> dict[str, float]:
        key = self.config.EXCHANGERATE_API_KEY
        if not key:
            raise ApiRequestError(
                f"не задан API-ключ — установите переменную "
                f"окружения {API_KEY_ENV} или добавьте её в файл .env"
            )
        base = self.config.BASE_CURRENCY
        payload = self._request_json(
            f"{self.config.EXCHANGERATE_API_URL}/{key}/latest/{base}"
        )
        if payload.get("result") != "success":
            raise ApiRequestError(self._describe_api_error(payload))

        api_rates = payload.get("rates") or {}
        rates = {}
        for code in self.config.FIAT_CURRENCIES:
            # API отдаёт «сколько code за 1 USD»; храним «сколько USD за 1 code».
            per_base = self._positive_number(api_rates.get(code))
            if per_base is not None:
                rates[f"{code}_{base}"] = 1 / per_base
        if not rates:
            raise ApiRequestError("в ответе нет ожидаемых курсов")
        self.last_fetch_meta["source_timestamp"] = self._source_timestamp(payload)
        return rates

    def _describe_http_error(self, response, payload) -> str:
        if payload and payload.get("result") == "error":
            return self._describe_api_error(payload)
        return super()._describe_http_error(response, payload)

    def _describe_api_error(self, payload: dict) -> str:
        error_type = payload.get("error-type", "unknown")
        text = EXCHANGERATE_ERROR_MESSAGES.get(error_type, f"ошибка API '{error_type}'")
        status = self.last_fetch_meta.get("status_code")
        return f"{text} (HTTP {status})"

    @staticmethod
    def _source_timestamp(payload: dict) -> str | None:
        raw = payload.get("time_last_update_utc")
        if not raw:
            return None
        try:
            return parsedate_to_datetime(raw).isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError):
            return None


def build_clients(config: ParserConfig | None = None) -> list[BaseApiClient]:
    """Создаёт все доступные клиенты с общей конфигурацией."""
    config = config or ParserConfig()
    return [CoinGeckoClient(config), ExchangeRateApiClient(config)]
