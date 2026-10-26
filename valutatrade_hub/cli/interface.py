"""Консольный интерфейс ValutaTrade Hub.

CLI только разбирает команды, вызывает функции core.usecases и печатает
результат. Доменные исключения перехватываются в одном месте (_execute)
и превращаются в понятные пользователю сообщения.

Режимы запуска:
    project                                  — интерактивная оболочка с сессией;
    project get-rate --from USD --to BTC     — одна команда и выход.
"""

import shlex
import sys
from dataclasses import dataclass

from prettytable import PrettyTable

from valutatrade_hub.core import usecases
from valutatrade_hub.core.currencies import get_supported_codes
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    ValutaTradeError,
)
from valutatrade_hub.core.utils import (
    format_amount,
    format_money,
    format_rate,
    format_timestamp,
)
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import setup_logging

PROMPT = "> "
EXIT_COMMANDS = ("exit", "quit")
SEPARATOR = "-" * 33
WELCOME = (
    "ValutaTrade Hub — валютный кошелёк. "
    "Введите 'help' для списка команд, 'exit' для выхода."
)


@dataclass
class Session:
    """Текущий вошедший пользователь (живёт, пока открыта оболочка)."""

    user_id: int | None = None
    username: str | None = None


@dataclass(frozen=True)
class Option:
    name: str
    required: bool = False
    description: str = ""


@dataclass(frozen=True)
class Command:
    name: str
    handler: object
    description: str
    options: tuple[Option, ...] = ()

    @property
    def usage(self) -> str:
        parts = [self.name]
        for option in self.options:
            text = f"--{option.name} <{option.name}>"
            parts.append(text if option.required else f"[{text}]")
        return " ".join(parts)


# ---------- Разбор аргументов ----------


def parse_options(command: Command, tokens: list[str]) -> dict[str, str]:
    """Разбирает '--key value' и '--key=value' согласно описанию команды."""
    allowed = {option.name for option in command.options}
    values: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            raise ValueError(
                f"Неожиданный аргумент '{token}'. Справка: help {command.name}"
            )
        name, has_value, value = token[2:].partition("=")
        if name not in allowed:
            raise ValueError(
                f"Неизвестный аргумент '--{name}' для команды '{command.name}'. "
                f"Справка: help {command.name}"
            )
        if not has_value:
            index += 1
            if index >= len(tokens) or tokens[index].startswith("--"):
                raise ValueError(f"Для аргумента --{name} не указано значение")
            value = tokens[index]
        values[name] = value
        index += 1

    for option in command.options:
        if option.required and option.name not in values:
            raise ValueError(
                f"Не указан обязательный аргумент --{option.name}. "
                f"Использование: {command.usage}"
            )
    return values


def _parse_positive_int(value: str | None, name: str) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number <= 0:
        raise ValueError(f"'{name}' должен быть целым положительным числом")
    return number


# ---------- Обработчики команд ----------


def cmd_register(session: Session, args: dict) -> None:
    result = usecases.register(args["username"], args["password"])
    print(
        f"Пользователь '{result['username']}' зарегистрирован "
        f"(id={result['user_id']}). "
        f"Войдите: login --username {result['username']} --password ****"
    )


def cmd_login(session: Session, args: dict) -> None:
    result = usecases.login(args["username"], args["password"])
    session.user_id = result["user_id"]
    session.username = result["username"]
    print(f"Вы вошли как '{result['username']}'")


def cmd_logout(session: Session, args: dict) -> None:
    if session.user_id is None:
        print("Вы не вошли в систему")
        return
    print(f"Пользователь '{session.username}' вышел из системы")
    session.user_id = session.username = None


def cmd_show_portfolio(session: Session, args: dict) -> None:
    report = usecases.get_portfolio(session.user_id, args.get("base"))
    base = report["base"]
    if not report["rows"]:
        print(
            f"Портфель пользователя '{report['username']}' пуст. "
            "Пополните счёт: buy --currency USD --amount 1000"
        )
        return
    print(f"Портфель пользователя '{report['username']}' (база: {base}):")
    for row in report["rows"]:
        balance = format_amount(row["balance"], row["code"])
        print(f"- {row['code']}: {balance}  → {format_money(row['value'])} {base}")
    print(SEPARATOR)
    print(f"ИТОГО: {format_money(report['total'])} {base}")
    if report["stale"]:
        print(
            "Внимание: курсы в кеше устарели (обновлены "
            f"{format_timestamp(report['oldest_rate_update'])}). "
            "Выполните 'update-rates' для актуальной оценки."
        )


