"""Настройка логирования: формат, уровень, ротация файлов.

Формат — человекочитаемая строка (выбран вместо JSON ради удобства чтения
глазами при отладке и в демо):
    INFO 2025-10-09T12:05:22 BUY user='alice' currency='BTC' amount=0.0500 ...

Логгеры:
    valutatrade.actions — доменные операции (@log_action) -> logs/actions.log;
    valutatrade.parser  — Parser Service -> logs/parser.log и консоль.

Ротация: RotatingFileHandler по размеру (log_max_bytes, по умолчанию 1 МБ),
хранится log_backup_count архивов. Уровень по умолчанию INFO, для отладки —
VALUTATRADE_LOG_LEVEL=DEBUG.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from valutatrade_hub.infra.settings import SettingsLoader

ACTIONS_LOGGER = "valutatrade.actions"
PARSER_LOGGER = "valutatrade.parser"
CONSOLE_FORMAT = "%(levelname)s: %(message)s"

_configured = False


def _file_handler(settings: SettingsLoader, path_key: str) -> logging.Handler:
    path = settings.get_path(path_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path,
        maxBytes=int(settings.get("log_max_bytes")),
        backupCount=int(settings.get("log_backup_count")),
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(settings.get("log_format"), settings.get("log_date_format"))
    )
    return handler


def setup_logging() -> None:
    """Настраивает логгеры приложения (повторные вызовы ничего не меняют)."""
    global _configured
    if _configured:
        return
    settings = SettingsLoader()
    level = getattr(logging, str(settings.get("log_level")).upper(), logging.INFO)

    actions = logging.getLogger(ACTIONS_LOGGER)
    actions.setLevel(level)
    actions.addHandler(_file_handler(settings, "actions_log_file"))
    actions.propagate = False

    parser = logging.getLogger(PARSER_LOGGER)
    parser.setLevel(level)
    parser.addHandler(_file_handler(settings, "parser_log_file"))
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    parser.addHandler(console)
    parser.propagate = False

    _configured = True


def get_actions_logger() -> logging.Logger:
    setup_logging()
    return logging.getLogger(ACTIONS_LOGGER)


def get_parser_logger() -> logging.Logger:
    setup_logging()
    return logging.getLogger(PARSER_LOGGER)
