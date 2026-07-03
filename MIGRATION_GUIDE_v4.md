# TriggerParse v4.0 — Справочник миграции функций

> Соответствие функций v3.0 и их эквивалентов в v4.0 модульной архитектуре

---

## Таблица соответствия

### 1. Логирование и состояние

| v3.0 | v4.0 | Модуль | Статус |
|------|------|--------|--------|
| `setup_logging()` | Будет в `ParseEngine` | `parser_lib.core.engine` | 📋 |
| `LimitedLog` | Встроен в engine | `parser_lib.core.engine` | 📋 |
| `AppState` | `ParseEngine.state` | `parser_lib.core.engine` | 📋 |

### 2. Вспомогательные функции

| v3.0 | v4.0 | Модуль | Примечание |
|------|------|--------|------------|
| `decode_bytes()` | Будет в `inputs.text_loader` | `parser_lib.inputs` | 📋 |
| `try_load_default_config()` | `ConfigLoader.load_json()` | `parser_lib.config.loader` | ✅ |
| `_escape_html()` | Будет в HTTP слое | (не в libr) | — |

### 3. Предикаты и классификация

| v3.0 | v4.0 | Модуль | Статус |
|------|------|--------|--------|
| `_token_starts_upper()` | `StartsUpperPredicate` | `parser_lib.core.predicates` | ✅ |
| `_token_has_letter()` | `HasLetterPredicate` | `parser_lib.core.predicates` | ✅ |
| `_token_is_number_colon_dot()` | `LooksLikeNumberPredicate` | `parser_lib.core.predicates` | ✅ |
| `_token_is_part_of_number_colon_dot()` | `IsPartOfNumberPredicate` | `parser_lib.core.predicates` | ✅ |
| `_token_any()` | `AnyPredicate` | `parser_lib.core.predicates` | ✅ |
| `_compile_predicate_chain()` | `PredicateFactory.create()` | `parser_lib.core.predicates` | ✅ |
| `build_classifier()` | `Classifier` класс | `parser_lib.core.classifier` | ✅ |

### 4. Валидация и компиляция конфига

| v3.0 | v4.0 | Модуль | Статус |
|------|------|--------|--------|
| `validate_config()` | `ConfigLoader.validate_basic()` | `parser_lib.config.loader` | ✅ |
| `_compile_validation()` | `ValidatorFactory.create()` | `parser_lib.core.validator` | ✅ |
| `compile_config()` | Будет в `ParseEngine` | `parser_lib.core.engine` | 📋 |

### 5. Алгоритм Левенштейна

| v3.0 | v4.0 | Модуль | Статус |
|------|------|--------|--------|
| `levenshtein_distance()` | `levenshtein_distance()` | `parser_lib.utils.distance` | ✅ |

### 6. Нормализация значений

| v3.0 | v4.0 | Модуль | Статус |
|------|------|--------|--------|
| `_apply_normalization_step()` | `NormalizerFactory.create_step()` | `parser_lib.core.normalizer` | ✅ |
| `make_normalizer()` | `NormalizerFactory.create_pipeline()` | `parser_lib.core.normalizer` | ✅ |
| Все шаги нормализации | Соответствующие классы | `parser_lib.core.normalizer` | ✅ |

### 7. Предобработка текста

| v3.0 | v4.0 | Модуль | Статус |
|------|------|--------|--------|
| `normalize_whitespace()` | Будет в `inputs.text_loader` | `parser_lib.inputs` | 📋 |
| `tokenize_text()` | `TokenizerFactory.create().tokenize()` | `parser_lib.core.tokenizer` | ✅ |
| `clean_text()` | Будет в `inputs.text_loader` | `parser_lib.inputs` | 📋 |

### 8. Ядро парсера