def _print_changes(result: dict) -> None:
    code = result["currency_code"]
    print("Изменения в портфеле:")
    print(
        f"- {code}: было {format_amount(result['before'], code)} "
        f"→ стало {format_amount(result['after'], code)}"
    )
    if code != result["base"]:
        base = result["base"]
        print(
            f"- {base}: было {format_amount(result['usd_before'], base)} "
            f"→ стало {format_amount(result['usd_after'], base)}"
        )


def cmd_buy(session: Session, args: dict) -> None:
    result = usecases.buy(session.user_id, args["currency"], args["amount"])
    code, base = result["currency_code"], result["base"]
    amount = format_amount(result["amount"], code)
    if code == base:
        print(f"Пополнение выполнено: {amount} {code}")
    else:
        print(
            f"Покупка выполнена: {amount} {code} по курсу "
            f"{format_rate(result['rate'])} {base}/{code}"
        )
    _print_changes(result)
    if code != base:
        print(
            f"Оценочная стоимость покупки: "
            f"{format_money(result['estimated_value'])} {base}"
        )


def cmd_sell(session: Session, args: dict) -> None:
    result = usecases.sell(session.user_id, args["currency"], args["amount"])
    code, base = result["currency_code"], result["base"]
    amount = format_amount(result["amount"], code)
    if code == base:
        print(f"Вывод средств выполнен: {amount} {code}")
    else:
        print(
            f"Продажа выполнена: {amount} {code} по курсу "
            f"{format_rate(result['rate'])} {base}/{code}"
        )
    _print_changes(result)
    if code != base:
        print(f"Оценочная выручка: {format_money(result['estimated_value'])} {base}")


def cmd_get_rate(session: Session, args: dict) -> None:
    result = usecases.get_rate(args["from"], args["to"])
    updated = format_timestamp(result["updated_at"])
    print(
        f"Курс {result['from']}→{result['to']}: {format_rate(result['rate'])} "
        f"(обновлено: {updated})"
    )
    print(
        f"Обратный курс {result['to']}→{result['from']}: "
        f"{format_rate(result['reverse_rate'])}"
    )


def cmd_update_rates(session: Session, args: dict) -> None:
    result = usecases.update_rates(args.get("source"))
    log_path = SettingsLoader().get("parser_log_file")
    if result.has_errors:
        print(
            f"Update completed with errors (rates updated: {result.updated}). "
            f"Check {log_path} for details."
        )
    else:
        print(
            f"Update successful. Total rates updated: {result.updated}. "
            f"Last refresh: {result.last_refresh}"
        )


def cmd_show_rates(session: Session, args: dict) -> None:
    top = _parse_positive_int(args.get("top"), "top")
    result = usecases.show_rates(args.get("currency"), top, args.get("base"))
    print(f"Rates from cache (updated at {result['last_refresh']}):")
    table = PrettyTable(["Pair", "Rate", "Updated at", "Source", "Fresh"])
    table.align["Pair"] = "l"
    table.align["Rate"] = "r"
    for row in result["rows"]:
        table.add_row(
            [
                row["pair"],
                format_rate(row["rate"]),
                format_timestamp(row["updated_at"]),
                row["source"],
                "no" if row["stale"] else "yes",
            ]
        )
    print(table)
    if any(row["stale"] for row in result["rows"]):
        print("Часть курсов устарела. Выполните 'update-rates', чтобы обновить кеш.")


def cmd_currencies(session: Session, args: dict) -> None:
    for line in usecases.list_currencies():
        print(line)


def cmd_help(session: Session, args: dict, command_name: str | None = None) -> None:
    if command_name:
        command = COMMANDS.get(command_name)
        if command is None:
            raise ValueError(f"Неизвестная команда '{command_name}'")
        print(f"{command.name} — {command.description}")
        print(f"Использование: {command.usage}")
        for option in command.options:
            mark = "обязательный" if option.required else "необязательный"
            print(f"  --{option.name}: {option.description} ({mark})")
        return
    table = PrettyTable(["Команда", "Описание"])
    table.align = "l"
    for command in COMMANDS.values():
        table.add_row([command.usage, command.description])
    table.add_row(["exit", "выйти из программы"])
    print(table)


