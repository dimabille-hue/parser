# TriggerParse Engine v4.0 — Архитектура модульной библиотеки

> **Версия:** 4.0 (переход на модульную архитектуру)  
> **Статус:** Beta - базовые модули готовы, интеграция в процессе  
> **Совместимость:** v3.0 конфигурации полностью поддерживаются

---

## Обзор

Парсер v4.0 переписан с монолитной архитектуры (один файл ~114KB) на модульную библиотеку `parser_lib`. Это позволяет:

✅ **Универсальность** — легко адаптировать для других типов данных  
✅ **Тестируемость** — unit-тесты для каждого компонента  
✅ **Расширяемость** — система плагинов для кастомных функций  
✅ **Переиспользуемость** — встраивание в другие приложения  
✅ **Поддержка v3.0 конфигов** — 100% обратная совместимость

---

## Структура проекта

```
parser_lib/
├── __init__.py              # Главный API
├── core/
│   ├── __init__.py
│   ├── tokenizer.py         # Разбиение текста на токены
│   ├── normalizer.py        # Нормализация значений
│   ├── validator.py         # Валидация значений
│   ├── predicates.py        # Предикаты для классификации токенов
│   ├── classifier.py        # Распределение токенов по триггерам
│   └── engine.py            # (готовится) Главный парсинг
├── config/
│   ├── __init__.py
│   └── loader.py            # Загрузка и валидация конфигов
├── outputs/
│   ├── __init__.py
│   ├── csv_exporter.py      # Экспорт в CSV
│   ├── json_exporter.py     # Экспорт в JSON
│   └── database_exporter.py # (готовится) Экспорт в БД
├── inputs/
│   ├── __init__.py
│   └── text_loader.py       # (готовится) Загрузка текстовых файлов
├── utils/
│   ├── __init__.py
│   └── distance.py          # Алгоритм Левенштейна
└── plugins/
    ├── __init__.py
    └── normalization/       # (готовится) Плагины нормализации
        └── russian_rules.py

tests/
├── test_core.py             # Тесты ядра
├── test_config.py           # Тесты конфигурации
└── test_exporters.py        # Тесты экспортеров
```

---

## Модули

### 1. `parser_lib.core.tokenizer`

**Назначение:** Разбиение текста на токены

```python
from parser_lib.core.tokenizer import TokenizerFactory

# Создать токенизатор
tokenizer = TokenizerFactory.create('whitespace')
tokens = tokenizer.tokenize("Яч 1. Ном. 418.4.")
# → ["Яч", "1.", "Ном.", "418.4."]
```

**Доступные режимы:**
- `'whitespace'` — разбиение только по пробелам (по умолчанию)
- `'whitespace_and_punctuation'` — также по пунктуации

**Расширение:**
```python
class CustomTokenizer(BaseTokenizer):
    def tokenize(self, text: str) -> List[str]:
        # Ваша логика
        pass

TokenizerFactory.register('custom', CustomTokenizer)
```

---

### 2. `parser_lib.core.normalizer`

**Назначение:** Нормализация извлеченных значений

```python
from parser_lib.core.normalizer import NormalizerFactory

# Создать пайплайн нормализации
normalizer = NormalizerFactory.create_pipeline([
    'strip',
    'remove_trailing_dot',
    'replace_char:internal:.->/',
    'collapse_spaces'
])

result = normalizer.normalize("418.4. ")
# → "418/4"
```

**Встроенные шаги:**

| Шаг | Описание | Пример |
|-----|---------|--------|
| `strip` | Пробелы по краям | `" text "` → `"text"` |
| `remove_dots` | Все точки | `"1.2.3"` → `"123"` |
| `remove_trailing_dot` | Точка в конце | `"1."` → `"1"` |
| `remove_spaces` | Все пробелы | `"5 9"` → `"59"` |
| `collapse_spaces` | Множественные пробелы | `"a  b"` → `"a b"` |
| `uppercase` | Верхний регистр | `"text"` → `"TEXT"` |
| `lowercase` | Нижний регистр | `"TEXT"` → `"text"` |
| `digits_only` | Только цифры | `"Яч5а"` → `"5"` |
| `replace_char:A->B` | Заменить символ | `"1.2"` → `"1:2"` |
| `to_int` | Целое число | `"3.14"` → `"3"` |
| `to_float:N` | Округлить до N | `"3.14159"` → `"3.14"` |
| `apply_replacements` | Словарь замен | Требует `replacements` |
| `regex_sub:A->B` | Regex замена | `"a  b"` → `"a_b"` |

**Расширение:**
```python
class ToUpperCase(BaseNormalizationStep):
    def apply(self, value: str) -> str:
        return value.upper()

NormalizerFactory.register_step('my_upper', ToUpperCase)
normalizer = NormalizerFactory.create_pipeline(['my_upper'])
```

---

### 3. `parser_lib.core.validator`

**Назначение:** Валидация нормализованных значений

```python
from parser_lib.core.validator import ValidatorFactory

# Создать валидатор
validator = ValidatorFactory.create('word_count:2,3')

if validator.validate("Иванов Иван"):
    print("✓ Валидно")
else:
    print("✗ Ошибка:", validator.get_error_message())
```

**Правила валидации:**

| Правило | Пример | Проходит |
|---------|--------|----------|
| `not_empty` | любая непустая строка | `"text"` |
| `word_count:min,max` | `"word_count:2,3"` | `"Иванов Иван"` |
| `length:min,max` | `"length:5,10"` | `"hello"` (5 символов) |
| `regex:PATTERN` | `"regex:^[0-9:]+$"` | `"59:34"` |
| `choices:A,B,C` | `"choices:red,blue"` | `"red"` |

---

### 4. `parser_lib.core.predicates`