| v3.0 | v4.0 | Модуль | Статус |
|------|------|--------|--------|
| `parse_single_record()` | `ParseEngine.parse_record()` | `parser_lib.core.engine` | 📋 |
| `segment_text()` | `ParseEngine.segment()` | `parser_lib.core.engine` | 📋 |
| `parse_text()` | `ParseEngine.parse()` | `parser_lib.core.engine` | 📋 |

### 9. Экспорт результатов

| v3.0 | v4.0 | Модуль | Статус |
|------|------|--------|--------|
| `build_json_bytes()` | `JSONExporter.export()` | `parser_lib.outputs.json_exporter` | ✅ |
| `build_xlsx_bytes()` | Будет в экспортере | `parser_lib.outputs` | 📋 |
| CSV функции | `CSVExporter.export()` | `parser_lib.outputs.csv_exporter` | ✅ |

### 10. Постобработка и статистика

| v3.0 | v4.0 | Модуль | Статус |
|------|------|--------|--------|
| `run_tests()` | Будет в `ParseEngine` | `parser_lib.core.engine` | 📋 |
| `detect_duplicates()` | Будет в `ParseEngine` | `parser_lib.core.engine` | 📋 |
| `compute_stats()` | Будет в `ParseEngine` | `parser_lib.core.engine` | 📋 |

---

## Примеры миграции

### Пример 1: Нормализация значения

**v3.0:**
```python
normalizer = make_normalizer(
    ["strip", "remove_trailing_dot", "replace_char:internal:.->"]
)
result = normalizer("418.4.")
```

**v4.0:**
```python
from parser_lib.core.normalizer import NormalizerFactory

normalizer = NormalizerFactory.create_pipeline([
    "strip",
    "remove_trailing_dot",
    "replace_char:internal:.->/"
])
result = normalizer.normalize("418.4.")
```

### Пример 2: Классификация токена

**v3.0:**
```python
classifier = build_classifier(config)
trigger_name = classifier("Фио.")
```

**v4.0:**
```python
from parser_lib.core.classifier import Classifier

classifier = Classifier(config['triggers'])
trigger_name = classifier.classify("Фио.")
```

### Пример 3: Валидация

**v3.0:**
```python
validator_func = _compile_validation("word_count:2,3")
if validator_func("Иванов Иван"):
    print("OK")
```

**v4.0:**
```python
from parser_lib.core.validator import ValidatorFactory

validator = ValidatorFactory.create("word_count:2,3")
if validator.validate("Иванов Иван"):
    print("OK")
```

### Пример 4: Создание предикатов

**v3.0:**
```python
detect_pred = _compile_predicate_chain("starts_upper | has_letter")
if detect_pred("Смирнов"):
    print("Matching")
```

**v4.0:**
```python
from parser_lib.core.predicates import PredicateFactory

pred = PredicateFactory.create("starts_upper | has_letter")
if pred("Смирнов"):
    print("Matching")
```

---

## Легенда статуса

| Иконка | Значение |
|--------|----------|
| ✅ | Готово и тестировано |
| 📋 | В процессе реализации |
| 🔄 | Требует переработки |
| — | Не требуется в libr (часть HTTP слоя) |

---

## Полная замена функции

Для полной замены функции `parse_text()` из v3.0 используйте:

```python
from parser_lib.config.loader import ConfigLoader
from parser_lib.core.classifier import Classifier
from parser_lib.core.normalizer import NormalizerFactory
from parser_lib.core.tokenizer import TokenizerFactory

# Загрузить конфиг
config = ConfigLoader.load_json('config.json')

# Создать компоненты
tokenizer = TokenizerFactory.create(config.get('tokenizer', {}).get('split_by', 'whitespace'))
classifier = Classifier(config['triggers'])

# Токенизировать
tokens = tokenizer.tokenize(text)

# Классифицировать
for token in tokens:
    trigger_name = classifier.classify(token)
    if trigger_name:
        # Обработать триггер
        pass
```

Полная логика парсинга будет в `ParseEngine` в следующих версиях.
