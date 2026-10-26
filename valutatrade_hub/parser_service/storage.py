"""Хранилище Parser Service: история exchange_rates.json и снимок rates.json.

exchange_rates.json — журнал всех замеров. id записи = <FROM>_<TO>_<ISO-UTC>,
поэтому повторная запись того же замера не дублируется.
rates.json — последний корректный курс по каждой паре; новое значение
«побеждает», только если его updated_at не старше текущего.
Обе записи атомарные (через DatabaseManager: временный файл -> rename).
"""

from pathlib import Path

from valutatrade_hub.core.utils import parse_iso
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.config import ParserConfig

SNAPSHOT_SOURCE = "ParserService"


def make_record_id(from_code: str, to_code: str, timestamp: str) -> str:
    """Уникальный id замера: BTC_USD_2025-10-10T12:00:00Z."""
    return f"{from_code}_{to_code}_{timestamp}"


class RatesStorage:
    """Чтение и запись файлов курсов Parser Service."""

    def __init__(self, config: ParserConfig | None = None):
        self.config = config or ParserConfig()
        self._db = DatabaseManager()
        self.rates_path = Path(self.config.RATES_FILE_PATH)
        self.history_path = Path(self.config.HISTORY_FILE_PATH)

    # ---------- rates.json ----------

    def load_rates(self) -> dict:
        data = self._db.read_json(self.rates_path, {})
        data.setdefault("pairs", {})
        return data

    def save_rates(self, pairs: dict, last_refresh: str) -> int:
        """Сливает новые пары со снимком; возвращает число обновлённых пар.

        Args:
            pairs: {"BTC_USD": {"rate": ..., "updated_at": ..., "source": ...}}
        """
        snapshot = self.load_rates()
        current = snapshot["pairs"]
        updated = 0
        for key, entry in pairs.items():
            existing = current.get(key)
            if existing is None or _is_not_older(entry, existing):
                current[key] = entry
                updated += 1
        snapshot["source"] = SNAPSHOT_SOURCE
        snapshot["last_refresh"] = last_refresh
        self._db.write_json(self.rates_path, snapshot)
        return updated

    # ---------- exchange_rates.json ----------

    def load_history(self) -> list[dict]:
        return self._db.read_json(self.history_path, [])

    def append_history(self, records: list[dict]) -> int:
        """Добавляет новые замеры в историю; возвращает число добавленных."""
        history = self.load_history()
        known_ids = {record.get("id") for record in history}
        new_records = [record for record in records if record["id"] not in known_ids]
        if new_records:
            self._db.write_json(self.history_path, history + new_records)
        return len(new_records)


def _is_not_older(new_entry: dict, existing: dict) -> bool:
    try:
        return parse_iso(new_entry["updated_at"]) >= parse_iso(existing["updated_at"])
    except (KeyError, TypeError, ValueError):
        return True
