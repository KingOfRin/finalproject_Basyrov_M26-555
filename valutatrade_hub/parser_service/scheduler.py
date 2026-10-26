"""Планировщик периодического обновления курсов.

Запуск отдельным процессом:
    uv run valutatrade-parser                 # каждые N секунд (из конфигурации)
    uv run valutatrade-parser --interval 60   # свой интервал
    uv run valutatrade-parser --once          # одно обновление и выход
"""

import argparse
import threading

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.logging_config import get_parser_logger
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.updater import RatesUpdater


class RatesScheduler:
    """Вызывает RatesUpdater.run_update() раз в interval_seconds."""

    def __init__(self, updater: RatesUpdater, interval_seconds: int):
        if interval_seconds <= 0:
            raise ValueError("Интервал обновления должен быть положительным")
        self.updater = updater
        self.interval_seconds = interval_seconds
        self.logger = get_parser_logger()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> bool:
        """Одно обновление; ошибки логируются и не останавливают планировщик."""
        try:
            result = self.updater.run_update()
        except ApiRequestError as error:
            self.logger.error("Scheduled update failed: %s", error.reason)
            return False
        self.logger.info(
            "Scheduled update done: %d rates, last refresh %s",
            result.updated,
            result.last_refresh,
        )
        return not result.has_errors

    def run_forever(self, max_runs: int | None = None) -> None:
        """Блокирующий цикл обновлений до stop() или max_runs прогонов."""
        runs = 0
        while not self._stop_event.is_set():
            self.run_once()
            runs += 1
            if max_runs is not None and runs >= max_runs:
                break
            self._stop_event.wait(self.interval_seconds)

    def start(self) -> None:
        """Запускает цикл обновлений в фоновом потоке."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Останавливает цикл обновлений."""
        self._stop_event.set()
        if self._thread:
            self._thread.join()


def main() -> None:
    """CLI-точка входа для запуска Parser Service по расписанию."""
    config = ParserConfig()
    parser = argparse.ArgumentParser(description="ValutaTrade Hub Parser Service")
    parser.add_argument(
        "--interval",
        type=int,
        default=config.UPDATE_INTERVAL_SECONDS,
        help="интервал обновления в секундах",
    )
    parser.add_argument(
        "--once", action="store_true", help="выполнить одно обновление и выйти"
    )
    args = parser.parse_args()

    scheduler = RatesScheduler(RatesUpdater(), args.interval)
    if args.once:
        scheduler.run_once()
        return
    scheduler.logger.info(
        "Parser Service started, interval %d s (Ctrl+C to stop)", args.interval
    )
    try:
        scheduler.run_forever()
    except KeyboardInterrupt:
        scheduler.logger.info("Parser Service stopped")


if __name__ == "__main__":
    main()
