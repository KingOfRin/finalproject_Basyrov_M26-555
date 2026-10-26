# ValutaTrade Hub

Консольное приложение, имитирующее работу валютного кошелька. Пользователь
регистрируется, пополняет виртуальный USD-счёт, покупает и продаёт фиатные
и криптовалюты, смотрит портфель и актуальные курсы.

Система состоит из двух сервисов:

- **Core Service** — CLI, пользователи, портфели, сделки, чтение курсов из
  локального кэша `data/rates.json`;
- **Parser Service** — получает курсы из CoinGecko (криптовалюты) и
  ExchangeRate-API (фиат), пишет снимок в `data/rates.json` и историю
  замеров в `data/exchange_rates.json`.

## Структура проекта

```
finalproject_Basyrov_M26-555/
├── data/
│   ├── users.json             # пользователи (хеш пароля + соль)
│   ├── portfolios.json        # портфели и кошельки
│   ├── rates.json             # снимок курсов для Core Service (кэш)
│   └── exchange_rates.json    # история замеров Parser Service
├── demo/
│   └── demo_commands.txt      # сценарий для демонстрации
├── valutatrade_hub/
│   ├── logging_config.py      # формат, уровень и ротация логов
│   ├── decorators.py          # @log_action
│   ├── core/
│   │   ├── currencies.py      # Currency / FiatCurrency / CryptoCurrency + реестр
│   │   ├── exceptions.py      # доменные исключения
│   │   ├── models.py          # User, Wallet, Portfolio
│   │   ├── usecases.py        # бизнес-логика
│   │   └── utils.py           # валидация, форматирование, расчёт курсов
│   ├── infra/
│   │   ├── settings.py        # SettingsLoader (Singleton)
│   │   └── database.py        # DatabaseManager (Singleton, JSON-хранилище)
│   ├── parser_service/
│   │   ├── config.py          # ParserConfig: ключи, URL, списки валют
│   │   ├── api_clients.py     # BaseApiClient, CoinGeckoClient, ExchangeRateApiClient
│   │   ├── updater.py         # RatesUpdater
│   │   ├── storage.py         # чтение/запись rates.json и exchange_rates.json
│   │   └── scheduler.py       # периодическое обновление
│   └── cli/
│       └── interface.py       # команды CLI
├── main.py
├── Makefile
├── pyproject.toml
└── uv.lock
```

## Установка и запуск