**Назначение:** Классификация токенов (для `detect_by`, `token_rule`, `unless`)

```python
from parser_lib.core.predicates import PredicateFactory

# Создать предикат
pred = PredicateFactory.create('starts_upper')

if pred("Смирнов."):
    print("Токен начинается с заглавной буквы")

# Комбинация
pred_or = PredicateFactory.create('starts_upper | has_letter')
assert pred_or("Text") is True
assert pred_or("123text") is True
assert pred_or("123") is False
```

**Встроенные предикаты:**

| Предикат | Что проверяет |
|----------|---------------|
| `starts_upper` | Первая буква заглавная |
| `has_letter` | Содержит хотя бы одну букву |
| `looks_like_number_colon_dot` | Только цифры/буквы/точки/двоеточия |
| `is_part_of_number_colon_dot` | Выше + содержит цифру или точку |
| `any` | Любой непустой токен |
| `regex:PATTERN` | Совпадение с регуляркой |

**Комбинирование:**
```python
pred = PredicateFactory.create('starts_upper | regex:\d+')
# Срабатывает если токен начинается с заглавной ИЛИ содержит цифры
```

---

### 5. `parser_lib.core.classifier`

**Назначение:** Распределение токенов по триггерам

```python
from parser_lib.core.classifier import Classifier

config = {
    'triggers': {
        'фио': {
            'aliases': ['фио', 'ф.и.о'],
            'search_mode': 'fuzzy',
        },
        'кад': {
            'aliases': ['кад', 'кадастр'],
            'search_mode': 'fuzzy',
        }
    },
    'max_distance': 1,
    'require_first_char': True,
    'stop_words': set()
}

classifier = Classifier(config['triggers'])

result = classifier.classify("Фио.")  # → 'фио'
result = classifier.classify("фиo")   # → 'фио' (одна ошибка)
result = classifier.classify("xyz")   # → None
```

**Режимы поиска:**
- `'fuzzy'` — нечеткий поиск (расстояние Левенштейна)
- `'exact'` — точное совпадение
- `'regex'` — первый алиас — регулярное выражение

---

### 6. `parser_lib.config.loader`

**Назначение:** Загрузка и валидация конфигурации

```python
from parser_lib.config.loader import ConfigLoader

# Загрузить JSON
config = ConfigLoader.load_json('default_config.json')

# Валидировать
errors = ConfigLoader.validate_basic(config)
if errors:
    for err in errors:
        print(f"✗ {err}")
else:
    print("✓ Конфиг валиден")
```

**Обязательные поля:**
- `parser_name` — название парсера
- `csv_columns` — список выходных колонок
- `triggers` — словарь триггеров

---

### 7. `parser_lib.outputs.csv_exporter` и `json_exporter`

**Назначение:** Экспорт результатов парсинга

```python
from parser_lib.outputs.csv_exporter import CSVExporter
from parser_lib.outputs.json_exporter import JSONExporter

records = [
    {"яч": "1", "ном": "418/4", "фио/орг": "Смирнов", "err": ""},
    {"яч": "2", "ном": "6/8", "фио/орг": "Петров", "err": "errDUP"},
]
columns = ["яч", "ном", "фио/орг"]

# CSV
csv_bytes = CSVExporter.export(records, columns)
CSVExporter.export_to_file(records, columns, 'output.csv')

# JSON
json_bytes = JSONExporter.export(records, columns)
JSONExporter.export_to_file(records, columns, 'output.json')
```

---

## Миграция с v3.0

### Конфигурация

✅ **v3.0 конфигурация полностью совместима с v4.0**

Просто используйте свой существующий `default_config.json` или загружайте через:

```python
from parser_lib.config.loader import ConfigLoader

config = ConfigLoader.load_json('default_config.json')
errors = ConfigLoader.validate_basic(config)
```

### Использование в коде

**Вместо:**
```python
# v3.0 - монолитный файл
from engine_web import parse_text
results = parse_text(text, config)
```

**Используйте:**
```python
# v4.0 - модульная библиотека
from parser_lib import ParseEngine
from parser_lib.config.loader import ConfigLoader

config = ConfigLoader.load_json('config.json')
engine = ParseEngine(config)
results = engine.parse(text)
```

---

## Путь развития v4.0

### ✅ Готово
- [x] Базовые модули (tokenizer, normalizer, validator)
- [x] Система предикатов
- [x] Классификатор триггеров
- [x] Конфиг-лоадер
- [x] CSV/JSON экспортеры
- [x] Unit-тесты

### 🔄 В процессе
- [ ] ParseEngine — главный класс парсинга
- [ ] Интеграция с v3.0 функциями парсинга
- [ ] HTTP API (миграция с Flask)
- [ ] Документация API

### 📋 Планируется
- [ ] Система плагинов для нормализации
- [ ] Поддержка XML/HTML input
- [ ] Database exporter (PostgreSQL, SQLite)
- [ ] Batch processing
- [ ] Performance оптимизация (Cython)
- [ ] CLI интерфейс

---

## Запуск тестов

```bash
# Установить pytest
pip install pytest

# Запустить все тесты
pytest tests/ -v

# С покрытием
pip install pytest-cov
pytest tests/ --cov=parser_lib --cov-report=html
```

---

## API Справка

Полная документация по каждому модулю находится в файлах их источников с docstring примерами.

**Быстрые ссылки:**
- Tokenizer API: `parser_lib/core/tokenizer.py`
- Normalizer API: `parser_lib/core/normalizer.py`
- Validator API: `parser_lib/core/validator.py`
- Predicates API: `parser_lib/core/predicates.py`
- Classifier API: `parser_lib/core/classifier.py`
- Config API: `parser_lib/config/loader.py`
- Exporters API: `parser_lib/outputs/`
