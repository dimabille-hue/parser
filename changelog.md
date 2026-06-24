# CHANGELOG — TriggerParse Engine

Все значимые изменения фиксируются в этом файле.  
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).

---

## [3.0] — текущая версия

### Добавлено

**Движок и парсинг**
- `LimitedLog` — класс-обёртка над `list` с ограничением числа строк debug-лога (`MAX_DEBUG_LOG_LINES = 20000`). Защита от перерасхода памяти на больших файлах
- `normalize_whitespace()` — предобработка текста: неразрывные пробелы (`\u00a0`), BOM, табуляции, переносы строк, zero-width символы → единый пробел
- `tokenize_text()` — настраиваемая токенизация через `tokenizer.split_by` в конфиге (`whitespace` / `whitespace_and_punctuation`)
- `decode_bytes()` — автоопределение кодировки: `chardet` → `utf-8-sig` → `utf-8` → `cp1251` → `latin-1`
- `detect_duplicates()` — пометка дублирующихся записей кодом ошибки по ключевому полю
- `run_tests()` — запуск регрессионных тест-кейсов из секции `tests` конфига
- `_fmt_uptime()` — форматирование секунд в читаемый вид (`1д 2ч 3м 4с`)
- `_csv_escape()` — защита от CSV-инъекции: значения начинающиеся с `= + - @ TAB CR` получают префикс `'`

**Конфиг**
- `csv_column` в триггере — явный маппинг поля в CSV-колонку; несколько триггеров могут писать в одну колонку
- `priority` в `heuristics` — детерминированный порядок срабатывания эвристик
- `collector.guard` — коллектор прерывается если следующий токен является явным триггером
- `stop_words` и `stop_word_error` на уровне триггера
- `tokenizer.split_by` — режим токенизации
- `dedup` — настройки детектора дублей (`key`, `error_code`, `case_sensitive`)
- `process_timeout` — лимит времени обработки в секундах
- `tests` — встроенные регрессионные тест-кейсы
- Новые шаги нормализации: `replace_char:FROM->TO`, `replace_char:internal:FROM->TO`, `normalize_number`, `to_int`, `to_float:N`, `pad_left:N`, `pad_right:N`
- `replace_dot_after_keywords`, `replace_space_before_keywords` — новые адресные шаги

**Веб-интерфейс**
- Вкладка «Результаты»: статистика, заполненность полей, топ-ошибок, распределение значений, предпросмотр таблицы, кнопки CSV/JSON/Excel
- Вкладка «Тесты»: запуск тест-кейсов прямо в браузере
- Страница `/docs` — интерактивная документация конфига (генерируется из кода)
- Live-валидация JSON в textarea конфигурации (подсветка, бейджи, блокировка кнопки)
- Интерактивный debug-лог: раскрываемые записи, фильтры по типу события, поиск
- Прогресс-бар обработки через SSE (`/progress`)
- Распределение значений по полям (карточки с повторами)
- Секция «Потерянные токены» (при `log_suspicious: true`)
- Кнопка «Скачать текущий конфиг» (`/download_config`)
- Кнопка «⊗ Сбросить» — очистка результатов без перезапуска сервера
- Favicon — SVG-иконка «T» в стиле интерфейса

**Экспорт**
- JSON-экспорт (`/download/<token>?fmt=json`)
- Excel-экспорт через `openpyxl` (`/download/<token>?fmt=xlsx`) с форматированием

**Операционное**
- `setup_logging()` — логирование через `logging` с ротацией файлов (`engine.log`, 5 МБ × 3)
- Базовая HTTP-аутентификация через переменные окружения `TRIGGERPARSE_USER` / `TRIGGERPARSE_PASS`
- Обработка запросов в `ThreadPoolExecutor` с таймаутом (защита от зависания)
- `/health` эндпоинт — статус, uptime, имя конфига (без авторизации)
- Все импорты на верхнем уровне (был ряд локальных `import` внутри функций)

### Исправлено
- Сегментация: `continuation_heuristics` больше не схлопывает все записи в одну (защита `starts_with_trigger`)
- `levenshtein_distance`: итеративная реализация без рекурсии
- Хардкод маппинга `фио/орг` убран из кода в конфиг
- `last_field` в парсере — эвристики работают после закрытия multi-token поля
- SSE `/progress`: дедлайн через `time.monotonic()`, ловит `BrokenPipeError`, интервал 0.25с
- Guard `files[0][0] if files else 'unknown'` — защита от IndexError при пустом multipart
- CSV-инъекция: `_csv_escape()` на каждое значение перед `writerow()`
- `suspicious_log`: тип изменён с `set` на `Counter` (считает вхождения)
- `debug_log`: тип изменён с `list` на `LimitedLog` (ограничение размера)
- Все `print()` заменены на `log.*`
- HTML-шаблон использует `string.Template.safe_substitute` — устойчив к `$` в данных

---

## [2.1] — исходная версия

### Было
- Базовый парсер: fuzzy/exact/regex поиск триггеров, Левенштейн, эвристики
- Веб-интерфейс: три вкладки (Основное, Конфигурация, Отладка)
- Выгрузка CSV
- `record_detection` с `continuation_heuristics`
- `multi_token` для кадастровых номеров
- `collector` для многотокенных значений
- Встроенные предикаты: `starts_upper`, `has_letter`, `looks_like_number_colon_dot`, `is_part_of_number_colon_dot`, `any`
- Шаги нормализации: `strip`, `collapse_spaces`, `remove_dots`, `remove_trailing_dot`, `remove_spaces`, `uppercase`, `lowercase`, `digits_only`, `dots_to_colons`, `replace_internal_dot`, `apply_replacements`, `replace_dot_before_keywords`, `regex_sub`
- Валидация значений: `not_empty`, `word_count`, `regex`
- `validate_config()` — проверка структуры конфига
- `compile_config()` — компиляция предикатов и регулярок
- `AppState` с threading.Lock — потокобезопасное хранение состояния
- Ограничение размера файла 32 МБ
- Подавление HTTP-лога в stderr