# TriggerParse Engine v3.0 — Справочник функций

> Полное описание всех функций, классов и методов движка.  
> Порядок соответствует порядку в файле `engine_web.py`.

---

## Содержание

1. [Логирование](#1-логирование)
2. [Класс AppState](#2-класс-appstate)
3. [Вспомогательные функции](#3-вспомогательные-функции)
4. [Встроенные предикаты](#4-встроенные-предикаты)
5. [Валидация и компиляция конфига](#5-валидация-и-компиляция-конфига)
6. [Алгоритм Левенштейна](#6-алгоритм-левенштейна)
7. [Классификатор триггеров](#7-классификатор-триггеров)
8. [Нормализация значений](#8-нормализация-значений)
9. [Предобработка текста](#9-предобработка-текста)
10. [Ядро парсера](#10-ядро-парсера)
11. [Экспорт результатов](#11-экспорт-результатов)
12. [Постобработка и статистика](#12-постобработка-и-статистика)
13. [Документация и HTML-рендеринг](#13-документация-и-html-рендеринг)
14. [HTTP-сервер](#14-http-сервер)
15. [Точка входа](#15-точка-входа)
16. [Схема вызовов](#16-схема-вызовов)

---

## 1. Логирование

### `setup_logging(level)`

```python
def setup_logging(level: int = logging.INFO) -> logging.Logger
```

Инициализирует единственный логгер приложения с именем `"triggerparse"`.

**Хендлеры:**

| Хендлер | Уровень | Куда пишет |
|---------|---------|------------|
| `StreamHandler` | INFO и выше | `stdout` (консоль) |
| `RotatingFileHandler` | DEBUG и выше | `engine.log`, ротация 5 МБ × 3 файла |

**Защита от дублирования:** если логгер уже имеет хендлеры — возвращает существующий без добавления новых. Это важно при перезагрузке модуля в тестах.

**Формат записи:**
```
2025-06-11 10:23:41  INFO     Анализ: 2 файл(ов), debug=False
2025-06-11 10:23:41  WARNING  Файл 'data.txt': нестандартная кодировка cp1251
```

**Параметры:**

| Параметр | Тип | По умолч. | Описание |
|----------|-----|-----------|----------|
| `level` | int | `logging.INFO` | Минимальный уровень для консоли |

**Возвращает:** `logging.Logger` — готовый логгер.

**Использование:**
```python
log = setup_logging()
log.info("Сервер запущен")
log.warning("Нестандартная кодировка")
log.debug("Токен: 'Фио.' -> триггер 'фио'")
log.error("Превышен таймаут")
```

---

### `LimitedLog`

```python
class LimitedLog(list)
```

Список строк debug-лога с ограничением размера. Drop-in замена обычного `list` —
все вызовы `debug_log.append(...)` в парсере работают без изменений.

После достижения `max_lines`:
- Добавляет единственный маркер усечения:
  `*** ЛОГ ОБРЕЗАН: достигнут лимит N строк... ***`
- Устанавливает флаг `truncated = True`
- Считает отброшенные строки в `dropped`
- Пишет `WARNING` в серверный лог

**Атрибуты:**

| Атрибут | Тип | Описание |
|---------|-----|----------|
| `max_lines` | int | Лимит строк (по умолч. `MAX_DEBUG_LOG_LINES = 20000`) |
| `truncated` | bool | `True` если лог был обрезан |
| `dropped` | int | Количество отброшенных строк |

**Пример:**
```python
log = LimitedLog(max_lines=100)
for i in range(200):
    log.append(f'строка {i}')
# len(log) == 101 (100 строк + 1 маркер)
# log.truncated == True
# log.dropped == 100
```

**Связанные константы:**

| Константа | Значение | Описание |
|-----------|----------|----------|
| `MAX_DEBUG_LOG_LINES` | 20000 | Глобальный лимит строк debug-лога |
| `MAX_SUSPICIOUS_SHOWN` | 50 | Сколько потерянных токенов показывать в UI |
| `MAX_VALUE_DIST_SHOWN` | 8 | Сколько повторов показывать в распределении значений |

Можно переопределить при создании: `LimitedLog(max_lines=5000)`.

---

## 2. Класс AppState

```python
class AppState
```

Единственный экземпляр `_state = AppState()` хранит всё изменяемое состояние сервера. Все методы потокобезопасны — защищены `threading.Lock()`.

**Почему класс, а не глобальные переменные:** при параллельных HTTP-запросах глобальные переменные создают race condition. `AppState` гарантирует атомарность операций через блокировку.

---

### `AppState.set_config(raw, compiled)`

```python
def set_config(self, raw: dict, compiled: dict)
```

Сохраняет пару: исходный JSON-конфиг и скомпилированный (с предкомпилированными функциями).

| Параметр | Описание |
|----------|----------|
| `raw` | Чистый Python-словарь из JSON — для отображения в интерфейсе |
| `compiled` | Результат `compile_config(raw)` — содержит скомпилированные регулярки и функции-предикаты |

---

### `AppState.get_config()`

```python
def get_config(self) -> tuple[dict | None, dict | None]
```

Возвращает `(raw_config, compiled_config)`. Оба `None` если конфиг не загружен.

---

### `AppState.clear_config()`

```python
def clear_config(self)
```

Сбрасывает конфиг. Используется при ошибке загрузки.

---

### `AppState.set_debug(log, name)` / `get_debug()`

```python
def set_debug(self, log: list, name: str)
def get_debug(self) -> tuple[list | None, str | None]
```

Сохраняет/возвращает список строк debug-лога и имя файла для скачивания.

---

### `AppState.set_result(...)` / `get_result()`

```python
def set_result(self,
    csv_bytes:  bytes,
    json_bytes: bytes,
    xlsx_bytes: bytes | None,
    csv_name:   str,
    stats:      dict,
    preview:    list,
    token:      str
)
def get_result(self) -> tuple[bytes, bytes, bytes|None, str, dict, list, str]
```

Сохраняет результаты последнего успешного анализа: байты трёх форматов экспорта,
статистику, первые 50 записей для предпросмотра и одноразовый токен ссылки.

| Параметр | Тип | Описание |
|----------|-----|----------|
| `csv_bytes` | bytes | CSV в кодировке UTF-8 BOM |
| `json_bytes` | bytes | JSON (массив объектов) |
| `xlsx_bytes` | bytes\|None | XLSX или `None` если openpyxl не установлен |
| `csv_name` | str | Имя файла для скачивания |
| `stats` | dict | Результат `compute_stats()` |
| `preview` | list | Первые 50 записей для предпросмотра |
| `token` | str | 12-символьный md5-токен для URL скачивания |

---

### `AppState.set_progress(pct, msg, done)` / `get_progress()`

```python
def set_progress(self, pct: int, msg: str, done: bool = False)
def get_progress(self) -> dict
```

Управляет прогрессом обработки для SSE-стрима `/progress`.

| Поле | Тип | Описание |
|------|-----|----------|
| `pct` | int | Процент выполнения 0–100 |
| `msg` | str | Текстовое сообщение для UI |
| `done` | bool | `True` — обработка завершена, клиент закрывает EventSource |

`get_progress()` возвращает `{'pct':0,'msg':'','done':True}` по умолчанию если прогресс ещё не установлен — это означает «ничего не происходит».

---

## 3. Вспомогательные функции

### `decode_bytes(data)`

```python
def decode_bytes(data: bytes) -> tuple[str, str]
```

Декодирует байты файла в строку с автоопределением кодировки. Возвращает `(text, encoding_name)`.

**Цепочка попыток:**

| Приоритет | Метод | Условие |
|-----------|-------|---------|
| 1 | `chardet` | Если установлен и уверенность ≥ 70% |
| 2 | `utf-8-sig` | UTF-8 с BOM (файлы из Excel) |
| 3 | `utf-8` | Стандартный UTF-8 |
| 4 | `cp1251` | Windows-кириллица |
| 5 | `latin-1` | Никогда не падает (последний резерв) |

**Пример:**
```python
text, enc = decode_bytes(open("data.txt", "rb").read())
# text = "Яч 1. Ном. 418.4..."
# enc  = "utf-8"
```

Если кодировка не `utf-8` и не `utf-8-sig` — сервер показывает предупреждение в интерфейсе.

---

### `try_load_default_config()`

```python
def try_load_default_config()
```

Загружает `default_config.json` при старте сервера если файл существует.

**Последовательность действий:**
1. Проверяет существование `DEFAULT_CONFIG_FILE`
2. Читает JSON
3. Вызывает `validate_config(raw)` — при ошибках логирует и прерывает
4. Вызывает `compile_config(raw)` — компилирует предикаты и регулярки
5. Сохраняет в `_state.set_config(raw, compiled)`

При любой ошибке логирует её и оставляет конфиг пустым — сервер запускается, но требует загрузки конфига через интерфейс.

---

### `_escape_html(s)`

```python
def _escape_html(s: str) -> str
```

Экранирует символы `&`, `<`, `>`, `"` для безопасной вставки строки в HTML.  
Используется везде где в HTML вставляются данные из конфига или результатов парсинга — защита от XSS.

```python
_escape_html('a < b & c > "d"')
# → 'a &lt; b &amp; c &gt; &quot;d&quot;'
```

---

## 4. Встроенные предикаты

Предикаты — простые функции `(str) -> bool`. Используются в `detect_by`, `token_rule`, `unless`.

### `_token_starts_upper(token)`

```python
def _token_starts_upper(token: str) -> bool
```

`True` если первый **буквенный** символ токена (после удаления пунктуации по краям) — заглавная буква, и токен не является чисто числовым.

```python
_token_starts_upper("Смирнов.")   # True
_token_starts_upper("смирнов.")   # False
_token_starts_upper("123.")       # False (цифры)
_token_starts_upper("А1Б")        # True
```

**Зачем нужно:** определяет начало слова-фамилии или названия организации без явного триггера.

---

### `_token_has_letter(token)`

```python
def _token_has_letter(token: str) -> bool
```

`True` если токен содержит хотя бы один буквенный символ.

```python
_token_has_letter("418.4")    # False
_token_has_letter("418а")     # True
_token_has_letter("Москва.")  # True
```

**Зачем нужно:** широкий предикат для эвристик — «любой токен с буквами» означает текстовое значение, а не число.

---

### `_token_is_number_colon_dot(token)`

```python
def _token_is_number_colon_dot(token: str) -> bool
```

`True` если токен после удаления пробелов состоит **только** из цифр, букв (кириллица/латиница), точек и двоеточий.

```python
_token_is_number_colon_dot("59.34")        # True
_token_is_number_colon_dot("59:34:640098") # True
_token_is_number_colon_dot("59.34а")       # True
_token_is_number_colon_dot("Москва")       # True (только буквы)
_token_is_number_colon_dot("59,34")        # False (запятая)
```

**Зачем нужно:** определяет токены-части кадастрового номера для `multi_token`, а также срабатывание эвристики кадастра без триггера.

---

### `_token_is_part_of_number_colon_dot(token)`

```python
def _token_is_part_of_number_colon_dot(token: str) -> bool
```

То же что `_token_is_number_colon_dot`, но дополнительно требует наличия хотя бы одной цифры **или** точки/двоеточия. Исключает чисто буквенные токены.

```python
_token_is_part_of_number_colon_dot("59.34")   # True
_token_is_part_of_number_colon_dot("АБВ")     # False (нет цифр/точек)
_token_is_part_of_number_colon_dot("А59")     # True
```

**Зачем нужно:** при сборке кадастрового номера через `multi_token` нужно принимать части `"59.34"`, `"640098"`, `"498."` но **не** принимать слово `"Адр."` которое стоит следом — иначе оно поглотится в кадастр.

---

### `_token_any(token)`

```python
def _token_any(token: str) -> bool
```

`True` для любого непустого токена.

```python
_token_any("что угодно")  # True
_token_any("")             # False
_token_any("  ")           # False (только пробелы)
```

**Зачем нужно:** используется в `collector` когда нужно взять ровно один следующий токен независимо от его содержимого (номер ячейки, порядковый номер).

---

## 5. Валидация и компиляция конфига

### `validate_config(config)`

```python
def validate_config(config: dict) -> list[str]
```

Проверяет структуру конфига и возвращает список ошибок (пустой если всё в порядке).

**Что проверяется:**

| Раздел | Проверки |
|--------|----------|
| Корень | Наличие `parser_name`, `csv_columns`, `triggers`; типы всех полей |
| `triggers` | Каждый триггер имеет `aliases` (непустой список) и `search_mode` (`fuzzy`/`exact`/`regex`) |
| `csv_column` | Если задано — должно быть в `csv_columns` |
| `heuristics.priority` | Если задано — должно быть целым числом |
| `stop_words` триггера | Должен быть списком |
| `tokenizer.split_by` | Только `"whitespace"` или `"whitespace_and_punctuation"` |
| `dedup` | Поле `key` обязательно и должно быть в `csv_columns` |
| `tests` | Каждый кейс должен иметь `input` и `expect` |
| `max_distance`, `require_first_char`, `stop_words` | Типы |
| `record_detection` | Наличие `trigger`; `mode` только `"trigger"` |

**Пример:**
```python
errs = validate_config({"parser_name": "Test", "csv_columns": ["a"], "triggers": {}})
# errs = ["'triggers' должен быть непустым объектом"]
```

**Не вызывает исключений** — только возвращает список строк. Это позволяет показать все ошибки сразу, а не останавливаться на первой.

---

### `_compile_predicate_chain(expr)`

```python
def _compile_predicate_chain(expr: str) -> Callable[[str], bool]
```

Компилирует строку-предикат вида `"pred1 | pred2 | regex:ПАТТЕРН"` в функцию `(str) -> bool`.

**Алгоритм:**
1. Разбивает по `|`
2. Для каждой части: если начинается с `regex:` — компилирует регулярку; иначе ищет в `BUILTIN_PREDICATES`
3. Если частей одна — возвращает её напрямую
4. Если несколько — возвращает лямбду `any(f(t) for f in funcs)` (логическое ИЛИ)

**Важно:** все переменные в лямбдах захватываются через default-аргументы (`p=compiled`) — это предотвращает классическую Python-ловушку с замыканиями в циклах.

```python
fn = _compile_predicate_chain("starts_upper | regex:\\d+")
fn("Иванов")   # True (starts_upper)
fn("123abc")   # True (regex)
fn("abc")      # False
```

---

### `_compile_validation(rule)`

```python
def _compile_validation(rule: str) -> Callable[[str], bool]
```

Компилирует строку правила валидации в функцию `(str) -> bool`.

| Правило | Компилируется в |
|---------|----------------|
| `"not_empty"` | `lambda v: bool(v.strip())` |
| `"regex:ПАТТЕРН"` | `lambda v: bool(re.fullmatch(pattern, v))` |
| `"word_count:min,max"` | `lambda v: min <= len(v.split()) <= max` |
| Всё остальное | `lambda v: True` (всегда проходит) |

---

### `compile_config(raw_config)`

```python
def compile_config(raw_config: dict) -> dict
```

Принимает чистый JSON-словарь, возвращает **глубокую копию** с добавленными скомпилированными объектами.

**Что добавляется:**

| Поле | Что компилируется |
|------|-------------------|
| `config['stop_words']` | `list → set` для O(1) поиска |
| `config['tokenizer']` | Устанавливает дефолты |
| `trigger['csv_column']` | Устанавливает дефолт = имя триггера |
| `trigger['_stop_words']` | `list → set` стоп-слов триггера |
| `trigger['_compiled_regex']` | `re.compile(aliases[0])` для режима `regex` |
| `trigger['validation']['_func']` | Через `_compile_validation()` |
| `heuristics['_detect']` | Через `_compile_predicate_chain()` |
| `heuristics['_unless']` | Через `_compile_predicate_chain()` |
| `heuristics['_token_rule']` | Через `_compile_predicate_chain()` |
| `collector['_token_rule']` | Через `_compile_predicate_chain()` |
| `multi_token['_token_rule']` | Через `_compile_predicate_chain()` |
| `heuristics['priority']` | Устанавливает дефолт 100 |

**После компиляции** триггеры сортируются по `heuristics.priority` — это обеспечивает детерминированный порядок срабатывания эвристик независимо от порядка ключей в JSON.

**Почему deepcopy:** raw_config хранится в `AppState` для отображения в интерфейсе. Если компилировать на месте — в JSON попадут скомпилированные функции, которые нельзя сериализовать через `json.dumps`.

```python
cfg = compile_config(raw)
# cfg['triggers']['фио']['_stop_words']  → frozenset()
# cfg['triggers']['фио']['heuristics']['_detect']  → <function>
```

---

## 6. Алгоритм Левенштейна

### `levenshtein_distance(s1, s2)`

```python
def levenshtein_distance(s1: str, s2: str) -> int
```

Вычисляет редакционное расстояние между двумя строками — минимальное количество односимвольных операций (вставка, удаление, замена) для преобразования `s1` в `s2`.

**Реализация:** итеративная с одной строкой состояния (оптимизация памяти O(min(n,m)) вместо O(n×m)). Без рекурсии — более длинная строка всегда в `s1` через простой swap `s1, s2 = s2, s1`.

```python
levenshtein_distance("фио", "фио")    # 0
levenshtein_distance("фио", "фиo")    # 1 (латинская 'o')
levenshtein_distance("ном", "нoмер")  # 2
levenshtein_distance("кад", "када")   # 1
```

**Используется в:** `build_classifier` для fuzzy-режима сравнения токенов с алиасами триггеров.

---

## 7. Классификатор триггеров

### `build_classifier(config, debug_log)`

```python
def build_classifier(
    config:    dict,
    debug_log: Optional[list] = None
) -> Callable[[str], Optional[str]]
```

Фабричная функция — возвращает замыкание `classifier(raw_token) -> trigger_name | None`.

**Внутреннее состояние замыкания:**
- `triggers`, `max_dist`, `require_first`, `stop_words` — извлечены из конфига
- `_cache: dict[str, Optional[str]]` — кеш результатов
- `use_cache: bool` — `True` если `debug_log is None`

**Алгоритм классификации одного токена:**

```
1. Проверить кеш → вернуть cached если есть
2. Убрать небуквенные символы из токена → clean
3. Если clean пустой → None (кешируем)
4. Если clean ∈ stop_words → None (кешируем)
5. Для каждого триггера:
   exact:  если clean совпадает с любым алиасом → вернуть trigger (кешируем)
   regex:  если _compiled_regex.fullmatch(raw_token) → вернуть trigger (кешируем)
   fuzzy:  для каждого алиаса:
     - если require_first и первые символы разные → пропустить
     - вычислить levenshtein_distance(clean, alias_clean)
     - обновить best_trigger / best_distance
6. Если best_distance <= max_dist → вернуть best_trigger (кешируем)
7. Иначе → None (кешируем)
```

**Кеширование:** один и тот же токен (например `"Фио."`) встречается в тексте сотни раз. Кеш превращает повторные вызовы из O(триггеры × длина) в O(1) lookup. **Отключается при отладке** — иначе debug_log не записывал бы повторные классификации.

**Параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `config` | dict | Скомпилированный конфиг |
| `debug_log` | list\|None | Если передан — каждый шаг логируется; кеш отключается |

**Возвращает:** функцию `classifier(str) -> Optional[str]` — имя триггера или `None`.

> **Внутренняя функция `classifier(raw_token)`:** само замыкание.
> Содержит кеш `_cache` и флаг `use_cache`. Не вызывается напрямую —
> только через возвращённую фабрикой функцию.

---

## 8. Нормализация значений

### `_apply_normalization_step(value, step, replacements)`

```python
def _apply_normalization_step(
    value:        str,
    step:         str,
    replacements: Optional[dict]
) -> str
```

Применяет **один шаг** нормализации к строке. Диспетчер по имени шага.

Полный список шагов и их поведение описан в [CONFIG_GUIDE.md, раздел 5](#).

**Группы шагов:**

| Группа | Шаги |
|--------|------|
| Базовые | `strip`, `collapse_spaces`, `remove_dots`, `remove_trailing_dot`, `remove_spaces`, `uppercase`, `lowercase`, `digits_only` |
| Замена символов | `replace_char:FROM->TO`, `replace_char:internal:FROM->TO` |
| Адресные | `replace_dot_before_keywords:...`, `replace_dot_after_keywords:...`, `replace_space_before_keywords:...` |
| Числовые | `normalize_number`, `to_int`, `to_float:N`, `pad_left:N`, `pad_right:N` |
| Словарные | `apply_replacements` |
| Регулярные | `regex_sub:PATTERN->REPL` |

**Неизвестный шаг:** возвращает `value` без изменений — не падает с ошибкой.

---

### `_cap_kw(m)`

```python
def _cap_kw(m: re.Match) -> str
```

Вспомогательная функция-замена для `re.sub` в шаге `replace_space_before_keywords`.
Возвращает `', '` — запятая и пробел перед ключевым словом.
Вызывается только внутри `_apply_normalization_step`, не предназначена для прямого использования.

---

### `make_normalizer(pipeline, replacements)`

```python
def make_normalizer(
    pipeline:     list,
    replacements: Optional[dict] = None
) -> Callable[[str], str]
```

Фабрика — создаёт функцию нормализации из списка шагов.

**Пример:**
```python
norm = make_normalizer(
    ["strip", "remove_trailing_dot", "replace_char:internal:.>/"],
    replacements=None
)
norm("418.4.")   # → "418/4"
norm("6.8.")     # → "6/8"
```

Возвращённая функция применяет шаги последовательно и в конце вызывает `.strip()`.

---

## 9. Предобработка текста

### `normalize_whitespace(text)`

```python
def normalize_whitespace(text: str) -> str
```

Нормализует все виды пробельных символов к единому пробелу.

**Что убирается без замены:**
- `\ufeff` — BOM (метка порядка байт, стоит в начале файлов UTF-8 из Windows)
- `\u00ad` — мягкий перенос (используется в типографике)
- `\u200b`, `\u200c`, `\u200d` — zero-width символы (невидимые разделители из Word)

**Что заменяется на пробел:**
- `\u00a0` — неразрывный пробел (очень частый в текстах из Word)
- `\u2009`, `\u202f` — узкий и узкий неразрывный пробел
- `\u2002`, `\u2003` — en-space и em-space
- `\t` — табуляция
- `\r`, `\n` — переносы строк

**Финально:** несколько подряд идущих пробелов схлопываются в один.

**Зачем важно:** тексты из Word, Excel, PDF содержат разнообразные пробельные символы. Токенизатор `text.split()` не разбивает по `\u00a0` — без этой функции `"Ленинградская\u00a0область"` воспринимается как один токен.

---

### `tokenize_text(text, config)`

```python
def tokenize_text(text: str, config: dict) -> list[str]
```

Разбивает текст на токены согласно настройке `tokenizer.split_by` в конфиге.

| Режим | Реализация | Применение |
|-------|------------|------------|
| `"whitespace"` | `text.split()` | Стандартный (по умолчанию) |
| `"whitespace_and_punctuation"` | `re.split(r'(\s+\|(?<=[^\s]),)', text)` | Текст с запятыми-разделителями |

---

### `clean_text(text)`

```python
def clean_text(text: str) -> str
```

Комплексная очистка текста перед токенизацией. Выполняет два действия последовательно:

1. **Удаление `[...]`** — убирает всё содержимое квадратных скобок включая вложенные `[[...]]`. Используется `while`-цикл: повторяет замену пока строка изменяется.
2. **`normalize_whitespace()`** — нормализует пробелы.

```python
clean_text("Яч [примечание] 1. [[двойные]] скобки.")
# → "Яч   1.   скобки."   (затем normalize_whitespace)
# → "Яч 1. скобки."
```

---

## 10. Ядро парсера

### `parse_single_record(tokens, config, classify, suspicious_log, debug_log)`

```python
def parse_single_record(
    tokens:        list,
    config:        dict,
    classify:      Callable[[str], Optional[str]],
    suspicious_log: Counter,
    debug_log:     Optional[LimitedLog] = None
) -> dict
```

Парсит один список токенов в словарь `{поле: значение}`.

**Принимает готовый `classify`** — не создаёт его внутри. Это ключевое для производительности: классификатор с кешем создаётся один раз на весь файл и передаётся сюда.

**Приоритет обработки каждого токена:**

```
1. Collector-режим (активный сборщик):
   - Guard-проверка: является ли токен явным триггером?
     Если да → прерываем сбор (переобрабатываем токен)
   - Если token_rule(токен) и count < limit → добавляем в буфер
   - Иначе → закрываем поле, переобрабатываем токен

2. Стоп-слово (глобальное или уровня поля):
   - Выбрасываем токен, добавляем error_code в errors

3. Явный триггер (classify(token) != None):
   - Сохраняем текущее поле (save_field)
   - Открываем новое (open_field)
   - Если on_new_record → активируем collector если есть

4. Multi-token для текущего поля:
   - Если token_rule(токен) → добавляем в буфер
   - Иначе → закрываем поле, переобрабатываем через эвристики

5. Эвристики (по порядку priority):
   - Проверяем if_missing_after (current_field или last_field)
   - Проверяем unless
   - Если detect_by → открываем поле с error_code

6. Добавляем к текущему полю или теряем (suspicious_log)
```

**Внутренние переменные состояния:**

| Переменная | Назначение |
|------------|------------|
| `current_field` | Имя открытого поля или `None` |
| `last_field` | Имя **последнего сохранённого** поля — нужен для эвристик когда `current_field` уже `None` (после multi_token) |
| `value_buffer` | Накопленные токены текущего поля |
| `errors` | Множество кодов ошибок записи |
| `collector_mode` | Флаг активного коллектора |
| `collector_limit` | Максимум токенов коллектора |
| `collector_count` | Сколько токенов уже собрано |
| `collector_rule` | Скомпилированный предикат коллектора |

**Внутренние функции:**

| Функция | Сигнатура | Назначение |
|---------|-----------|------------|
| `log(msg)` | `(str) -> None` | Пишет строку в `debug_log` если он передан (иначе no-op) |
| `save_field()` | `() -> None` | Нормализует буфер, валидирует, сохраняет в `record` с учётом `csv_column`. Устанавливает `last_field` |
| `open_field(name, first_token, err_code, with_collector)` | `(str, str\|None, str\|None, bool) -> None` | Вызывает `save_field()`, открывает новое поле, опционально активирует коллектор |

**Возвращает:** `dict` вида `{"яч": "1", "ном": "418/4", "фио/орг": "Смирнов Николай Евгеньевич", "err": "errFIO1"}`. Поле `"err"` присутствует только если есть ошибки.

---

### `segment_text(text, config, classify, debug_log)`

```python
def segment_text(
    text:      str,
    config:    dict,
    classify:  Callable[[str], Optional[str]],
    debug_log: Optional[list] = None
) -> list[list[str]]
```

Разбивает токены всего текста на группы — по одной группе на запись.

**Принимает готовый `classify`** — тот же экземпляр что передаётся в `parse_single_record`. Это гарантирует одинаковые результаты классификации при сегментации и при парсинге.

**Алгоритм:**

1. Если `record_detection` не задан → возвращает `[text.split()]` (весь текст — одна запись)
2. Иначе: проходит по токенам, при встрече триггера начинает новый сегмент
3. **continuation_heuristics:** опциональный проход слияния соседних сегментов

**Логика слияния (continuation_heuristics):**

```
Для каждого сегмента:
  Если сегмент начинается с триггера начала записи → НЕ сливать (всегда)
  Если merge_count >= merge_limit → остановить слияния (защита от петли)
  Если detect_by(любой из первых max_tokens_to_check токенов) → слить с предыдущим
```

**Лимит слияний:** `merge_limit = len(records) - 1`. Предотвращает схлопывание всего текста в одну запись при слишком широком `detect_by`. Счётчик `merge_count` сбрасывается при каждом несмёрженном переходе.

---

### `parse_text(text, config, suspicious_log, debug_log)`

```python
def parse_text(
    text:          str,
    config:        dict,
    suspicious_log: Counter,
    debug_log:     Optional[LimitedLog] = None
) -> list[dict]
```

Главная функция парсинга. Оркестрирует весь процесс.

**Последовательность:**

```
1. clean_text(text)           — очистка и нормализация пробелов
2. build_classifier(config)   — один классификатор с кешем для всего файла
3. segment_text(...)          — разбивка на записи
4. Цикл: parse_single_record(...) для каждой записи
5. detect_duplicates(...)     — пометка дублей после полного парсинга
```

**Почему классификатор создаётся один раз:** кеш классификатора работает на уровне файла. Если бы он создавался заново для каждой записи — кеш терялся бы и Левенштейн пересчитывался для каждого токена.

---

## 11. Экспорт результатов

### `build_json_bytes(records, columns)`

```python
def build_json_bytes(records: list[dict], columns: list[str]) -> bytes
```

Сериализует список записей в JSON-байты (UTF-8).

**Формат:** массив объектов, каждый содержит только поля из `columns + ['err']`.

```json
[
  {"яч": "1", "ном": "418/4", "фио/орг": "Смирнов Николай Евгеньевич", "err": ""},
  {"яч": "2", "ном": "6/8",   "фио/орг": "Новиков Максим Павлович",   "err": ""}
]
```

Отсутствующие поля заполняются пустой строкой `""`.

---

### `build_xlsx_bytes(records, columns)`

```python
def build_xlsx_bytes(records: list[dict], columns: list[str]) -> bytes | None
```

Создаёт XLSX-файл через `openpyxl`.

**Возвращает `None`** если `openpyxl` не установлен — не падает с ошибкой.

**Форматирование:**
- Строка заголовков: белый текст на тёмном фоне `#1A2540`, выравнивание по центру, жирный шрифт
- Строки с ошибками (`rec['err']` непустой): светло-розовый фон `#FFF0F0`
- Автоширина колонок: `min(max_длина_значения + 4, 60)` символов

**Требует:** `pip install openpyxl`

---

## 12. Постобработка и статистика

### `run_tests(config)`

```python
def run_tests(config: dict) -> dict
```

Запускает тест-кейсы из `config['tests']`. Каждый кейс запускает `parse_text` на `input` и сравнивает результат с `expect`.

**Возвращает:**
```python
{
    'total':   3,
    'passed':  2,
    'failed':  1,
    'results': [
        {
            'description': 'Тест ФИО',
            'status': 'pass',
            'details': [
                {'field': 'яч',     'expected': '1',     'got': '1',     'ok': True},
                {'field': 'фио/орг','expected': 'Иванов','got': 'Иванов','ok': True},
            ]
        },
        ...
    ]
}
```

При ошибке парсинга — статус `fail` с деталью `field='(parse)'`.  
При несуществующем индексе записи — статус `fail` с деталью `field='(records)'`.

Если секция `tests` отсутствует — возвращает `{'error': '...'}`.

---

### `detect_duplicates(records, config)`

```python
def detect_duplicates(records: list[dict], config: dict) -> int
```

Проходит по всем записям и помечает дубли кодом ошибки.

**Алгоритм:**
1. Берёт `dedup.key` из конфига
2. Строит множество `seen` уже встреченных значений
3. Если значение ключевого поля уже в `seen` → добавляет `error_code` к `rec['err']` (не перезаписывает существующие ошибки)
4. Первое вхождение в `seen` не помечается

**Регистрозависимость:** управляется `dedup.case_sensitive`. При `false` (по умолчанию) сравнение ведётся по `lower()`.

**Возвращает:** количество найденных дублей. `0` если `dedup` не задан в конфиге.

---

### `compute_stats(records, config)`

```python
def compute_stats(records: list[dict], config: dict) -> dict
```

Вычисляет агрегированную статистику по всем записям.

**Возвращает:**
```python
{
    'total':       10,
    'clean':       8,
    'with_errors': 2,
    'error_rate':  20.0,
    'top_errors':  [('errFIO1', 3), ('errKAD2', 1)],
    'field_fill':  {'яч': 10, 'ном': 10, 'фио/орг': 9, 'кад': 8},
    'duplicates':  1,
    'value_distribution': {
        'dok': {
            'unique':         2,
            'filled':         10,
            'repeated':       [('Паспорт', 6), ('Договор', 4)],
            'repeated_total': 2,
        },
        ...
    },
}
```

**`field_fill`** — количество записей где данное поле непустое после нормализации.

**`value_distribution`** — для каждой колонки:

| Ключ | Тип | Описание |
|------|-----|----------|
| `unique` | int | Количество уникальных значений |
| `filled` | int | Количество непустых значений |
| `repeated` | list | Топ-8 значений встречающихся > 1 раза `[(значение, count),...]` |
| `repeated_total` | int | Сколько всего уникальных значений встречается > 1 раза |

Отображается в интерфейсе как сетка карточек под таблицей заполненности.
Константа `MAX_VALUE_DIST_SHOWN = 8` ограничивает число показываемых повторов.

---

## 13. Документация и HTML-рендеринг

### `_build_docs_html()`

```python
def _build_docs_html() -> str
```

Генерирует полную HTML-страницу документации конфига из словаря `_DOCS`.

Страница доступна по маршруту `/docs`. Не принимает параметров — данные берутся из `_DOCS` в коде, поэтому документация всегда актуальна.

> **Внутренняя функция `section(title, rows, three_col)`:** рендерит одну HTML-таблицу
> из списка кортежей. При `three_col=True` генерирует двухколоночную таблицу (шаг, описание),
> иначе трёхколоночную (поле, тип, описание). Не предназначена для вызова извне.

---

### `_classify_log_line(line)`

```python
def _classify_log_line(line: str) -> tuple[str, str]
```

Классифицирует одну строку debug-лога по содержимому. Возвращает `(css_class, tag_html)`.

| CSS-класс | Тег | Условие |
|-----------|-----|---------|
| `t-trigger` | `TRIGGER` | Содержит "found trigger:", "exact match", "regex match" |
| `t-save` | `SAVE` | Начинается с "save_field" |
| `t-heur` | `HEUR` | Содержит "heuristic matched" |
| `t-stop` | `STOP` | Содержит "stop_word" |
| `t-lost` | `LOST` | Содержит "token lost" или "no active field" |
| `t-err` | (нет) | Содержит "валидация не пройдена" или "ВНИМАНИЕ" |
| `t-segment` | `REC` | Начинается с "=== SEGMENT", "--- Record", "=== PARS" |
| `""` | `""` | Всё остальное |

---

### `_render_debug_html(debug_log, log_token)`

```python
def _render_debug_html(
    debug_log:  list[str],
    log_token:  str
) -> str
```

Конвертирует плоский список строк лога в интерактивный HTML.

**Что делает:**
1. Разбивает лог на группы по записям (по строкам `"--- Record N/M ---"`)
2. Для каждой записи извлекает `save_field`-строки → генерирует бейджи с именами полей и значениями
3. Рендерит HTML с раскрываемыми блоками (`open/close` по клику)
4. Генерирует JS: функция `toggleRec(i)`, фильтрация по типу и поиск по тексту
5. Добавляет ссылку для скачивания raw-лога

**Формат вывода:** самодостаточный HTML-фрагмент (без `<html>/<head>`) — вставляется в шаблон страницы через `${debug_html}`.

---

### `_render_stats_html(stats, csv_columns, preview_rows, csv_name, csv_token)`

```python
def _render_stats_html(
    stats:          dict,
    csv_columns:    list,
    preview_rows:   list,
    csv_name:       str,
    csv_token:      str,
    suspicious:     Optional[Counter] = None,
    log_suspicious: bool = False
) -> str
```

| Параметр | Тип | Описание |
|----------|-----|----------|
| `suspicious` | Counter\|None | Счётчик потерянных токенов из `parse_text()` |
| `log_suspicious` | bool | Если `True` — рендерит секцию «Потерянные токены» |

Рендерит HTML вкладки «Результаты»:

1. **Кнопки скачивания** — CSV, JSON, Excel (`/download/<token>?fmt=csv|json|xlsx`)
2. **Карточки статистики** — всего / без ошибок / с ошибками / доля / дублей
3. **Прогресс-бары заполненности полей** — для каждой колонки из `csv_columns`
4. **Список топ-ошибок** — код и количество
5. **Потерянные токены** — если `log_suspicious=True`, добавляется третья колонка
   (`three-col` вместо `two-col`) со списком токенов отсортированных по частоте
6. **Распределение значений** — сетка карточек (`dist-grid`), по одной на поле:
   уникальные значения, повторяющиеся с частотой
7. **Таблица предпросмотра** — первые 50 строк с заголовками

---

### `build_html(config_loaded, raw_config, message, active_tab, results_html, debug_html)`

```python
def build_html(
    config_loaded: bool,
    raw_config:    Optional[dict] = None,
    message:       str = "",
    active_tab:    str = "main",
    results_html:  str = "",
    debug_html:    str = "",
) -> str
```

Собирает полную HTML-страницу из шаблона `_HTML_TEMPLATE` (`string.Template`).

**Переменные шаблона:**

| Переменная | Что подставляется |
|------------|-------------------|
| `${status_html}` | Статус конфига + опциональное сообщение |
| `${config_json}` | JSON конфига для textarea (экранированный) |
| `${debug_html}` | HTML лога отладки или приглашение загрузить файл |
| `${results_html}` | HTML результатов или приглашение запустить анализ |
| `${active_tab}` | Имя активной вкладки для JS-активации |

**Почему `string.Template` вместо `str.replace`:** если в конфиге или результатах встречается строка `$CONFIG_JSON` — `str.replace` заменил бы её рекурсивно. `Template.safe_substitute` этого не делает.

---

## 14. HTTP-сервер

### Класс `RequestHandler`

```python
class RequestHandler(BaseHTTPRequestHandler)
```

Обрабатывает HTTP-запросы. Все маршруты однопоточны — большие запросы выполняются через `ThreadPoolExecutor` с таймаутом.

---

### `RequestHandler.log_message(fmt, *args)`

```python
def log_message(self, fmt, *args)
```

Перекрывает стандартный метод `BaseHTTPRequestHandler.log_message`. Перенаправляет HTTP-лог в `log.debug` вместо `stderr`.

---

### `RequestHandler._check_auth()`

```python
def _check_auth(self) -> bool
```

Проверяет HTTP Basic Auth если включена (переменные окружения `TRIGGERPARSE_USER` и `TRIGGERPARSE_PASS`).

**Алгоритм:**
1. Если `AUTH_ENABLED = False` (переменные не заданы) → всегда возвращает `True`
2. Читает заголовок `Authorization: Basic <base64>`
3. Декодирует `base64` → `user:password`
4. Сравнивает через `hmac.compare_digest` (защита от timing-атак)

Возвращает `True` если авторизация успешна или отключена, `False` иначе.

---

### `RequestHandler._send_auth_required()`

```python
def _send_auth_required(self)
```

Отправляет `HTTP 401` с заголовком `WWW-Authenticate: Basic realm="TriggerParse Engine"`.
Браузер автоматически показывает стандартное окно ввода логина/пароля.

**Глобальные константы аутентификации:**

| Константа | Источник | Описание |
|-----------|----------|----------|
| `AUTH_USER` | `os.environ['TRIGGERPARSE_USER']` | Логин (пустая строка = не задан) |
| `AUTH_PASS` | `os.environ['TRIGGERPARSE_PASS']` | Пароль |
| `AUTH_ENABLED` | `bool(AUTH_USER and AUTH_PASS)` | `True` если оба заданы |

---

### `RequestHandler.do_GET()`

Обрабатывает GET-запросы. Маршруты:

| Маршрут | Действие |
|---------|----------|
| `/` | Главная страница интерфейса |
| `/debug_log/<name>` | Скачать raw debug-лог (attachment) |
| `/download/<token>?fmt=csv\|json\|xlsx` | Скачать результаты в выбранном формате |
| `/download_config` | Скачать текущий конфиг как `config.json` |
| `/docs` | Страница документации конфига |
| `/progress` | SSE-стрим прогресса обработки (`text/event-stream`) |
| `/run_tests` | Запустить тест-кейсы, вернуть JSON |

---

### `RequestHandler.do_POST()`

Обрабатывает POST-запросы. Маршруты:

| Маршрут | Действие |
|---------|----------|
| `/analyze` | Парсинг файлов, возврат страницы с результатами |
| `/debug` | Парсинг с полным debug-логом, возврат страницы отладки |
| `/upload_config` | Загрузка и применение конфига |
| `/validate_config` | Быстрая валидация JSON (для live-проверки в браузере) |
Все маршруты проверяются через `_check_auth()` до любой обработки. При неудаче — 401.

---

### `RequestHandler._send_html(body)`

```python
def _send_html(self, body: str)
```

Отправляет HTML-ответ с корректными заголовками (`Content-Type: text/html; charset=utf-8`, `Content-Length`).

---

### `RequestHandler._send_json(data, status)`

```python
def _send_json(self, data: dict, status: int = 200)
```

Отправляет JSON-ответ. Используется для API-маршрутов (`/run_tests`, `/validate_config`, `/progress`).

---

### `RequestHandler._read_body()`

```python
def _read_body(self) -> Optional[bytes]
```

Читает тело POST-запроса с проверкой размера. При превышении `MAX_UPLOAD_BYTES` (32 МБ) — отправляет `413 Request Entity Too Large` и возвращает `None`.

---

### `RequestHandler._parse_multipart()`

```python
def _parse_multipart(self) -> tuple[list[tuple[str, bytes]], str]
```

Парсит `multipart/form-data` через стандартный `email.parser.BytesParser`. Возвращает `([(filename, bytes), ...], csv_name)`.

**Поля формы:**
- `files` — загруженные TXT-файлы (может быть несколько)
- `csvname` — желаемое имя выходного CSV

---

### `RequestHandler._handle_analyze(compiled_cfg, raw_cfg, debug_mode)`

```python
def _handle_analyze(
    self,
    compiled_cfg: dict,
    raw_cfg:      Optional[dict],
    debug_mode:   bool
)
```

Основная логика обработки загруженных файлов.

**Последовательность:**

```
1. _parse_multipart()  — извлечь файлы из запроса
2. Создать внутреннюю функцию _parse_all()
3. Запустить _parse_all() в ThreadPoolExecutor с таймаутом
4. _parse_all() обрабатывает файлы последовательно:
   - decode_bytes() для каждого файла
   - parse_text() с обновлением _state.set_progress()
5. compute_stats() + build_json_bytes() + build_xlsx_bytes()
6. _state.set_result() — сохранить всё в AppState
7. Если debug_mode:
   - _render_debug_html() → вкладка «Отладка»
   Иначе:
   - _render_stats_html() → вкладка «Результаты»
8. build_html() + _send_html()
```

**Обработка ошибок:**
- `TimeoutError` → `503 Service Unavailable`
- Любое другое исключение → `500 Internal Server Error`

---

### `RequestHandler._handle_upload_config()`

```python
def _handle_upload_config(self)
```

Загружает новый конфиг из формы (файл или textarea).

**Приоритет:** если загружен файл — используется файл; если только textarea — используется её содержимое.

**Последовательность:**
1. Читать тело запроса
2. `json.loads()` — разобрать JSON
3. `validate_config()` — проверить структуру
4. `compile_config()` — скомпилировать
5. `_state.set_config()` — сохранить
6. Записать в `default_config.json` — persist между перезапусками
7. Вернуть страницу с сообщением об успехе или ошибке

---

## 15. Точка входа

### `run_server(port)`

```python
def run_server(port: int = 8000)
```

Запускает HTTP-сервер.

**Последовательность:**
1. `try_load_default_config()` — загрузить конфиг если есть
2. `HTTPServer(('', port), RequestHandler)` — создать сервер на всех интерфейсах
3. Логировать URL
4. `httpd.serve_forever()` — блокирующий цикл обработки запросов
5. При `KeyboardInterrupt` (Ctrl+C) — логировать остановку

**Запуск из командной строки:**
```bash
python engine_web.py          # порт 8000 (по умолчанию)
python engine_web.py 9000     # порт 9000
```

---

## 16. Схема вызовов

Путь от HTTP-запроса до CSV-файла:

```
HTTP POST /analyze
│
├─ RequestHandler.do_POST()
│  └─ _handle_analyze(compiled_cfg, raw_cfg, debug_mode=False)
│     │
│     ├─ _parse_multipart()          → [(fname, bytes), ...]
│     │
│     ├─ ThreadPoolExecutor
│     │  └─ _parse_all()
│     │     └─ для каждого файла:
│     │        ├─ decode_bytes()      → (text, encoding)
│     │        └─ parse_text()
│     │           ├─ clean_text()
│     │           │  └─ normalize_whitespace()
│     │           ├─ build_classifier()   → classify(token)->name|None
│     │           │  └─ [кеш + levenshtein_distance()]
│     │           ├─ segment_text()       → [[токены записи 1], [токены записи 2], ...]
│     │           ├─ для каждой записи:
│     │           │  └─ parse_single_record()
│     │           │     ├─ [collector / stop / classify / multi_token / heuristics]
│     │           │     └─ save_field()
│     │           │        └─ make_normalizer() → применяет pipeline
│     │           │           └─ _apply_normalization_step() × N
│     │           └─ detect_duplicates()
│     │
│     ├─ compute_stats()
│     ├─ build_json_bytes()
│     ├─ build_xlsx_bytes()
│     ├─ _state.set_result()
│     ├─ _render_stats_html()
│     └─ build_html() → _send_html()
│
└─ HTTP 200 (HTML-страница с результатами)

Параллельно (SSE):
  GET /progress
  └─ _state.get_progress() × каждые 0.5с → data: {"pct":N,"msg":"..."}
```

**Путь загрузки конфига:**

```
HTTP POST /upload_config
│
├─ _handle_upload_config()
│  ├─ json.loads()
│  ├─ validate_config()      → [] или [ошибки]
│  ├─ compile_config()
│  │  ├─ deepcopy(raw)
│  │  ├─ _compile_predicate_chain() × N
│  │  ├─ _compile_validation() × N
│  │  └─ sort by heuristics.priority
│  ├─ _state.set_config(raw, compiled)
│  └─ json.dump() → default_config.json
│
└─ HTTP 200 (страница с сообщением)
```

---

*Документация соответствует TriggerParse Engine v3.0, файл `engine_web.py`, ~2600 строк.*

**Изменения с момента первой публикации:**
- Добавлен класс `LimitedLog` (лимит debug-лога)
- `suspicious_log`: тип изменён с `set` на `Counter`
- `compute_stats()`: добавлено поле `value_distribution`
- `_render_stats_html()`: новые параметры `suspicious`, `log_suspicious`; новая секция распределения значений
- `AppState.set_result()`: расширена сигнатура (добавлены `json_bytes`, `xlsx_bytes`)
- `RequestHandler`: добавлены `_check_auth()`, `_send_auth_required()`
- Новый маршрут GET `/download_config`
- Глобальные константы аутентификации `AUTH_USER`, `AUTH_PASS`, `AUTH_ENABLED`