"""RatesUpdater — координирует обновление курсов из всех источников."""

import time
from dataclasses import dataclass, field

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import utc_now_iso
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import get_parser_logger
from valutatrade_hub.parser_service.api_clients import BaseApiClient, build_clients
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage, make_record_id


@dataclass
class UpdateResult:
    """Итог одного прогона обновления."""

    updated: int = 0
    last_refresh: str | None = None
    sources: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class RatesUpdater:
    """Опрашивает API-клиентов, объединяет курсы и сохраняет их.

    Отказоустойчивость: ошибка одного клиента логируется, остальные
    продолжают работу. ApiRequestError бросается, только если не ответил
    ни один из выбранных источников.
    """

    def __init__(
        self,
        clients: list[BaseApiClient] | None = None,
        storage: RatesStorage | None = None,
    ):
        config = ParserConfig()
        self.clients = clients if clients is not None else build_clients(config)
        self.storage = storage or RatesStorage(config)
        self.logger = get_parser_logger()

    def available_sources(self) -> list[str]:
        return [client.source_key for client in self.clients]

    def _select_clients(self, source: str | None) -> list[BaseApiClient]:
        if source is None:
            return self.clients
        selected = [c for c in self.clients if c.source_key == source.lower()]
        if not selected:
            raise ValueError(
                f"Неизвестный источник '{source}'. "
                f"Доступно: {', '.join(self.available_sources())}"
            )
        return selected

    def run_update(self, source: str | None = None) -> UpdateResult:
        """Обновляет курсы из всех (или одного) источников.

        Args:
            source: ключ источника (coingecko / exchangerate) или None — все.

        Raises:
            ValueError: неизвестный источник.
            ApiRequestError: ни один источник не вернул данные.
        """
        clients = self._select_clients(source)
        started = time.perf_counter()
        self.logger.info("Starting rates update...")

        result = UpdateResult()
        pairs: dict[str, dict] = {}
        history: list[dict] = []
        for client in clients:
            self._fetch_from(client, result, pairs, history)

        if not pairs:
            reasons = "; ".join(
                f"{name}: {reason}" for name, reason in result.errors.items()
            )
            self.logger.error("Update failed: no source returned data.")
            raise ApiRequestError(reasons or "нет данных ни от одного источника")

        result.last_refresh = utc_now_iso()
        self.logger.info("Writing %d rates to %s...", len(pairs), self._display_path())
        self.storage.append_history(history)
        self.storage.save_rates(pairs, result.last_refresh)
        result.updated = len(pairs)
        self.logger.debug(
            "Update finished in %.0f ms", (time.perf_counter() - started) * 1000
        )
        return result

    def _fetch_from(self, client, result, pairs, history) -> None:
        self.logger.debug("Fetching from %s...", client.name)
        try:
            rates = client.fetch_rates()
        except ApiRequestError as error:
            result.errors[client.name] = error.reason
            self.logger.error("Failed to fetch from %s: %s", client.name, error.reason)
            return

        fetched_at = utc_now_iso()
        meta = client.last_fetch_meta
        for key, rate in rates.items():
            from_code, to_code = key.split("_", 1)
            pairs[key] = {"rate": rate, "updated_at": fetched_at, "source": client.name}
            history.append(
                {
                    "id": make_record_id(from_code, to_code, fetched_at),
                    "from_currency": from_code,
                    "to_currency": to_code,
                    "rate": rate,
                    "timestamp": fetched_at,
                    "source": client.name,
                    "meta": {
                        "raw_id": meta.get("raw_ids", {}).get(key),
                        "request_ms": meta.get("request_ms"),
                        "status_code": meta.get("status_code"),
                        "etag": meta.get("etag"),
                        "source_timestamp": meta.get("source_timestamp"),
                    },
                }
            )
        result.sources[client.name] = len(rates)
        self.logger.info("Fetching from %s... OK (%d rates)", client.name, len(rates))

    def _display_path(self) -> str:
        path = self.storage.rates_path
        try:
            return path.relative_to(SettingsLoader().project_root).as_posix()
        except ValueError:
            return str(path)
