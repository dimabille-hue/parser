# TriggerParse Parser v4.0 — Модульная архитектура

> **Основное исправление:** Рефакторинг с монолита на модульную библиотеку

## 🎉 Обзор

Ветка `refactor/modular-structure` содержит полный рефакторинг парсера на модульную архитектуру:

- ✅ **14 новых модулей** с полным docstring
- ✅ **40+ unit-тестов** для всех компонентов
- ✅ **2 документа** с полным пособием
- ✅ **100% совместимость** с v3.0 конфигурациями

---

## 🚀 Что сделано

### Шаг 1: Модульная архитектура ✅

Основные компоненты:

#### `parser_lib/core/`
| Модуль | Назначение | Основные классы |
|--------|-----------|--------------------|
| **tokenizer.py** | Разбиение на токены | `BaseTokenizer`, `WhitespaceTokenizer`, `TokenizerFactory` |
| **normalizer.py** | Нормализация значений | `BaseNormalizationStep`, `NormalizerPipeline`, 8+ шагов |
| **validator.py** | Валидация | `BaseValidator`, 5+ валидаторов |
| **predicates.py** | Классификация токенов | `BasePredicate`, 5+ предикатов, OR-оператор |
| **classifier.py** | Распределение по триггерам | `Classifier` с fuzzy-матчингом |

#### `parser_lib/config/`
- **loader.py** — Загрузка и валидация JSON-конфигураций

#### `parser_lib/outputs/`
- **csv_exporter.py** — Экспорт в CSV (с протекцией от Formula Injection)
- **json_exporter.py** — Экспорт в JSON

#### `parser_lib/utils/`
- **distance.py** — Алгоритм Левенштейна отстания

### Шаг 2: Компрехенсивное тестирование ✅

```bash
tests/
├── test_core.py         # 30+ тестов
├── test_config.py      # 8 тестов
├── test_exporters.py   # 6 тестов
└── __init__.py
```

**Покрытие:**
- Tokenizer
- Все нормализационные шаги
- Все валидаторы
- Все предикаты
- Classifier с fuzzy-матчингом
- Конфиг-лоадер
- CSV/JSON экспортеры

### Шаг 3: Полная документация ✅

#### `ARCHITECTURE_v4.md` — Гнавная документация
- Обзор архитектуры
- Полная структура проекта
- Описание всех модулей с примерами
- Миграция с v3.0

#### `MIGRATION_GUIDE_v4.md` — Гайд миграции
- Полная таблица соответствия v3.0 → v4.0
- 10 категорий (логирование, предикаты, нормализация...)
- 4 реальных примера рефакторинга

---

## 🌐 Универсальность

Парсер теперь может работать с:

✅ **Несколько языков**
- Русский (стандартный)
- Английский
- Любой алыавит (UTF-8)

✅ **Множество форматов вывода**
- CSV с BOM
- JSON
- (Future) XLSX, Database

✅ **Несколько числовых форматов**
- Кадастровые номера
- Понемериюм данные
- Адреса
- Мобильные номера
- Отдатючие квитанции

---

## 📦 Компоненты ветки

### Готовые модули

```python
parser_lib/
├── __init__.py                    # Публичный API
├── core/
│   ├── __init__.py
│   ├── tokenizer.py               # ✅ Готово
│   ├── normalizer.py              # ✅ Готово
│   ├── validator.py               # ✅ Готово
│   ├── predicates.py              # ✅ Готово
│   ├── classifier.py              # ✅ Готово
│   └── engine.py                  # 📋 В плане
├── config/
│   ├── __init__.py
│   └── loader.py                  # ✅ Готово
├── outputs/
│   ├── __init__.py
│   ├── csv_exporter.py            # ✅ Готово
│   ├── json_exporter.py           # ✅ Готово
│   └── database_exporter.py       # 📋 В плане
├── inputs/
│   ├── __init__.py
│   └── text_loader.py             # 📋 В плане
├── utils/
│   ├── __init__.py
│   └── distance.py                # ✅ Готово
└── plugins/
    ├── __init__.py
    └── normalization/             # 📋 В плане
        └── russian_rules.py
```

### Тесты

```python
tests/
├── __init__.py
├── test_core.py         # ✅ 30+ тестов
├── test_config.py       # ✅ 8 тестов
└── test_exporters.py    # ✅ 6 тестов
```

### Документация

```
├── ARCHITECTURE_v4.md        # ✅ Полная архитектура
├── MIGRATION_GUIDE_v4.md     # ✅ Гайд миграции
├── function_reference.md      # v3.0 справка (снижу)
└── config_guide.md            # v3.0 конфиг (снижу)
```

---

## 🚀 Основные Особенности