COMMANDS: dict[str, Command] = {
    command.name: command
    for command in (
        Command(
            "register",
            cmd_register,
            "зарегистрировать нового пользователя",
            (
                Option("username", True, "имя пользователя"),
                Option("password", True, "пароль, не короче 4 символов"),
            ),
        ),
        Command(
            "login",
            cmd_login,
            "войти в систему",
            (
                Option("username", True, "имя пользователя"),
                Option("password", True, "пароль"),
            ),
        ),
        Command("logout", cmd_logout, "выйти из учётной записи"),
        Command(
            "show-portfolio",
            cmd_show_portfolio,
            "показать кошельки и итоговую стоимость",
            (Option("base", False, "базовая валюта, по умолчанию USD"),),
        ),
        Command(
            "buy",
            cmd_buy,
            "купить валюту за USD (buy USD — пополнение)",
            (
                Option("currency", True, "код покупаемой валюты, например BTC"),
                Option("amount", True, "количество в единицах валюты"),
            ),
        ),
        Command(
            "sell",
            cmd_sell,
            "продать валюту, выручка зачисляется в USD",
            (
                Option("currency", True, "код продаваемой валюты"),
                Option("amount", True, "количество в единицах валюты"),
            ),
        ),
        Command(
            "get-rate",
            cmd_get_rate,
            "текущий курс одной валюты к другой",
            (
                Option("from", True, "исходная валюта, например USD"),
                Option("to", True, "целевая валюта, например BTC"),
            ),
        ),
        Command(
            "update-rates",
            cmd_update_rates,
            "обновить курсы из внешних API",
            (Option("source", False, "coingecko или exchangerate (по умолчанию все)"),),
        ),
        Command(
            "show-rates",
            cmd_show_rates,
            "курсы из локального кеша",
            (
                Option("currency", False, "показать только эту валюту"),
                Option("top", False, "N самых дорогих криптовалют"),
                Option("base", False, "пересчитать курсы к этой валюте"),
            ),
        ),
        Command("currencies", cmd_currencies, "список поддерживаемых валют"),
        Command("help", cmd_help, "справка: help [команда]"),
    )
}


# ---------- Выполнение ----------


def _execute(session: Session, tokens: list[str]) -> None:
    """Выполняет одну команду и превращает исключения в сообщения."""
    name, rest = tokens[0], tokens[1:]
    command = COMMANDS.get(name)
    try:
        if command is None:
            raise ValueError(f"Неизвестная команда '{name}'. Введите 'help'.")
        if command.name == "help":
            cmd_help(session, {}, rest[0] if rest else None)
            return
        command.handler(session, parse_options(command, rest))
    except InsufficientFundsError as error:
        print(error)
    except CurrencyNotFoundError as error:
        print(error)
        print(f"Поддерживаемые валюты: {', '.join(get_supported_codes())}")
        print("Справка: help get-rate, список валют: currencies")
    except ApiRequestError as error:
        print(error)
        print("Повторите попытку позже или проверьте подключение к сети.")
    except (ValutaTradeError, ValueError) as error:
        print(error)


def run_line(session: Session, line: str) -> bool:
    """Обрабатывает строку ввода; возвращает False, если нужно выйти."""
    try:
        tokens = shlex.split(line)
    except ValueError as error:
        print(f"Ошибка разбора команды: {error}")
        return True
    if not tokens:
        return True
    if tokens[0] in EXIT_COMMANDS:
        return False
    _execute(session, tokens)
    return True


def run_shell() -> None:
    """Интерактивная оболочка с сохранением сессии между командами."""
    session = Session()
    print(WELCOME)
    while True:
        prompt = f"[{session.username}] {PROMPT}" if session.username else PROMPT
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not run_line(session, line):
            break
    print("До свидания!")


def main() -> None:
    """Точка входа: оболочка без аргументов, одна команда — с аргументами."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    setup_logging()
    if len(sys.argv) > 1:
        _execute(Session(), sys.argv[1:])
        return
    run_shell()