Нужны Python 3.12+ и [uv](https://docs.astral.sh/uv/).

```bash
make install        # uv sync — установка зависимостей
make project        # uv run project — интерактивная оболочка
make lint           # uv run ruff check .
make build          # uv build — сборка пакета в dist/
make package-install  # установка собранного пакета как утилиты
```

Без `make`: `uv sync`, затем `uv run project` (или `uv run python main.py`).

Одну команду можно выполнить без входа в оболочку:

```bash
uv run project get-rate --from USD --to BTC
uv run project update-rates
```

Сессия (`login`) живёт, пока открыта интерактивная оболочка.

## Команды CLI

| Команда | Назначение |
|---|---|
| `register --username <str> --password <str>` | регистрация (пароль ≥ 4 символов) |
| `login --username <str> --password <str>` | вход |
| `logout` | выход из учётной записи |
| `show-portfolio [--base <str>]` | кошельки и итог в базовой валюте (по умолчанию USD) |
| `buy --currency <str> --amount <float>` | покупка за USD; `buy --currency USD` — пополнение |
| `sell --currency <str> --amount <float>` | продажа, выручка зачисляется в USD |
| `get-rate --from <str> --to <str>` | курс с учётом TTL кэша |
| `update-rates [--source coingecko\|exchangerate]` | немедленное обновление курсов |
| `show-rates [--currency <str>] [--top <int>] [--base <str>]` | курсы из кэша |
| `currencies` | список поддерживаемых валют |
| `help [команда]`, `exit` | справка, выход |

Поддерживаемые валюты: USD, EUR, GBP, RUB, CNY (фиат) и BTC, ETH, SOL (крипто).

### Пример сессии

```
> register --username alice --password 1234
Пользователь 'alice' зарегистрирован (id=1). Войдите: login --username alice --password ****
> login --username alice --password 1234
Вы вошли как 'alice'
[alice] > buy --currency USD --amount 5000
Пополнение выполнено: 5000.00 USD
Изменения в портфеле:
- USD: было 0.00 → стало 5000.00
[alice] > buy --currency BTC --amount 0.05
Покупка выполнена: 0.0500 BTC по курсу 79840.00 USD/BTC
Изменения в портфеле:
- BTC: было 0.0000 → стало 0.0500
- USD: было 5000.00 → стало 1008.00
Оценочная стоимость покупки: 3,992.00 USD
[alice] > sell --currency BTC --amount 0.01
Продажа выполнена: 0.0100 BTC по курсу 79840.00 USD/BTC
Изменения в портфеле:
- BTC: было 0.0500 → стало 0.0400
- USD: было 1008.00 → стало 1806.40
Оценочная выручка: 798.40 USD
[alice] > show-portfolio
Портфель пользователя 'alice' (база: USD):
- BTC: 0.0400  → 3,193.60 USD
- USD: 1806.40  → 1,806.40 USD
---------------------------------
ИТОГО: 5,000.00 USD
[alice] > get-rate --from USD --to BTC
Курс USD→BTC: 0.00001253 (обновлено: 2026-10-26 20:19:48)
Обратный курс BTC→USD: 79840.00
[alice] > sell --currency BTC --amount 1
Недостаточно средств: доступно 0.0400 BTC, требуется 1.0000 BTC
```

### Правила торговли

Все сделки проходят через USD-кошелёк:

- `buy X` списывает `amount × курс(X→USD)` с USD-кошелька и зачисляет `amount`
  на кошелёк `X` (кошелёк создаётся автоматически). Если USD не хватает —
  `InsufficientFundsError`;
- `sell X` списывает `amount` с кошелька `X` и зачисляет выручку на USD;
- `buy --currency USD` — пополнение счёта, `sell --currency USD` — вывод.

Сделка не записывается на диск, если на любом шаге возникла ошибка.

## Курсы, кэш и TTL

- `data/rates.json` — последний курс по каждой паре `XXX_USD` с полями
  `rate`, `updated_at`, `source`, плюс общий `last_refresh`. Курс между любыми
  двумя валютами считается через USD.
- Курс свежий, если он моложе `rates_ttl_seconds` (по умолчанию 300 секунд).
- `get-rate`, `buy` и `sell` при устаревшем курсе сами запускают Parser Service.
  Если обновить не удалось — `ApiRequestError` с указанием причины; если курса
  нет совсем — «Курс USD→BTC недоступен. Повторите попытку позже.»
- `show-portfolio` и `show-rates` читают только кэш и предупреждают, если
  курсы устарели.

## Parser Service

- **CoinGecko** — публичный доступ, ключ не нужен. Тикеры переводятся в ID
  через `CRYPTO_ID_MAP` (`BTC → bitcoin`).
- **ExchangeRate-API** — ключ берётся из переменной окружения
  `EXCHANGERATE_API_KEY`. Удобнее всего положить его в `.env` (файл в git
  не попадает):

  ```bash
  cp .env.example .env   # и вставить ключ
  ```

  Если ключ не задан, используется открытый эндпоинт `open.er-api.com`
  (тот же формат, обновляется раз в сутки), в лог пишется предупреждение.

Запуск:

```bash
uv run project update-rates                       # вручную, все источники
uv run project update-rates --source coingecko    # один источник
make parser                                       # по расписанию (интервал из конфига)
uv run valutatrade-parser --interval 60           # свой интервал
uv run valutatrade-parser --once                  # одно обновление
```

Падение одного источника не останавливает обновление: данные остальных
сохраняются, а итог помечается «Update completed with errors». Запись файлов
атомарная (временный файл → `os.replace`). История в `exchange_rates.json`
не дублируется: `id = <FROM>_<TO>_<ISO-UTC timestamp>`.

## Конфигурация

Секция `[tool.valutatrade]` в `pyproject.toml` (читает `SettingsLoader`):
пути к JSON-файлам и логам, `rates_ttl_seconds`, `default_base_currency`,
формат логов, параметры ротации, `parser_update_interval_seconds`.

Переменные окружения: `EXCHANGERATE_API_KEY`, `VALUTATRADE_LOG_LEVEL=DEBUG`
(подробные логи), `VALUTATRADE_HOME` (другой каталог с `data/` и `logs/`).

## Логи

- `logs/actions.log` — операции `REGISTER`, `LOGIN`, `BUY`, `SELL`
  (декоратор `@log_action`; для `buy`/`sell` пишется и «было→стало»):

  ```
  INFO 2026-10-26T23:19:48 BUY user='alice' currency='BTC' amount=0.0500 rate=79840.00 base='USD' wallet=0.0000→0.0500 result=OK
  ```

- `logs/parser.log` — шаги Parser Service.

Ротация по размеру: 1 МБ, хранится 5 архивных файлов.

## Демо

Сценарий полного цикла с ошибками лежит в `demo/demo_commands.txt`:

```powershell
Get-Content demo/demo_commands.txt | uv run project   # PowerShell
uv run project < demo/demo_commands.txt               # bash
```

Запись демо: [asciinema](https://asciinema.org/) (Linux/macOS/WSL) —
`asciinema rec demo.cast`, на Windows — [ScreenToGif](https://www.screentogif.com/).