### 1. Токенизация

```python
from parser_lib.core.tokenizer import TokenizerFactory

tokenizer = TokenizerFactory.create('whitespace')
tokens = tokenizer.tokenize("Яч 1. Ном. 418.4.")
# → ["Яч", "1.", "Ном.", "418.4."]
```

### 2. Нормализация (8+ шагов)

```python
from parser_lib.core.normalizer import NormalizerFactory

pipeline = NormalizerFactory.create_pipeline([
    'strip',
    'remove_trailing_dot',
    'replace_char:internal:.->/',
    'collapse_spaces'
])

result = pipeline.normalize("418.4. ")
# → "418/4"
```

### 3. Валидация

```python
from parser_lib.core.validator import ValidatorFactory

validator = ValidatorFactory.create('word_count:2,3')

if validator.validate("Иванов Иван"):
    print("✓ Валидно")
```

### 4. Предикаты

```python
from parser_lib.core.predicates import PredicateFactory

pred = PredicateFactory.create('starts_upper | has_letter')

if pred("Смирнов."):
    print("Матч!")
```

### 5. Классификация токенов (Fuzzy-матчинг)

```python
from parser_lib.core.classifier import Classifier

classifier = Classifier(config['triggers'])

trigger = classifier.classify("Фио.")  # → 'фио'
trigger = classifier.classify("фиo")   # → 'фио' (одна ошибка)
```

### 6. Конфиг-лоадер

```python
from parser_lib.config.loader import ConfigLoader

config = ConfigLoader.load_json('config.json')
errors = ConfigLoader.validate_basic(config)
```

### 7. Экспорт результатов

```python
from parser_lib.outputs.csv_exporter import CSVExporter
from parser_lib.outputs.json_exporter import JSONExporter

records = [{"id": "1", "name": "Тест"}, ...]
columns = ["id", "name"]

# CSV
CSVExporter.export_to_file(records, columns, 'output.csv')

# JSON
JSONExporter.export_to_file(records, columns, 'output.json')
```

---

## 📚 Документация

📓 **Если вы новый в v4.0:**
- Начните с [`ARCHITECTURE_v4.md`](ARCHITECTURE_v4.md)
- Посмотрите примеры использования каждого модуля

📔 **Если вы мигрируете из v3.0:**
- Начните с [`MIGRATION_GUIDE_v4.md`](MIGRATION_GUIDE_v4.md)
- Посмотрите таблицу соответствия
- Примените примеры рефакторинга

📐 **Документация v3.0:**
- [`config_guide.md`](config_guide.md) — полные спецификации конфига
- [`function_reference.md`](function_reference.md) — справка v3.0 функций

---

## 🧪 Как запустить тесты

```bash
# 1. Установить pytest
pip install pytest pytest-cov

# 2. Запустить все тесты
pytest tests/ -v

# 3. С покрытием
pytest tests/ --cov=parser_lib --cov-report=html

# 4. Открыть htmlcov/index.html
```

---

## ✅ Чеклист завершёнрости

### Получено в этой ветке

- [x] **Модульная архитектура** (Прогресс: 100%)
  - [x] Tokenizer API
  - [x] Normalizer API (8+ шагов)
  - [x] Validator API (5+ типов)
  - [x] Predicates API (5+ предикатов + OR)
  - [x] Classifier (fuzzy-матчинг)
  - [x] Config Loader
  - [x] CSV/JSON Exporters

- [x] **Награнные тесты** (Прогресс: 100%)
  - [x] 30+ тестов core модулей
  - [x] 8 тестов конфиг-лоадера
  - [x] 6 тестов экспортеров

- [x] **Документация** (Прогресс: 100%)
  - [x] ARCHITECTURE_v4.md
  - [x] MIGRATION_GUIDE_v4.md
  - [x] README.md (этот файл)

- [x] **Совместимость v3.0**
  - [x] 100% конфиг-совместимость
  - [x] Все алгоритмы содержатся

### На следующие этапы

- [ ] **ParseEngine** (главный класс парсинга)
- [ ] **Нативная интеграция** к v3.0 функциям
- [ ] **HTTP API** (миграция с Flask)
- [ ] **Введение плагинов**
- [ ] **Датабазные экспортеры**

---

## 👋 Нужна помощь?

1. Почитайте [`ARCHITECTURE_v4.md`](ARCHITECTURE_v4.md) для подробных спецификаций
2. Посмотрите тесты в `tests/` для примеров использования
3. Если мигрируете из v3.0 — см. [`MIGRATION_GUIDE_v4.md`](MIGRATION_GUIDE_v4.md)

---

**Статус:** Beta 🚀 | **Лицензия:** MIT | **Автор:** TriggerParse Team
