"""DatabaseManager — абстракция над JSON-хранилищем (Singleton).

Чтение возвращает значение по умолчанию, если файла ещё нет.
Запись атомарная: данные пишутся во временный файл рядом с целевым,
затем он заменяет целевой через os.replace — файл никогда не остаётся
записанным наполовину.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from valutatrade_hub.core.exceptions import ValutaTradeError
from valutatrade_hub.core.utils import create_file_cache
from valutatrade_hub.infra.settings import SettingsLoader


class DatabaseManager:
    """Единая точка доступа к users.json, portfolios.json и rates.json.

    Singleton через __new__ (аналогично SettingsLoader): один объект на процесс,
    общий кэш чтения rates.json для всех модулей.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._settings = SettingsLoader()
            instance._cached_read = create_file_cache(instance._read_from_disk)
            cls._instance = instance
        return cls._instance

    # ---------- Низкоуровневые операции ----------

    @staticmethod
    def _read_from_disk(path: Path) -> Any:
        if not path.exists() or path.stat().st_size == 0:
            return None
        try:
            with path.open(encoding="utf-8") as file:
                return json.load(file)
        except json.JSONDecodeError as error:
            raise ValutaTradeError(
                f"Файл данных '{path.name}' повреждён: {error.msg}"
            ) from error

    def read_json(self, path: Path, default: Any) -> Any:
        """Читает JSON; если файла нет или он пуст — возвращает default."""
        data = self._cached_read(Path(path))
        return default if data is None else data

    def write_json(self, path: Path, data: Any) -> None:
        """Атомарно записывает JSON (временный файл -> os.replace)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.stem}_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            os.replace(tmp_name, path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise

    # ---------- Доменные коллекции ----------

    def load_users(self) -> list[dict]:
        return self.read_json(self._settings.get_path("users_file"), [])

    def save_users(self, users: list[dict]) -> None:
        self.write_json(self._settings.get_path("users_file"), users)

    def load_portfolios(self) -> list[dict]:
        return self.read_json(self._settings.get_path("portfolios_file"), [])

    def save_portfolios(self, portfolios: list[dict]) -> None:
        self.write_json(self._settings.get_path("portfolios_file"), portfolios)

    def load_rates(self) -> dict:
        """Снимок курсов: {"pairs": {...}, "last_refresh": "..."}."""
        data = self.read_json(self._settings.get_path("rates_file"), {})
        data.setdefault("pairs", {})
        return data

    def save_rates(self, rates: dict) -> None:
        self.write_json(self._settings.get_path("rates_file"), rates)
