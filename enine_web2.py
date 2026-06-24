#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TriggerParse Engine v3.1 — Universal Configurable Parser
========================================================
Исправления по сравнению с v3.0:
  - Удалён мёртвый _UNICODE_SPACE_RE (компилировался, но нигде не использовался)
  - segment_text: should_merge реструктурирован в три явные ветки (starts_with_trigger /
    merge_limit / else), устранена неочевидная зависимость от порядка условий
  - HTTPServer → ThreadingHTTPServer: SSE /progress теперь работает параллельно
    с /analyze и /debug (раньше однопоточный сервер сериализовал соединения)
  - /debug_log/<token>: токен теперь проверяется (ранее любой путь отдавал лог)
  - _handle_analyze: прогресс сбрасывается в 0 перед запуском воркера, чтобы
    клиент не видел done=True от предыдущего прогона
  - enc_notes (имена файлов из загрузок) экранируются через _escape_html перед
    вставкой в HTML (XSS)
  - _handle_upload_config: файл и textarea обрабатываются двумя отдельными
    проходами; файл всегда приоритетнее textarea независимо от порядка частей
  - AppState.__init__: все поля результата инициализированы явно (было только
    через set_result/getattr — риск AttributeError при нестандартном доступе)
  - Добавлен threading.Event cancel_event: воркер проверяет флаг между файлами
    и прекращает работу после таймаута, предотвращая запись в _state от
    «брошенного» потока

Запуск:
    python engine_web.py [порт]

Базовая аутентификация (опционально):
    TRIGGERPARSE_USER=admin TRIGGERPARSE_PASS=secret python engine_web.py
"""

import sys
import os
import csv
import re
import io
import json
import copy
import base64
import hmac
import threading
import logging
import logging.handlers
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from email.parser import BytesParser
from email.policy import default as email_default
from string import Template
from typing import Callable, Optional
from collections import Counter
import time
import hashlib
import concurrent.futures
from urllib.parse import urlparse, parse_qs

# ==========================================================
# КОНСТАНТЫ
# ==========================================================
DEFAULT_CONFIG_FILE  = Path("default_config.json")
MAX_UPLOAD_BYTES     = 32 * 1024 * 1024
LOG_FILE             = Path("engine.log")
PROCESS_TIMEOUT_SEC  = 60
MAX_DEBUG_LOG_LINES  = 20000
MAX_SUSPICIOUS_SHOWN = 50
MAX_VALUE_DIST_SHOWN = 8

AUTH_USER    = os.environ.get('TRIGGERPARSE_USER', '')
AUTH_PASS    = os.environ.get('TRIGGERPARSE_PASS', '')
AUTH_ENABLED = bool(AUTH_USER and AUTH_PASS)


class LimitedLog(list):
    """Список строк debug-лога с ограничением размера."""
    def __init__(self, max_lines: int = MAX_DEBUG_LOG_LINES):
        super().__init__()
        self.max_lines = max_lines
        self.truncated = False
        self.dropped   = 0

    def append(self, item):
        if len(self) >= self.max_lines:
            if not self.truncated:
                super().append(
                    f'*** ЛОГ ОБРЕЗАН: достигнут лимит {self.max_lines} строк. '
                    f'Дальнейшие записи не сохраняются. ***'
                )
                self.truncated = True
                log.warning(f'debug_log обрезан на {self.max_lines} строках')
            self.dropped += 1
            return
        super().append(item)


# ==========================================================
# ЛОГИРОВАНИЕ
# ==========================================================

def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("triggerparse")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    try:
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError as e:
        logger.warning(f"Не удалось открыть лог-файл {LOG_FILE}: {e}")
    return logger


log = setup_logging()

# ==========================================================
# ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# ==========================================================

class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        # конфиг
        self.config     = None
        self.raw_config = None
        # debug-лог
        self.last_debug_log   = None
        self.last_debug_name  = None
        self.last_debug_token = None   # FIX: токен для валидации /debug_log/<token>
        # FIX: явная инициализация всех полей результата
        self.last_csv_bytes   = None
        self.last_json_bytes  = None
        self.last_xlsx_bytes  = None
        self.last_csv_name    = None
        self.last_stats       = None
        self.last_preview     = None
        self.last_token       = None
        self._progress        = {'pct': 0, 'msg': '', 'done': True}

    def set_config(self, raw: dict, compiled: dict):
        with self._lock:
            self.raw_config = raw
            self.config     = compiled

    def get_config(self):
        with self._lock:
            return self.raw_config, self.config

    def clear_config(self):
        with self._lock:
            self.raw_config = None
            self.config     = None

    def set_debug(self, debug_log, name: str, token: str = None):
        with self._lock:
            self.last_debug_log   = debug_log
            self.last_debug_name  = name
            self.last_debug_token = token

    def get_debug(self):
        with self._lock:
            return self.last_debug_log, self.last_debug_name, self.last_debug_token

    def set_result(self, csv_bytes: bytes, json_bytes: bytes,
                   xlsx_bytes: Optional[bytes], csv_name: str,
                   stats: dict, preview: list, token: str):
        with self._lock:
            self.last_csv_bytes  = csv_bytes
            self.last_json_bytes = json_bytes
            self.last_xlsx_bytes = xlsx_bytes
            self.last_csv_name   = csv_name
            self.last_stats      = stats
            self.last_preview    = preview
            self.last_token      = token

    def get_result(self):
        with self._lock:
            return (self.last_csv_bytes, self.last_json_bytes,
                    self.last_xlsx_bytes, self.last_csv_name,
                    self.last_stats, self.last_preview, self.last_token)

    def set_progress(self, pct: int, msg: str, done: bool = False):
        with self._lock:
            self._progress = {'pct': pct, 'msg': msg, 'done': done}

    def get_progress(self) -> dict:
        with self._lock:
            return self._progress.copy()


_state = AppState()


def decode_bytes(data: bytes) -> tuple[str, str]:
    try:
        import chardet
        detected = chardet.detect(data)
        enc  = detected.get('encoding') or ''
        conf = detected.get('confidence', 0) or 0
        if enc and conf >= 0.7:
            try:
                return data.decode(enc), enc
            except (UnicodeDecodeError, LookupError):
                pass
    except ImportError:
        pass
    for enc in ('utf-8-sig', 'utf-8', 'cp1251'):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1', errors='replace'), 'latin-1'


def try_load_default_config():
    if not DEFAULT_CONFIG_FILE.exists():
        return
    try:
        with open(DEFAULT_CONFIG_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        errs = validate_config(raw)
        if errs:
            raise ValueError("\n".join(errs))
        compiled = compile_config(raw)
        _state.set_config(raw, compiled)
        log.info(f"Конфигурация загружена из {DEFAULT_CONFIG_FILE}")
    except Exception as e:
        log.error(f"Ошибка загрузки конфига: {e}")

# ==========================================================
# ВСТРОЕННЫЕ ФУНКЦИИ-ПРЕДИКАТЫ
# ==========================================================

def _token_starts_upper(token: str) -> bool:
    t = token.strip(".,;:!?()[]{}")
    if not t or any(ch.isdigit() for ch in t):
        return False
    return t[0].isupper()

def _token_has_letter(token: str) -> bool:
    return any(ch.isalpha() for ch in token)

def _token_is_number_colon_dot(token: str) -> bool:
    clean = token.replace(' ', '')
    return bool(clean) and bool(re.fullmatch(r'[0-9А-ЯЁ.:]+', clean))

def _token_is_part_of_number_colon_dot(token: str) -> bool:
    if not _token_is_number_colon_dot(token):
        return False
    return any(ch.isdigit() or ch in '.:' for ch in token)

def _token_any(token: str) -> bool:
    return bool(token.strip())

BUILTIN_PREDICATES: dict[str, Callable[[str], bool]] = {
    'starts_upper':                _token_starts_upper,
    'has_letter':                  _token_has_letter,
    'looks_like_number_colon_dot': _token_is_number_colon_dot,
    'is_part_of_number_colon_dot': _token_is_part_of_number_colon_dot,
    'any':                         _token_any,
}

# ==========================================================
# ВАЛИДАЦИЯ КОНФИГА
# ==========================================================

def validate_config(config: dict) -> list[str]:
    errors = []
    if not isinstance(config, dict):
        return ["Конфиг должен быть объектом JSON"]
    for key in ("parser_name", "csv_columns", "triggers"):
        if key not in config:
            errors.append(f"Отсутствует обязательный ключ: '{key}'")
    if "parser_name" in config and not isinstance(config["parser_name"], str):
        errors.append("'parser_name' должен быть строкой")
    if "csv_columns" in config:
        cols = config["csv_columns"]
        if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
            errors.append("'csv_columns' должен быть списком строк")
    if "triggers" in config:
        csv_cols = set(config.get("csv_columns", []))
        triggers = config["triggers"]
        if not isinstance(triggers, dict) or len(triggers) == 0:
            errors.append("'triggers' должен быть непустым объектом")
        else:
            for tname, trig in triggers.items():
                if not isinstance(trig, dict):
                    errors.append(f"Триггер '{tname}' должен быть объектом")
                    continue
                if "aliases" not in trig:
                    errors.append(f"Триггер '{tname}': отсутствует 'aliases'")
                elif not isinstance(trig["aliases"], list) or len(trig["aliases"]) == 0:
                    errors.append(f"Триггер '{tname}': 'aliases' должен быть непустым списком строк")
                if "search_mode" not in trig:
                    errors.append(f"Триггер '{tname}': отсутствует 'search_mode'")
                elif trig["search_mode"] not in ("exact", "fuzzy", "regex"):
                    errors.append(f"Триггер '{tname}': недопустимый search_mode '{trig['search_mode']}'")
                if "csv_column" in trig and trig["csv_column"] not in csv_cols:
                    errors.append(
                        f"Триггер '{tname}': csv_column '{trig['csv_column']}' "
                        f"отсутствует в csv_columns")
                if "stop_words" in trig and not isinstance(trig["stop_words"], list):
                    errors.append(f"Триггер '{tname}': stop_words должен быть списком строк")
                if "heuristics" in trig and isinstance(trig["heuristics"], dict):
                    p = trig["heuristics"].get("priority")
                    if p is not None and not isinstance(p, int):
                        errors.append(f"Триггер '{tname}': heuristics.priority должен быть целым числом")
    if "tokenizer" in config:
        tok = config["tokenizer"]
        if not isinstance(tok, dict):
            errors.append("'tokenizer' должен быть объектом")
        elif tok.get("split_by") not in (None, "whitespace", "whitespace_and_punctuation"):
            errors.append("'tokenizer.split_by' должен быть 'whitespace' или 'whitespace_and_punctuation'")
    if "dedup" in config:
        dd = config["dedup"]
        if not isinstance(dd, dict):
            errors.append("'dedup' должен быть объектом")
        else:
            if "key" not in dd:
                errors.append("'dedup' должен содержать 'key' — имя поля-ключа")
            elif dd["key"] not in config.get("csv_columns", []):
                errors.append(f"'dedup.key' = '{dd['key']}' отсутствует в csv_columns")
    if "tests" in config:
        ts = config["tests"]
        if not isinstance(ts, list):
            errors.append("'tests' должен быть массивом")
        else:
            for ti, tc in enumerate(ts):
                if not isinstance(tc, dict):
                    errors.append(f"tests[{ti}] должен быть объектом"); continue
                if "input" not in tc:
                    errors.append(f"tests[{ti}]: нет поля input")
                if "expect" not in tc:
                    errors.append(f"tests[{ti}]: нет поля expect")
    if "max_distance" in config and not isinstance(config["max_distance"], int):
        errors.append("'max_distance' должен быть целым числом")
    if "require_first_char" in config and not isinstance(config["require_first_char"], bool):
        errors.append("'require_first_char' должен быть true или false")
    if "stop_words" in config and not isinstance(config["stop_words"], list):
        errors.append("'stop_words' должен быть списком строк")
    if "record_detection" in config:
        rd = config["record_detection"]
        if not isinstance(rd, dict):
            errors.append("'record_detection' должен быть объектом")
        else:
            if "trigger" not in rd:
                errors.append("'record_detection' должен содержать 'trigger'")
            if "mode" in rd and rd["mode"] not in ("trigger",):
                errors.append("'record_detection.mode' поддерживает только 'trigger'")
    return errors


# ==========================================================
# КОМПИЛЯЦИЯ КОНФИГА
# ==========================================================

def _compile_predicate_chain(expr: str) -> Callable[[str], bool]:
    parts = [p.strip() for p in expr.split('|')]
    funcs: list[Callable[[str], bool]] = []
    for part in parts:
        if part.startswith('regex:'):
            pattern = part[6:].strip()
            compiled = re.compile(pattern)
            funcs.append(lambda t, p=compiled: bool(p.search(t)))
        elif part in BUILTIN_PREDICATES:
            funcs.append(BUILTIN_PREDICATES[part])
        else:
            raise ValueError(f"Неизвестная функция: '{part}'")
    if len(funcs) == 1:
        return funcs[0]
    return lambda t, fs=funcs: any(f(t) for f in funcs)


def _compile_validation(rule: str) -> Callable[[str], bool]:
    if rule == 'not_empty':
        return lambda v: bool(v.strip())
    if rule.startswith('regex:'):
        pattern = rule[6:].strip()
        return lambda v, p=pattern: bool(re.fullmatch(p, v))
    if rule.startswith('word_count:'):
        parts = rule.split(':')[1]
        mn, mx = map(int, parts.split(','))
        return lambda v, lo=mn, hi=mx: lo <= len(v.split()) <= hi
    return lambda v: True


def compile_config(raw_config: dict) -> dict:
    config = copy.deepcopy(raw_config)
    config.setdefault('version', '1.0')
    config.setdefault('max_distance', 1)
    config.setdefault('require_first_char', True)
    config.setdefault('stop_words', [])
    config.setdefault('log_suspicious', False)
    config.setdefault('debug_logging', False)
    config['stop_words'] = {w.lower() for w in config['stop_words']}

    if 'record_detection' in config:
        rd = config['record_detection']
        rd.setdefault('mode', 'trigger')
        ch = rd.get('continuation_heuristics')
        if ch and 'detect_by' in ch:
            ch['_detect'] = _compile_predicate_chain(ch['detect_by'])

    tok = config.setdefault('tokenizer', {'split_by': 'whitespace'})
    tok.setdefault('split_by', 'whitespace')

    for tname, trig in config.get('triggers', {}).items():
        trig.setdefault('csv_column', tname)
        trig.setdefault('on_new_record', False)
        trig.setdefault('multi_token', None)
        trig.setdefault('normalization', None)
        trig.setdefault('validation', None)
        trig.setdefault('heuristics', None)
        trig.setdefault('replacements', None)
        trig.setdefault('collector', None)
        sw = trig.get('stop_words')
        trig['_stop_words'] = {w.lower() for w in sw} if sw else set()

        if trig.get('search_mode') == 'regex':
            trig['_compiled_regex'] = re.compile(trig['aliases'][0], re.IGNORECASE)

        if trig.get('validation'):
            rule = trig['validation'].get('rule', '')
            trig['validation']['_func'] = _compile_validation(rule)

        heur = trig.get('heuristics')
        if heur:
            if 'detect_by' in heur:
                heur['_detect'] = _compile_predicate_chain(heur['detect_by'])
            if 'unless' in heur:
                heur['_unless'] = _compile_predicate_chain(heur['unless'])
            if 'token_rule' in heur:
                heur['_token_rule'] = _compile_predicate_chain(heur['token_rule'])
            heur.setdefault('priority', 100)

        coll = trig.get('collector')
        if coll and 'token_rule' in coll:
            coll['_token_rule'] = _compile_predicate_chain(coll['token_rule'])

        mt = trig.get('multi_token')
        if mt and mt.get('enabled') and 'token_rule' in mt:
            mt['_token_rule'] = _compile_predicate_chain(mt['token_rule'])

    config['triggers'] = dict(
        sorted(
            config['triggers'].items(),
            key=lambda kv: (kv[1].get('heuristics') or {}).get('priority', 100)
        )
    )
    return config

# ==========================================================
# ЛЕВЕНШТЕЙН
# ==========================================================

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1, start=1):
        curr = [i]
        for j, c2 in enumerate(s2, start=1):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]

# ==========================================================
# КЛАССИФИКАТОР
# ==========================================================

def build_classifier(config: dict, debug_log: Optional[list] = None) -> Callable[[str], Optional[str]]:
    triggers      = config['triggers']
    max_dist      = config['max_distance']
    require_first = config['require_first_char']
    stop_words    = config['stop_words']
    _cache: dict[str, Optional[str]] = {}
    use_cache = debug_log is None

    def classifier(raw_token: str) -> Optional[str]:
        if use_cache and raw_token in _cache:
            return _cache[raw_token]
        clean = "".join(ch for ch in raw_token.lower() if ch.isalpha())
        if not clean:
            if debug_log is not None:
                debug_log.append(f"    classify: '{raw_token}' -> нет букв")
            if use_cache: _cache[raw_token] = None
            return None
        if clean in stop_words:
            if debug_log is not None:
                debug_log.append(f"    classify: '{raw_token}' -> стоп-слово")
            if use_cache: _cache[raw_token] = None
            return None
        if debug_log is not None:
            debug_log.append(f"    classify: '{raw_token}' (clean='{clean}')")

        best_trigger  = None
        best_distance = 999

        for tname, trig in triggers.items():
            mode    = trig.get('search_mode', 'fuzzy')
            aliases = trig.get('aliases', [])

            if mode == 'exact':
                if clean in [a.lower() for a in aliases]:
                    if debug_log is not None:
                        debug_log.append(f"      {tname}: exact match")
                    if use_cache: _cache[raw_token] = tname
                    return tname
                continue

            if mode == 'regex':
                if trig['_compiled_regex'].fullmatch(raw_token):
                    if debug_log is not None:
                        debug_log.append(f"      {tname}: regex match")
                    if use_cache: _cache[raw_token] = tname
                    return tname
                continue

            for alias in aliases:
                alias_clean = "".join(ch for ch in alias.lower() if ch.isalpha())
                if not alias_clean:
                    continue
                if require_first and clean[0] != alias_clean[0]:
                    if debug_log is not None:
                        debug_log.append(f"      {tname}: alias='{alias}' первый символ не совпадает")
                    continue
                dist = levenshtein_distance(clean, alias_clean)
                if debug_log is not None:
                    debug_log.append(f"      {tname}: alias='{alias}' dist={dist}")
                if dist < best_distance:
                    best_distance = dist
                    best_trigger  = tname

        result = best_trigger if (best_trigger is not None and best_distance <= max_dist) else None
        if debug_log is not None:
            if result:
                debug_log.append(f"    -> триггер '{result}' (dist={best_distance})")
            else:
                debug_log.append(f"    -> не найден (best_dist={best_distance})")
        if use_cache:
            _cache[raw_token] = result
        return result

    return classifier


# ==========================================================
# НОРМАЛИЗАЦИЯ
# ==========================================================

def _apply_normalization_step(value: str, step: str, replacements: Optional[dict]) -> str:
    if step == 'strip':               return value.strip()
    if step == 'remove_trailing_dot': return value.rstrip('.')
    if step == 'remove_dots':         return value.replace('.', '')
    if step == 'remove_spaces':       return value.replace(' ', '')
    if step == 'collapse_spaces':     return re.sub(r'\s+', ' ', value).strip()
    if step == 'uppercase':           return value.upper()
    if step == 'lowercase':           return value.lower()
    if step == 'digits_only':         return re.sub(r'\D', '', value)

    if step.startswith('replace_char:'):
        body = step[len('replace_char:'):]
        internal = False
        if body.startswith('internal:'):
            internal = True
            body = body[len('internal:'):]
        if '->' in body:
            src, dst = body.split('->', 1)
            if internal:
                return re.sub(r'(?<=\S)' + re.escape(src) + r'(?=\S)', dst, value)
            return value.replace(src, dst)

    if step == 'apply_replacements':
        if replacements:
            for old_str, new_str in replacements.items():
                value = value.replace(old_str, new_str)
        return value

    if step.startswith('replace_dot_before_keywords:'):
        keys     = step.split(':', 1)[1]
        keywords = [k.strip() for k in keys.split(',')]
        pattern  = r'\.(?=\s*(?:' + '|'.join(re.escape(k) for k in keywords) + r')(?:\.|\b))'
        return re.sub(pattern, ',', value, flags=re.IGNORECASE)

    if step.startswith('replace_dot_after_keywords:'):
        keys     = step.split(':', 1)[1]
        keywords = [k.strip() for k in keys.split(',')]
        pattern  = r'\b(' + '|'.join(re.escape(k) for k in keywords) + r')\.(?=[\s,]|$)'
        return re.sub(pattern, r'\1', value, flags=re.IGNORECASE)

    if step.startswith('replace_space_before_keywords:'):
        keys     = step.split(':', 1)[1]
        keywords = [k.strip() for k in keys.split(',')]
        pattern  = r'(?<=[^\s,])\s+(?=(?:' + '|'.join(re.escape(k) for k in keywords) + r')\b)'
        result   = re.sub(pattern, ', ', value, flags=re.IGNORECASE)
        result   = re.sub(r',\s+([а-яёa-z])', lambda m: ', ' + m.group(1).upper(), result)
        return result

    if step.startswith('regex_sub:'):
        expr = step[len('regex_sub:'):]
        if '->' in expr:
            pat, repl = expr.split('->', 1)
            return re.sub(pat.strip(), repl.strip(), value)

    if step.startswith('normalize_number'):
        parts    = step.split(':')
        dec_sep  = parts[1] if len(parts) > 1 else ','
        thou_sep = parts[2] if len(parts) > 2 else ' '
        v = value.strip()
        if thou_sep:
            v = v.replace(thou_sep, '')
        v = v.replace(' ', '')
        if dec_sep and dec_sep != '.':
            v = v.replace(dec_sep, '.')
        return v

    if step == 'to_int':
        try:
            return str(int(float(value.replace(',', '.'))))
        except ValueError:
            return value

    if step.startswith('to_float:'):
        n = int(step.split(':', 1)[1])
        try:
            rounded = round(float(value.replace(',', '.')), n)
            return str(int(rounded)) if n == 0 else str(rounded)
        except ValueError:
            return value

    if step.startswith('pad_left:'):
        parts = step.split(':')
        n    = int(parts[1])
        char = parts[2] if len(parts) > 2 else '0'
        return value.rjust(n, char)

    if step.startswith('pad_right:'):
        parts = step.split(':')
        n    = int(parts[1])
        char = parts[2] if len(parts) > 2 else '0'
        return value.ljust(n, char)

    return value


def make_normalizer(pipeline: list, replacements: Optional[dict] = None) -> Callable[[str], str]:
    def normalize(value: str) -> str:
        for step in pipeline:
            value = _apply_normalization_step(value, step, replacements)
        return value.strip()
    return normalize

# ==========================================================
# УТИЛИТЫ ТЕКСТА
# ==========================================================

# FIX: _UNICODE_SPACE_RE удалён — был объявлен, но нигде не использовался.
# normalize_whitespace выполняет то же самое напрямую через inline-regex.

def normalize_whitespace(text: str) -> str:
    text = re.sub('[\ufeff\u200b\u200c\u200d\u00ad]', '', text)
    text = re.sub('[\u00a0\u2009\u202f\u2002\u2003\u2007\u2008\t\r\n]+', ' ', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def tokenize_text(text: str, config: dict) -> list[str]:
    mode = config.get('tokenizer', {}).get('split_by', 'whitespace')
    if mode == 'whitespace_and_punctuation':
        tokens = re.split(r'(\s+|(?<=[^\s]),)', text)
        return [t for t in tokens if t and not t.isspace()]
    return text.split()


def clean_text(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\[[^\[\]]*\]", " ", text)
    return normalize_whitespace(text)


# ==========================================================
# ПАРСЕР ЗАПИСИ
# ==========================================================

def parse_single_record(
    tokens: list,
    config: dict,
    classify: Callable[[str], Optional[str]],
    suspicious_log: Counter,
    debug_log: Optional[list] = None,
) -> dict:
    triggers = config['triggers']
    record:        dict               = {}
    current_field: Optional[str]      = None
    last_field:    Optional[str]      = None
    value_buffer:  list               = []
    errors:        set                = set()
    collector_mode:  bool             = False
    collector_limit: int              = 0
    collector_count: int              = 0
    collector_rule:  Optional[Callable] = None

    def _log(msg: str):
        if debug_log is not None:
            debug_log.append(msg)

    def save_field():
        nonlocal current_field, last_field, value_buffer
        if current_field is None:
            value_buffer = []
            return
        trig = triggers.get(current_field)
        if trig is None:
            _log(f"  save_field '{current_field}': нет в конфиге, отброшено")
            value_buffer  = []
            current_field = None
            return
        value      = " ".join(value_buffer).strip()
        norm_cfg   = trig.get('normalization') or {}
        pipeline   = norm_cfg.get('pipeline', ['strip', 'collapse_spaces'])
        normalizer = make_normalizer(pipeline, trig.get('replacements'))
        normalized = normalizer(value)
        _log(f"  save_field '{current_field}': raw='{value}' -> norm='{normalized}'")
        if normalized:
            valid_cfg = trig.get('validation')
            if valid_cfg and '_func' in valid_cfg:
                if not valid_cfg['_func'](normalized):
                    err = valid_cfg.get('error_code', 'errVAL')
                    errors.add(err)
                    _log(f"    валидация не пройдена: {err}")
            csv_col = trig.get('csv_column', current_field)
            if csv_col in record:
                record[csv_col] += " " + normalized
            else:
                record[csv_col] = normalized
        last_field    = current_field
        current_field = None
        value_buffer  = []

    def open_field(name: str, first_token: Optional[str] = None,
                   err_code: Optional[str] = None, with_collector: bool = False):
        nonlocal current_field, last_field, value_buffer
        nonlocal collector_mode, collector_limit, collector_count, collector_rule
        save_field()
        current_field = name
        value_buffer  = [first_token] if first_token is not None else []
        if err_code:
            errors.add(err_code)
        trig_cfg = triggers.get(name, {})
        coll = trig_cfg.get('collector') if with_collector else None
        if coll:
            collector_mode  = True
            collector_limit = coll.get('max_tokens', 10)
            collector_count = len(value_buffer)
            collector_rule  = coll.get('_token_rule', _token_any)
        else:
            collector_mode = False
            collector_rule = None

    _log("--- Record start ---")
    _log(f"Tokens: {tokens}")

    i = 0
    while i < len(tokens):
        token = tokens[i]

        # 1. Collector-режим
        if collector_mode and collector_rule:
            _guard_hit = classify(token) is not None
            if not _guard_hit and collector_count < collector_limit and collector_rule(token):
                value_buffer.append(token)
                collector_count += 1
                _log(f"Token {i}: '{token}' | collector ({collector_count}/{collector_limit})")
                i += 1
                continue
            else:
                reason = "trigger guard" if _guard_hit else "done/rule"
                _log(f"Token {i}: '{token}' | collector {reason}, re-processing")
                save_field()
                current_field  = None
                collector_mode = False
                collector_rule = None
                continue

        _log(f"Token {i}: '{token}' | field={current_field}, buf={value_buffer}")

        # Стоп-слова
        clean_alpha      = "".join(ch for ch in token.lower() if ch.isalpha())
        field_stop_words = (triggers.get(current_field) or {}).get('_stop_words', set())
        is_stop          = clean_alpha in config['stop_words'] or clean_alpha in field_stop_words
        if is_stop:
            err_code = (triggers.get(current_field) or {}).get('stop_word_error', 'errSTOP')
            errors.add(err_code)
            _log(f"  -> stop_word ('{token}'), err={err_code}")
            i += 1
            continue

        # 2. Явный триггер
        trigger = classify(token)
        if trigger is not None:
            _log(f"  found trigger: '{trigger}'")
            open_field(trigger)
            i += 1
            continue

        # 3. Multi-token
        trig_cfg = triggers.get(current_field) if current_field else None
        if (trig_cfg and isinstance(trig_cfg.get('multi_token'), dict)
                and trig_cfg['multi_token'].get('enabled')):
            rule = trig_cfg['multi_token'].get('_token_rule', _token_any)
            if rule(token):
                value_buffer.append(token)
                _log(f"  multi_token: принят")
                i += 1
                continue
            else:
                _log(f"  multi_token: отклонён ('{token}'), закрываем поле")
                save_field()
                current_field = None

        # 4. Эвристики
        effective_field = current_field if current_field is not None else last_field
        _log(f"  trigger not found, checking heuristics (current_field={current_field}, last_field={last_field})")
        used = False
        for tname, trig_h in triggers.items():
            heur = trig_h.get('heuristics')
            if not heur or '_detect' not in heur:
                continue
            if_missing_after = heur.get('if_missing_after')
            if if_missing_after and effective_field != if_missing_after:
                _log(f"    {tname}: if_missing_after={if_missing_after} != {effective_field}")
                continue
            unless_fn = heur.get('_unless')
            if unless_fn and unless_fn(token):
                _log(f"    {tname}: unless matched")
                continue
            if heur['_detect'](token):
                err = heur.get('error_code', f'err{tname.upper()}')
                _log(f"    {tname}: heuristic matched, err={err}")
                open_field(tname, first_token=token, err_code=err, with_collector=True)
                used = True
                i += 1
                break

        # 5. Добавляем к текущему полю или теряем
        if not used:
            if current_field is not None:
                value_buffer.append(token)
                _log(f"  -> added to field '{current_field}'")
            else:
                if config.get('log_suspicious'):
                    suspicious_log[token] += 1
                _log(f"  -> no active field, token lost")
            i += 1

    save_field()
    if errors:
        record['err'] = "; ".join(sorted(errors))
    _log("--- Record end ---")
    return record


# ==========================================================
# СЕГМЕНТАЦИЯ
# ==========================================================

def segment_text(
    text: str,
    config: dict,
    classify: Callable[[str], Optional[str]],
    debug_log: Optional[list] = None,
) -> list[list[str]]:
    rd = config.get('record_detection')
    if not rd:
        return [text.split()]

    trigger_name   = rd['trigger']
    tokens         = tokenize_text(text, config)
    records:       list[list[str]] = []
    current_record: list[str]      = []

    if debug_log is not None:
        debug_log.append(f"=== SEGMENTATION: trigger='{trigger_name}' ===")

    for token in tokens:
        if classify(token) == trigger_name:
            if current_record:
                if debug_log is not None:
                    debug_log.append(f"  new record: {current_record[:3]}...")
                records.append(current_record)
            current_record = [token]
        else:
            current_record.append(token)
    if current_record:
        records.append(current_record)

    if debug_log is not None:
        debug_log.append(f"  total records after split: {len(records)}")

    ch = rd.get('continuation_heuristics')
    if ch and '_detect' in ch:
        max_tokens  = ch.get('max_tokens_to_check', 5)
        merge_limit = max(1, len(records) - 1)
        merge_count = 0

        merged: list[list[str]] = []
        prev:   Optional[list[str]] = None

        for rec in records:
            if prev is not None:
                # FIX: три явные взаимоисключающие ветки вместо вложенных условий
                # с общей переменной should_merge — устранена зависимость от порядка.
                starts_with_trigger = bool(rec) and classify(rec[0]) == trigger_name

                if starts_with_trigger:
                    # Новая запись начинается с триггера — не сливаем
                    should_merge = False
                elif merge_count >= merge_limit:
                    # Достигнут лимит слияний — не сливаем
                    should_merge = False
                    if debug_log is not None:
                        debug_log.append(
                            f"  ВНИМАНИЕ: достигнут лимит слияний ({merge_limit}), "
                            f"дальнейшее слияние остановлено"
                        )
                else:
                    # Проверяем эвристику продолжения
                    check_tokens = rec[:max_tokens]
                    should_merge = any(ch['_detect'](t) for t in check_tokens)

                if debug_log is not None:
                    debug_log.append(
                        f"  continuation check: {rec[:max_tokens]} "
                        f"starts_with_trigger={starts_with_trigger} "
                        f"merge={should_merge} ({merge_count}/{merge_limit})"
                    )
                if should_merge:
                    prev.extend(rec)
                    merge_count += 1
                else:
                    merged.append(prev)
                    prev        = rec
                    merge_count = 0
            else:
                prev = rec

        if prev is not None:
            merged.append(prev)
        records = merged

        if debug_log is not None:
            debug_log.append(f"  total records after merge: {len(records)}")

    return records

# ==========================================================
# ГЛАВНАЯ ФУНКЦИЯ ПАРСИНГА
# ==========================================================

_CSV_FORMULA_CHARS = ('=', '+', '-', '@', '\t', '\r')


def _csv_escape(value: str) -> str:
    if value and value[0] in _CSV_FORMULA_CHARS:
        return "'" + value
    return value


def build_json_bytes(records: list[dict], columns: list[str]) -> bytes:
    cols = columns + (['err'] if 'err' not in columns else [])
    out  = [{c: r.get(c, '') for c in cols} for r in records]
    return json.dumps(out, ensure_ascii=False, indent=2).encode('utf-8')


def build_xlsx_bytes(records: list[dict], columns: list[str]) -> Optional[bytes]:
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return None

    cols = columns + (['err'] if 'err' not in columns else [])
    wb   = openpyxl.Workbook()
    ws   = wb.active
    ws.title = "Данные"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1A2540")
    for ci, col in enumerate(cols, start=1):
        cell           = ws.cell(row=1, column=ci, value=col)
        cell.font      = header_font
        cell.fill      = header_fill
        cell.alignment = Alignment(horizontal="center")

    err_fill = PatternFill("solid", fgColor="FFF0F0")
    for ri, rec in enumerate(records, start=2):
        has_err = bool(rec.get('err'))
        for ci, col in enumerate(cols, start=1):
            cell = ws.cell(row=ri, column=ci, value=rec.get(col, '') or '')
            if has_err:
                cell.fill = err_fill

    for ci, col in enumerate(cols, start=1):
        values  = [len(str(col))] + [len(str(r.get(col, '') or '')) for r in records]
        max_len = max(values) if values else 10
        ws.column_dimensions[
            openpyxl.utils.get_column_letter(ci)
        ].width = min(max_len + 4, 60)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _fmt_uptime(sec: int) -> str:
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, s   = divmod(sec, 60)
    parts = []
    if d: parts.append(f'{d}д')
    if h: parts.append(f'{h}ч')
    if m: parts.append(f'{m}м')
    parts.append(f'{s}с')
    return ' '.join(parts)


def run_tests(config: dict) -> dict:
    tests = config.get('tests', [])
    if not tests:
        return {'total': 0, 'passed': 0, 'failed': 0, 'results': [],
                'error': 'Секция tests отсутствует или пуста'}
    total = passed = failed = 0
    results = []
    for tc in tests:
        desc    = tc.get('description', f'Test #{total+1}')
        inp     = tc.get('input', '')
        expect  = tc.get('expect', {})
        rec_idx = tc.get('expect_record', 0)
        total  += 1
        try:
            records = parse_text(inp, config, Counter())
        except Exception as e:
            failed += 1
            results.append({'description': desc, 'status': 'fail',
                'details': [{'field': '(parse)', 'expected': '', 'got': str(e), 'ok': False}]})
            continue
        if rec_idx >= len(records):
            failed += 1
            results.append({'description': desc, 'status': 'fail',
                'details': [{'field': '(records)',
                             'expected': f'>= {rec_idx+1}',
                             'got': str(len(records)), 'ok': False}]})
            continue
        rec     = records[rec_idx]
        details = []
        ok_all  = True
        for field, exp_val in expect.items():
            got = str(rec.get(field, '') or '')
            ok  = got == str(exp_val)
            if not ok:
                ok_all = False
            details.append({'field': field, 'expected': str(exp_val), 'got': got, 'ok': ok})
        if ok_all: passed += 1
        else:      failed += 1
        results.append({'description': desc,
                        'status': 'pass' if ok_all else 'fail',
                        'details': details})
        log.debug(f"Test '{desc}': {'PASS' if ok_all else 'FAIL'}")
    log.info(f'Tests: {passed}/{total} passed')
    return {'total': total, 'passed': passed, 'failed': failed, 'results': results}


def detect_duplicates(records: list[dict], config: dict) -> int:
    dd = config.get('dedup')
    if not dd:
        return 0
    key_field      = dd.get('key', '')
    error_code     = dd.get('error_code', 'errDUP')
    case_sensitive = dd.get('case_sensitive', False)
    seen:  set = set()
    count: int = 0
    for rec in records:
        raw_val = str(rec.get(key_field) or '').strip()
        if not raw_val:
            continue
        key_val = raw_val if case_sensitive else raw_val.lower()
        if key_val in seen:
            existing = rec.get('err', '')
            codes    = {c.strip() for c in existing.split(';') if c.strip()}
            codes.add(error_code)
            rec['err'] = '; '.join(sorted(codes))
            log.debug(f"Дубль: {key_field}={raw_val!r}")
            count += 1
        else:
            seen.add(key_val)
    return count


def compute_stats(records: list[dict], config: dict) -> dict:
    csv_columns = config.get('csv_columns', [])
    total       = len(records)
    with_errors = sum(1 for r in records if r.get('err'))
    clean       = total - with_errors

    err_counter: Counter = Counter()
    for r in records:
        for code in (r.get('err') or '').split(';'):
            code = code.strip()
            if code:
                err_counter[code] += 1

    field_fill: dict[str, int] = {}
    for col in csv_columns:
        field_fill[col] = sum(1 for r in records if r.get(col, '').strip())

    value_distribution: dict[str, dict] = {}
    for col in csv_columns:
        counter = Counter()
        for r in records:
            val = (r.get(col) or '').strip()
            if val:
                counter[val] += 1
        repeated = [(v, c) for v, c in counter.most_common() if c > 1][:MAX_VALUE_DIST_SHOWN]
        value_distribution[col] = {
            'unique':         len(counter),
            'filled':         sum(counter.values()),
            'repeated':       repeated,
            'repeated_total': sum(1 for c in counter.values() if c > 1),
        }

    duplicates = sum(1 for r in records if 'errDUP' in (r.get('err') or ''))
    return {
        'total':              total,
        'clean':              clean,
        'with_errors':        with_errors,
        'error_rate':         round(with_errors / total * 100, 1) if total else 0.0,
        'top_errors':         err_counter.most_common(10),
        'field_fill':         field_fill,
        'duplicates':         duplicates,
        'value_distribution': value_distribution,
    }


def parse_text(
    text: str,
    config: dict,
    suspicious_log: Counter,
    debug_log: Optional[list] = None,
) -> list[dict]:
    text     = clean_text(text)
    classify = build_classifier(config, debug_log)

    records_tokens = segment_text(text, config, classify, debug_log)

    if debug_log is not None:
        debug_log.append(f"=== PARSING {len(records_tokens)} records ===")

    all_records = []
    for idx, rec_tokens in enumerate(records_tokens):
        if debug_log is not None:
            debug_log.append(f"--- Record {idx + 1}/{len(records_tokens)} ---")
        rec = parse_single_record(rec_tokens, config, classify, suspicious_log, debug_log)
        all_records.append(rec)

    if debug_log is not None:
        debug_log.append("=== PARSING COMPLETE ===")
        debug_log.append(f"Total records: {len(all_records)}")

    dup_count = detect_duplicates(all_records, config)
    if dup_count:
        log.info(f"Найдено дублей: {dup_count}")

    return all_records


# ==========================================================
# ДОКУМЕНТАЦИЯ
# ==========================================================

_DOCS: dict = {
    "top_level": [
        ("parser_name",       "string", "Обязательный. Название парсера для отображения."),
        ("version",           "string", "Версия конфига. По умолчанию '1.0'."),
        ("csv_columns",       "array",  "Обязательный. Список имён колонок в выходном CSV."),
        ("max_distance",      "int",    "Макс. расстояние Левенштейна для fuzzy-поиска. По умолчанию 1."),
        ("require_first_char","bool",   "Если true — fuzzy сравнивает только алиасы с тем же первым символом. По умолчанию true."),
        ("stop_words",        "array",  "Глобальные стоп-слова. Добавляют errSTOP."),
        ("log_suspicious",    "bool",   "Логировать токены не попавшие ни в одно поле. По умолчанию false."),
        ("debug_logging",     "bool",   "Включить пошаговый лог парсинга. По умолчанию false."),
        ("process_timeout",   "int",    f"Лимит времени обработки в секундах. По умолчанию {PROCESS_TIMEOUT_SEC}."),
        ("tokenizer",         "object", "Настройки токенизатора. split_by: 'whitespace' (умолч.) или 'whitespace_and_punctuation'."),
        ("dedup",             "object", "Детектор дублей. Поля: key, error_code (умолч. errDUP), case_sensitive (умолч. false)."),
        ("record_detection",  "object", "Сегментация на записи. Поля: mode ('trigger'), trigger, continuation_heuristics."),
    ],
    "trigger": [
        ("aliases",         "array",  "Обязательный. Варианты написания триггерного слова."),
        ("search_mode",     "string", "Обязательный. Режим: 'fuzzy', 'exact', 'regex'."),
        ("csv_column",      "string", "Целевая колонка CSV. По умолчанию — имя триггера."),
        ("on_new_record",   "bool",   "Если true — триггер начинает новую запись при сегментации."),
        ("normalization",   "object", "Нормализация. Поле pipeline: список шагов."),
        ("validation",      "object", "Валидация. Поля: rule, error_code."),
        ("heuristics",      "object", "Эвристика. Поля: detect_by, if_missing_after, unless, error_code, priority."),
        ("collector",       "object", "Сборщик значений. Поля: token_rule, max_tokens."),
        ("multi_token",     "object", "Многотокенное поле. Поля: enabled, token_rule."),
        ("replacements",    "object", "Словарь замен {старое: новое}. Применяется шагом apply_replacements."),
        ("stop_words",      "array",  "Стоп-слова на уровне триггера."),
        ("stop_word_error", "string", "Код ошибки для стоп-слова. По умолчанию errSTOP."),
    ],
    "normalization": [
        ("strip",                              "Убрать пробелы по краям."),
        ("collapse_spaces",                    "Схлопнуть множественные пробелы."),
        ("remove_dots",                        "Удалить все точки."),
        ("remove_trailing_dot",                "Удалить точку в конце."),
        ("remove_spaces",                      "Удалить все пробелы."),
        ("uppercase / lowercase",              "Привести к верхнему / нижнему регистру."),
        ("digits_only",                        "Оставить только цифры."),
        ("replace_char:FROM->TO",              "Заменить символ FROM на TO."),
        ("replace_char:internal:FROM->TO",     "Заменить FROM на TO между не-пробельными символами."),
        ("apply_replacements",                 "Применить словарь replacements."),
        ("replace_dot_before_keywords:kw,...", "Заменить точку перед ключевым словом на запятую."),
        ("replace_dot_after_keywords:kw,...",  "Удалить точку после ключевого слова."),
        ("replace_space_before_keywords:kw,...","Заменить пробел перед ключевым словом на ', '."),
        ("normalize_number[:dec[:thou]]",      "Унифицировать числовой формат. Пример: normalize_number:,:"),
        ("to_int",                             "Взять целую часть числа."),
        ("to_float:N",                         "Округлить до N знаков."),
        ("pad_left:N[:char]",                  "Дополнить слева до длины N."),
        ("pad_right:N[:char]",                 "Дополнить справа до длины N."),
        ("regex_sub:PATTERN->REPL",            "Замена по регулярному выражению."),
    ],
    "predicates": [
        ("starts_upper",                "Токен начинается с заглавной буквы (не цифра)."),
        ("has_letter",                  "Токен содержит хотя бы одну букву."),
        ("looks_like_number_colon_dot", "Токен состоит только из цифр, букв, точек и двоеточий."),
        ("is_part_of_number_colon_dot", "То же + содержит хотя бы цифру или точку/двоеточие."),
        ("any",                         "Любой непустой токен."),
        ("regex:PATTERN",               "Токен совпадает с регулярным выражением."),
        ("pred1 | pred2",               "Логическое ИЛИ предикатов."),
    ],
}


def _escape_html(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def _build_docs_html() -> str:
    def section(title: str, rows: list, three_col: bool = False) -> str:
        if three_col:
            header = "<tr><th>Шаг</th><th>Описание</th></tr>"
            body   = "".join(
                f"<tr><td><code>{_escape_html(k)}</code></td>"
                f"<td>{_escape_html(v)}</td></tr>"
                for k, v in rows
            )
        else:
            header = "<tr><th>Поле</th><th>Тип</th><th>Описание</th></tr>"
            body   = "".join(
                f"<tr><td><code>{_escape_html(k)}</code></td>"
                f"<td><span class='type'>{_escape_html(t)}</span></td>"
                f"<td>{_escape_html(d)}</td></tr>"
                for k, t, d in rows
            )
        return (f"<h3>{title}</h3>"
                f"<table class='doc-table'><thead>{header}</thead>"
                f"<tbody>{body}</tbody></table>")

    body = (
        section("Корневые ключи конфига", _DOCS["top_level"]) +
        section("Поля триггера", _DOCS["trigger"]) +
        section("Шаги нормализации", _DOCS["normalization"], three_col=True) +
        section("Предикаты (detect_by / token_rule)", _DOCS["predicates"], three_col=True)
    )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>TriggerParse — Документация конфига</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Manrope:wght@400;600;800&display=swap');
  :root{{--bg:#0f1117;--surface:#181c27;--border:#2a2f42;--accent:#5b8cff;--text:#d4daf5;--muted:#7a83a6;--mono:'JetBrains Mono',monospace;--sans:'Manrope',sans-serif;}}
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{background:var(--bg);color:var(--text);font-family:var(--sans);padding:32px 28px;max-width:1100px;margin:0 auto;}}
  header{{display:flex;align-items:baseline;gap:14px;margin-bottom:28px;border-bottom:1px solid var(--border);padding-bottom:18px;}}
  header h1{{font-size:1.4rem;font-weight:800;}} header h1 span{{color:var(--accent);}}
  header a{{margin-left:auto;color:var(--accent);font-size:.85rem;text-decoration:none;}}
  h3{{font-size:.95rem;font-weight:700;color:var(--accent);margin:28px 0 10px;text-transform:uppercase;letter-spacing:.05em;}}
  .doc-table{{width:100%;border-collapse:collapse;font-size:.82rem;margin-bottom:8px;}}
  .doc-table th{{background:var(--surface);color:var(--muted);padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);font-weight:600;font-size:.75rem;text-transform:uppercase;}}
  .doc-table td{{padding:7px 12px;border-bottom:1px solid var(--border);vertical-align:top;line-height:1.5;}}
  .doc-table tr:last-child td{{border-bottom:none;}}
  .doc-table tr:hover td{{background:rgba(91,140,255,.05);}}
  .doc-table code{{font-family:var(--mono);font-size:.8rem;color:var(--accent);white-space:nowrap;}}
  .type{{font-family:var(--mono);font-size:.75rem;color:#f0a030;background:rgba(240,160,48,.1);padding:1px 6px;border-radius:4px;}}
</style>
</head>
<body>
<header><h1>Trigger<span>Parse</span> — Документация конфига</h1><a href="/">← Назад</a></header>
{body}
</body></html>"""


# ==========================================================
# HTML-ШАБЛОН
# ==========================================================

_HTML_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>TriggerParse Engine v3.1</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAzMiAzMiI+CiAgPHJlY3Qgd2lkdGg9IjMyIiBoZWlnaHQ9IjMyIiByeD0iNiIgZmlsbD0iIzBmMTExNyIvPgogIDx0ZXh0IHg9IjE2IiB5PSIyNCIgZm9udC1mYW1pbHk9Im1vbm9zcGFjZSIgZm9udC1zaXplPSIyMiIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiM1YjhjZmYiIHRleHQtYW5jaG9yPSJtaWRkbGUiPlQ8L3RleHQ+PC9zdmc+">
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Manrope:wght@400;600;800&display=swap');
  :root{--bg:#0f1117;--surface:#181c27;--border:#2a2f42;--accent:#5b8cff;--accent2:#38d9a9;--text:#d4daf5;--muted:#7a83a6;--danger:#ff6b6b;--success:#38d9a9;--mono:'JetBrains Mono',monospace;--sans:'Manrope',sans-serif;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;padding:32px 28px;}
  header{display:flex;align-items:baseline;gap:14px;margin-bottom:28px;border-bottom:1px solid var(--border);padding-bottom:18px;}
  header h1{font-size:1.5rem;font-weight:800;letter-spacing:-.5px;} header h1 span{color:var(--accent);}
  .ver{font-size:.72rem;color:var(--muted);font-family:var(--mono);}
  .status-bar{padding:10px 14px;border-radius:8px;font-size:.85rem;background:var(--surface);border:1px solid var(--border);margin-bottom:22px;}
  .status-bar .ok{color:var(--success);font-weight:600;} .status-bar .fail{color:var(--danger);font-weight:600;}
  .tabs{display:flex;gap:4px;margin-bottom:-1px;}
  .tab-btn{padding:8px 20px;background:transparent;border:1px solid var(--border);border-bottom:none;color:var(--muted);cursor:pointer;border-radius:6px 6px 0 0;font-family:var(--sans);font-size:.85rem;font-weight:600;transition:background .15s,color .15s;}
  .tab-btn:hover{background:var(--surface);color:var(--text);}
  .tab-btn.active{background:var(--surface);color:var(--accent);border-bottom-color:var(--surface);}
  .tab-panel{display:none;background:var(--surface);border:1px solid var(--border);border-radius:0 8px 8px 8px;padding:24px;}
  .tab-panel.active{display:block;}
  h3{font-size:1rem;font-weight:700;margin-bottom:16px;color:var(--text);}
  label{display:block;font-size:.82rem;color:var(--muted);margin-bottom:5px;margin-top:14px;}
  input[type=file],input[type=text]{width:100%;padding:9px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:var(--mono);font-size:.83rem;outline:none;transition:border-color .15s;}
  input[type=file]:focus,input[type=text]:focus{border-color:var(--accent);}
  textarea{width:100%;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:var(--mono);font-size:.8rem;line-height:1.55;resize:vertical;outline:none;transition:border-color .15s;}
  textarea:focus{border-color:var(--accent);}
  .btn{margin-top:18px;padding:10px 22px;background:var(--accent);color:#fff;border:none;border-radius:7px;font-family:var(--sans);font-weight:700;font-size:.85rem;cursor:pointer;transition:opacity .15s;}
  .btn:hover{opacity:.85;} .btn.secondary{background:transparent;border:1px solid var(--border);color:var(--text);}
  .stat-grid{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px;}
  .stat-card{flex:1;min-width:120px;padding:14px 16px;background:var(--bg);border:1px solid var(--border);border-radius:8px;}
  .stat-card .val{font-size:1.6rem;font-weight:800;line-height:1;margin-bottom:4px;color:var(--text);}
  .stat-card .val.ok{color:var(--success);} .stat-card .val.warn{color:#f0a030;} .stat-card .val.err{color:var(--danger);}
  .stat-card .lbl{font-size:.75rem;color:var(--muted);}
  .preview-wrap{overflow-x:auto;margin-top:16px;border-radius:8px;border:1px solid var(--border);}
  .preview-wrap table{border-collapse:collapse;width:100%;font-size:.78rem;font-family:var(--mono);}
  .preview-wrap th{background:var(--bg);color:var(--accent);padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap;position:sticky;top:0;}
  .preview-wrap td{padding:6px 12px;border-bottom:1px solid var(--border);max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text);}
  .preview-wrap tr:last-child td{border-bottom:none;} .preview-wrap tr:hover td{background:rgba(91,140,255,.06);}
  .preview-wrap td.err-cell{color:var(--danger);}
  .fill-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;}
  .fill-name{width:90px;font-family:var(--mono);font-size:.78rem;color:var(--muted);text-align:right;}
  .fill-bar-wrap{flex:1;background:var(--border);border-radius:4px;height:8px;overflow:hidden;}
  .fill-bar{height:100%;border-radius:4px;background:var(--accent);transition:width .3s;}
  .fill-pct{width:36px;font-size:.75rem;color:var(--muted);text-align:right;}
  .err-list{list-style:none;margin-top:10px;}
  .err-list li{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);font-size:.8rem;}
  .err-list li:last-child{border-bottom:none;} .err-list .code{font-family:var(--mono);color:var(--danger);} .err-list .cnt{color:var(--muted);}
  .section-title{font-size:.78rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin:18px 0 10px;}
  .two-col{display:grid;grid-template-columns:1fr 1fr;gap:20px;}
  .three-col{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;}
  @media(max-width:1000px){.three-col{grid-template-columns:1fr 1fr;}}
  @media(max-width:700px){.two-col,.three-col{grid-template-columns:1fr;}}
  .dbg-toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center;}
  .dbg-toolbar .lbl{font-size:.78rem;color:var(--muted);margin-right:4px;}
  .dbg-filter{padding:4px 12px;border-radius:20px;font-size:.75rem;font-weight:600;border:1px solid var(--border);background:transparent;color:var(--muted);cursor:pointer;transition:all .15s;font-family:var(--sans);}
  .dbg-filter.active,.dbg-filter:hover{background:var(--accent);color:#fff;border-color:var(--accent);}
  .dbg-search{margin-left:auto;padding:5px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:var(--mono);font-size:.78rem;outline:none;width:200px;}
  .dbg-search:focus{border-color:var(--accent);}
  .dbg-summary{font-size:.78rem;color:var(--muted);margin-bottom:12px;}
  .dbg-record{border:1px solid var(--border);border-radius:8px;margin-bottom:8px;overflow:hidden;}
  .dbg-record-hdr{display:flex;align-items:center;gap:10px;padding:9px 14px;background:var(--bg);cursor:pointer;user-select:none;transition:background .12s;}
  .dbg-record-hdr:hover{background:#1a1f30;}
  .dbg-record-hdr .rec-num{font-family:var(--mono);font-size:.8rem;color:var(--accent);font-weight:700;}
  .dbg-record-hdr .rec-tokens{font-size:.75rem;color:var(--muted);font-family:var(--mono);}
  .dbg-record-hdr .rec-fields{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;}
  .rec-field-badge{font-size:.68rem;padding:1px 7px;border-radius:10px;font-family:var(--mono);background:rgba(91,140,255,.15);color:var(--accent);border:1px solid rgba(91,140,255,.2);}
  .dbg-toggle{font-size:.7rem;color:var(--muted);transition:transform .2s;display:inline-block;}
  .dbg-record.open .dbg-toggle{transform:rotate(90deg);}
  .dbg-record-body{display:none;padding:10px 0 6px;border-top:1px solid var(--border);}
  .dbg-record.open .dbg-record-body{display:block;}
  .dbg-line{display:flex;align-items:baseline;gap:8px;padding:2px 14px;font-size:.76rem;font-family:var(--mono);transition:background .1s;}
  .dbg-line:hover{background:rgba(255,255,255,.03);} .dbg-line.hidden{display:none;}
  .dbg-line .ln{color:var(--border);width:28px;text-align:right;flex-shrink:0;font-size:.68rem;}
  .dbg-line .txt{color:var(--text);white-space:pre-wrap;word-break:break-all;}
  .dbg-line.t-trigger .txt{color:var(--accent);font-weight:600;} .dbg-line.t-save .txt{color:var(--accent2);}
  .dbg-line.t-heur .txt{color:#f0a030;} .dbg-line.t-stop .txt{color:var(--danger);}
  .dbg-line.t-lost .txt{color:#555;} .dbg-line.t-err .txt{color:var(--danger);font-weight:600;}
  .dbg-line.t-segment .txt{color:#a78bfa;font-weight:600;}
  .dbg-line .tag{font-size:.62rem;padding:0 5px;border-radius:3px;flex-shrink:0;font-weight:700;letter-spacing:.04em;}
  .tag-trigger{background:rgba(91,140,255,.2);color:var(--accent);} .tag-save{background:rgba(56,217,169,.15);color:var(--accent2);}
  .tag-heur{background:rgba(240,160,48,.15);color:#f0a030;} .tag-stop{background:rgba(255,107,107,.15);color:var(--danger);}
  .tag-lost{background:rgba(255,255,255,.06);color:var(--muted);} .tag-segment{background:rgba(167,139,250,.15);color:#a78bfa;}
  .dbg-dl{margin-top:12px;padding:0 14px;}
  .dbg-dl a{color:var(--muted);font-size:.75rem;font-family:var(--mono);text-decoration:none;border-bottom:1px dashed var(--border);}
  .json-status{margin-top:8px;font-size:.78rem;font-family:var(--mono);min-height:20px;}
  .json-status.ok{color:var(--success);} .json-status.err{color:var(--danger);}
  .json-info{display:flex;gap:10px;margin-top:6px;flex-wrap:wrap;}
  .json-badge{font-size:.72rem;padding:2px 8px;border-radius:10px;font-family:var(--mono);background:rgba(91,140,255,.12);color:var(--accent);border:1px solid rgba(91,140,255,.2);}
  textarea.json-invalid{border-color:var(--danger)!important;} textarea.json-valid{border-color:var(--success)!important;}
  .progress-wrap{display:none;margin-top:14px;} .progress-wrap.active{display:block;}
  .progress-bar-bg{height:6px;background:var(--border);border-radius:3px;overflow:hidden;margin-bottom:6px;}
  .progress-bar{height:100%;width:0%;background:var(--accent);border-radius:3px;transition:width .3s;}
  .progress-msg{font-size:.78rem;color:var(--muted);font-family:var(--mono);}
  .test-result{padding:8px 12px;border-radius:6px;font-size:.8rem;font-family:var(--mono);margin-bottom:6px;}
  .test-result.pass{background:rgba(56,217,169,.1);border:1px solid rgba(56,217,169,.2);color:var(--success);}
  .test-result.fail{background:rgba(255,107,107,.1);border:1px solid rgba(255,107,107,.2);color:var(--danger);}
  .test-result.info{background:var(--bg);border:1px solid var(--border);color:var(--muted);}
  .test-summary{font-size:.85rem;font-weight:700;margin-bottom:12px;}
  .susp-list{list-style:none;margin-top:10px;max-height:260px;overflow-y:auto;}
  .susp-list li{display:flex;justify-content:space-between;gap:10px;padding:4px 0;border-bottom:1px solid var(--border);font-size:.78rem;font-family:var(--mono);}
  .susp-list li:last-child{border-bottom:none;} .susp-list .tok{color:var(--text);word-break:break-all;} .susp-list .cnt{color:var(--muted);flex-shrink:0;margin-left:10px;}
  .susp-note{font-size:.76rem;color:var(--muted);margin-top:8px;}
  .dist-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-top:10px;}
  .dist-card{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 12px;}
  .dist-hdr{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;gap:8px;}
  .dist-hdr .name{font-family:var(--mono);font-size:.82rem;color:var(--accent);font-weight:700;} .dist-hdr .meta{font-size:.7rem;color:var(--muted);white-space:nowrap;}
  .dist-list{list-style:none;}
  .dist-list li{display:flex;justify-content:space-between;gap:8px;padding:2px 0;font-size:.76rem;font-family:var(--mono);}
  .dist-list .val{color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;} .dist-list .cnt{color:var(--muted);flex-shrink:0;}
  .dist-empty{font-size:.76rem;color:var(--muted);} .dist-more{font-size:.7rem;color:var(--muted);margin-top:4px;}
</style>
</head>
<body>
<header>
  <h1>Trigger<span>Parse</span></h1>
  <span class="ver">Engine v3.1</span>
  <div style="margin-left:auto;display:flex;gap:14px;align-items:center">
    <button onclick="resetResults()" class="btn secondary" style="padding:5px 12px;font-size:.78rem">&#10006; Сбросить</button>
    <a href="/docs" target="_blank" style="color:var(--accent);font-size:.82rem;text-decoration:none;opacity:.8">📖 Документация</a>
  </div>
</header>
<div class="status-bar">${status_html}</div>
<div class="tabs">
  <button class="tab-btn" data-tab="main">Основное</button>
  <button class="tab-btn" data-tab="results">Результаты</button>
  <button class="tab-btn" data-tab="config">Конфигурация</button>
  <button class="tab-btn" data-tab="debug">Отладка</button>
  <button class="tab-btn" data-tab="tests">Тесты</button>
</div>
<div id="main" class="tab-panel">
  <h3>Загрузка файлов и анализ</h3>
  <form enctype="multipart/form-data" action="/analyze" method="post">
    <label>TXT-файлы (можно несколько)</label>
    <input type="file" name="files" multiple accept=".txt" required>
    <label>Имя выходного CSV</label>
    <input type="text" name="csvname" placeholder="result.csv">
    <button class="btn" type="submit">Анализировать</button>
  </form>
</div>
<div id="results" class="tab-panel">${results_html}</div>
<div id="config" class="tab-panel">
  <h3>Загрузка конфигурации</h3>
  <form enctype="multipart/form-data" action="/upload_config" method="post" id="cfg-form">
    <label>JSON-файл конфигурации</label>
    <input type="file" name="config_file" accept=".json" id="cfg-file">
    <label>Или вставьте JSON вручную</label>
    <textarea name="config_json" rows="28" id="cfg-ta" spellcheck="false">${config_json}</textarea>
    ${config_download_link}
    <div class="json-status" id="json-status"></div>
    <div class="json-info" id="json-info"></div>
    <button class="btn" type="submit" id="cfg-submit" style="margin-top:14px">Применить конфигурацию</button>
  </form>
</div>
<div id="debug" class="tab-panel">
  <h3>Отладка парсинга</h3>
  <form enctype="multipart/form-data" action="/debug" method="post" id="dbg-form">
    <label>TXT-файлы для пошагового анализа (можно несколько)</label>
    <input type="file" name="files" accept=".txt" multiple required>
    <button class="btn" type="submit">Запустить отладку</button>
  </form>
  <div class="progress-wrap" id="dbg-progress">
    <div class="progress-bar-bg"><div class="progress-bar" id="dbg-bar"></div></div>
    <div class="progress-msg" id="dbg-msg">Инициализация...</div>
  </div>
  ${debug_html}
</div>
<div id="tests" class="tab-panel">
  <h3>Тест-раннер конфига</h3>
  <p style="font-size:.82rem;color:var(--muted);margin-bottom:14px">
    Добавьте секцию <code style="font-family:var(--mono);color:var(--accent)">"tests"</code> в конфиг.
    Каждый кейс: <code style="font-family:var(--mono);color:var(--accent)">{description, input, expect:{поле:значение,...}}</code>
  </p>
  <button class="btn" onclick="runTests()">Запустить тесты</button>
  <div id="test-results" style="margin-top:16px"></div>
</div>
<script>
const panels=document.querySelectorAll('.tab-panel');
const buttons=document.querySelectorAll('.tab-btn');
function activate(name){panels.forEach(p=>p.classList.toggle('active',p.id===name));buttons.forEach(b=>b.classList.toggle('active',b.dataset.tab===name));}
buttons.forEach(b=>b.addEventListener('click',()=>activate(b.dataset.tab)));
activate('${active_tab}');
(function(){
  var ta=document.getElementById("cfg-ta"),st=document.getElementById("json-status"),
      inf=document.getElementById("json-info"),btn=document.getElementById("cfg-submit");
  if(!ta)return;
  var tid=null;
  function validate(){
    var val=ta.value.trim();if(!val){st.textContent="";inf.innerHTML="";return;}
    fetch("/validate_config",{method:"POST",headers:{"Content-Type":"application/json"},body:val})
    .then(function(r){return r.json();}).then(function(d){
      if(d.valid){st.className="json-status ok";st.textContent="JSON валиден";
        ta.className=ta.className.replace(/json-invalid|json-valid/g,"").trim()+" json-valid";
        if(btn)btn.disabled=false;
        inf.innerHTML='<span class="json-badge">'+d.triggers+' триггеров</span>'+'<span class="json-badge">'+d.columns+' колонок</span>'+(d.has_tests?'<span class="json-badge">есть тесты</span>':'');
      }else{st.className="json-status err";st.textContent=d.errors?d.errors[0]:"Ошибка";
        ta.className=ta.className.replace(/json-invalid|json-valid/g,"").trim()+" json-invalid";
        if(btn)btn.disabled=true;inf.innerHTML="";}
    }).catch(function(){});
  }
  ta.addEventListener("input",function(){clearTimeout(tid);tid=setTimeout(validate,400);});
  var fi=document.getElementById("cfg-file");
  if(fi)fi.addEventListener("change",function(){
    var f=this.files[0];if(!f)return;
    var r=new FileReader();r.onload=function(e){ta.value=e.target.result;validate();};r.readAsText(f,"utf-8");
  });
  validate();
})();
(function(){
  var form=document.getElementById("dbg-form");if(!form)return;
  form.addEventListener("submit",function(){
    var wrap=document.getElementById("dbg-progress"),bar=document.getElementById("dbg-bar"),msg=document.getElementById("dbg-msg");
    if(!wrap)return;
    wrap.classList.add("active");bar.style.width="0%";msg.textContent="Отправка...";
    var es=new EventSource("/progress");
    es.onmessage=function(e){var d=JSON.parse(e.data);bar.style.width=d.pct+"%";msg.textContent=d.msg||"";if(d.done){es.close();wrap.classList.remove("active");}};
    es.onerror=function(){es.close();wrap.classList.remove("active");};
  });
})();
function resetResults(){
  if(!confirm('Сбросить результаты анализа и debug-лог? Конфиг останется.'))return;
  fetch('/reset',{method:'POST'}).then(function(r){return r.json();}).then(function(){activate('main');window.location.reload();}).catch(function(e){alert('Ошибка сброса: '+e);});
}
function runTests(){
  var out=document.getElementById("test-results");
  out.innerHTML='<p style="color:var(--muted);font-size:.82rem">Запуск...</p>';
  fetch("/run_tests").then(function(r){return r.json();}).then(function(data){
    if(data.error){out.innerHTML='<div class="test-result info">'+data.error+'</div>';return;}
    var cls=data.failed?"fail":"pass";
    var html='<div class="test-summary '+cls+'">'+data.passed+' / '+data.total+' пройдено'+(data.failed?' ('+data.failed+' провалено)':'')+'</div>';
    data.results.forEach(function(r){
      html+='<div class="test-result '+r.status+'"><b>'+r.description+'</b><br>';
      r.details.forEach(function(d){
        var ok=d.ok?"&#10003;":"&#10007;";
        html+='<span style="margin-left:10px">'+ok+' '+d.field+': ожидалось <code>'+d.expected+'</code>'+(d.ok?'':', получено <code>'+d.got+'</code>')+'</span><br>';
      });
      html+='</div>';
    });
    out.innerHTML=html;
  }).catch(function(e){out.innerHTML='<div class="test-result fail">Ошибка: '+e+'</div>';});
}
</script>
</body>
</html>""")


# ==========================================================
# РЕНДЕР DEBUG-ЛОГА И СТАТИСТИКИ
# ==========================================================

def _classify_log_line(line):
    l = line.strip()
    if "found trigger:" in l or "exact match" in l or "regex match" in l or "trigger '" in l.lower():
        return 't-trigger', '<span class="tag tag-trigger">TRIGGER</span>'
    if l.startswith('save_field'):
        return 't-save', '<span class="tag tag-save">SAVE</span>'
    if 'heuristic matched' in l:
        return 't-heur', '<span class="tag tag-heur">HEUR</span>'
    if 'stop_word' in l:
        return 't-stop', '<span class="tag tag-stop">STOP</span>'
    if 'token lost' in l or 'no active field' in l:
        return 't-lost', '<span class="tag tag-lost">LOST</span>'
    if 'валидация не пройдена' in l or 'ВНИМАНИЕ' in l:
        return 't-err', ''
    if l.startswith('=== SEGMENT') or l.startswith('--- Record') or l.startswith('=== PARS'):
        return 't-segment', '<span class="tag tag-segment">REC</span>'
    return '', ''


def _render_debug_html(debug_log, log_token):
    if not debug_log:
        return '<p style="color:var(--muted);font-size:.85rem">Log empty.</p>'

    groups    = []
    cur_hdr   = "Init"
    cur_lines = []
    for line in debug_log:
        if line.startswith('--- Record ') and '/' in line:
            if cur_lines:
                groups.append((cur_hdr, cur_lines))
            cur_hdr   = line.strip('-').strip()
            cur_lines = []
        else:
            cur_lines.append(line)
    if cur_lines:
        groups.append((cur_hdr, cur_lines))

    total       = len(debug_log)
    type_counts = {}
    for line in debug_log:
        css, _ = _classify_log_line(line)
        if css:
            type_counts[css] = type_counts.get(css, 0) + 1

    filter_defs = [
        ('', 'Все'), ('t-trigger', 'Триггер'), ('t-save', 'Сохранение'),
        ('t-heur', 'Эвристика'), ('t-stop', 'Стоп-слово'), ('t-lost', 'Потеря'),
        ('t-err', 'Ошибка'), ('t-segment', 'Запись'),
    ]
    filter_btns = ''
    for cls, label in filter_defs:
        cnt   = type_counts.get(cls, 0) if cls else total
        extra = ' active' if not cls else ''
        cnt_s = '' if not cls else f' ({cnt})'
        filter_btns += (
            f'<button class="dbg-filter{extra}" data-filter="{cls}">'
            f'{_escape_html(label)}{cnt_s}</button>'
        )

    records_html = ''
    global_ln    = 0
    for gi, (header, lines) in enumerate(groups):
        field_badges = ''
        for ln in lines:
            if ln.strip().startswith('save_field'):
                m = re.search(r"save_field '([^']+)'.*norm='([^']*)'", ln)
                if m:
                    fval = m.group(2)[:20]
                    if fval:
                        field_badges += (
                            f'<span class="rec-field-badge">'
                            f'{_escape_html(m.group(1))}: {_escape_html(fval)}'
                            f'{"..." if len(m.group(2)) > 20 else ""}</span>'
                        )
        tok_prev = ''
        for ln in lines[:5]:
            m = re.search(r"Token \d+: '([^']+)'", ln)
            if m:
                tok_prev += _escape_html(m.group(1)) + ' '

        lines_html = ''
        for line in lines:
            global_ln += 1
            css, tag = _classify_log_line(line)
            lines_html += (
                f'<div class="dbg-line {css}" data-type="{css}">'
                f'<span class="ln">{global_ln}</span>{tag}'
                f'<span class="txt">{_escape_html(line)}</span></div>'
            )

        open_cls = ' open' if gi == 0 else ''
        records_html += (
            f'<div class="dbg-record{open_cls}" id="dbg-rec-{gi}">'
            f'<div class="dbg-record-hdr" onclick="toggleRec({gi})">'
            f'<span class="dbg-toggle">&#9654;</span>'
            f'<span class="rec-num">{_escape_html(header)}</span>'
            f'<span class="rec-tokens">{tok_prev.strip()}</span>'
            f'<span class="rec-fields">{field_badges}</span></div>'
            f'<div class="dbg-record-body">{lines_html}</div></div>'
        )

    # FIX: ссылка использует реальный токен (проверяется на сервере)
    dl = (
        f'<div class="dbg-dl"><a href="/debug_log/{log_token}" download>'
        f'Скачать raw-лог</a></div>'
    ) if log_token else ''

    js = (
        '<script>'
        'function toggleRec(i){document.getElementById("dbg-rec-"+i).classList.toggle("open");}'
        '(function(){var af="",sv="";'
        'function apply(){document.querySelectorAll(".dbg-line").forEach(function(el){'
        'var tm=!af||el.dataset.type===af;'
        'var sm=!sv||el.querySelector(".txt").textContent.toLowerCase().includes(sv);'
        'el.classList.toggle("hidden",!(tm&&sm));});}'
        'document.querySelectorAll(".dbg-filter").forEach(function(b){'
        'b.addEventListener("click",function(){'
        'document.querySelectorAll(".dbg-filter").forEach(function(x){x.classList.remove("active");});'
        'this.classList.add("active");af=this.dataset.filter;apply();});});'
        'var si=document.getElementById("dbg-search");'
        'if(si)si.addEventListener("input",function(){sv=this.value.toLowerCase();apply();});'
        '})();</script>'
    )

    return (
        f'<div class="dbg-toolbar"><span class="lbl">Фильтр:</span>'
        f'{filter_btns}'
        f'<input id="dbg-search" class="dbg-search" placeholder="Поиск по логу..." type="text">'
        f'</div>'
        f'<div class="dbg-summary">{len(groups)} записей &middot; {total} строк лога</div>'
        f'{records_html}{dl}{js}'
    )


def _render_stats_html(stats: dict, csv_columns: list, preview_rows: list,
                       csv_name: str, csv_token: str,
                       suspicious: Optional[Counter] = None,
                       log_suspicious: bool = False) -> str:
    total       = stats['total']
    clean       = stats['clean']
    with_errors = stats['with_errors']
    err_rate    = stats['error_rate']
    rate_cls    = 'ok' if err_rate == 0 else ('warn' if err_rate < 20 else 'err')
    duplicates  = stats.get('duplicates', 0)
    dup_cls     = 'err' if duplicates else 'ok'

    cards = (
        f'<div class="stat-grid">'
        f'<div class="stat-card"><div class="val ok">{total}</div><div class="lbl">Всего записей</div></div>'
        f'<div class="stat-card"><div class="val ok">{clean}</div><div class="lbl">Без ошибок</div></div>'
        f'<div class="stat-card"><div class="val {rate_cls}">{with_errors}</div><div class="lbl">С ошибками</div></div>'
        f'<div class="stat-card"><div class="val {rate_cls}">{err_rate}%</div><div class="lbl">Доля ошибок</div></div>'
        f'<div class="stat-card"><div class="val {dup_cls}">{duplicates}</div><div class="lbl">Дублей</div></div>'
        f'</div>'
    )

    fill_html = '<div class="section-title">Заполненность полей</div>'
    for col in csv_columns:
        filled = stats['field_fill'].get(col, 0)
        pct    = round(filled / total * 100) if total else 0
        fill_html += (
            f'<div class="fill-row">'
            f'<span class="fill-name">{_escape_html(col)}</span>'
            f'<div class="fill-bar-wrap"><div class="fill-bar" style="width:{pct}%"></div></div>'
            f'<span class="fill-pct">{pct}%</span></div>'
        )

    if stats['top_errors']:
        err_html = '<div class="section-title">Топ ошибок</div><ul class="err-list">'
        for code, cnt in stats['top_errors']:
            err_html += f'<li><span class="code">{_escape_html(code)}</span><span class="cnt">{cnt}</span></li>'
        err_html += '</ul>'
    else:
        err_html = '<div class="section-title">Ошибок нет</div>'

    susp_html = ''
    if log_suspicious:
        if suspicious:
            total_unique = len(suspicious)
            total_occur  = sum(suspicious.values())
            shown        = suspicious.most_common(MAX_SUSPICIOUS_SHOWN)
            susp_html    = (
                f'<div class="section-title">Потерянные токены '
                f'({total_unique} уникальных, {total_occur} вхождений)</div>'
                f'<ul class="susp-list">'
            )
            for tok, cnt in shown:
                susp_html += (
                    f'<li><span class="tok">{_escape_html(tok)}</span>'
                    f'<span class="cnt">&times;{cnt}</span></li>'
                )
            susp_html += '</ul>'
            if total_unique > MAX_SUSPICIOUS_SHOWN:
                susp_html += (
                    f'<div class="susp-note">показаны топ-{MAX_SUSPICIOUS_SHOWN} '
                    f'из {total_unique} уникальных токенов</div>'
                )
        else:
            susp_html = (
                '<div class="section-title">Потерянные токены</div>'
                '<p style="color:var(--muted);font-size:.82rem">Все токены распределены по полям.</p>'
            )

    dist_cards = ''
    for col in csv_columns:
        d = stats.get('value_distribution', {}).get(col)
        if not d or d['filled'] == 0:
            continue
        meta = f"{d['unique']} уник. / {d['filled']} запис."
        if d['repeated']:
            items = ''.join(
                f'<li><span class="val" title="{_escape_html(v)}">{_escape_html(v)}</span>'
                f'<span class="cnt">&times;{c}</span></li>'
                for v, c in d['repeated']
            )
            more = ''
            if d['repeated_total'] > len(d['repeated']):
                more = (f'<div class="dist-more">ещё {d["repeated_total"] - len(d["repeated"])} '
                        f'повторяющихся значений</div>')
            body = f'<ul class="dist-list">{items}</ul>{more}'
        else:
            body = '<div class="dist-empty">все значения уникальны</div>'
        dist_cards += (
            f'<div class="dist-card">'
            f'<div class="dist-hdr"><span class="name">{_escape_html(col)}</span>'
            f'<span class="meta">{meta}</span></div>{body}</div>'
        )
    dist_html = (
        '<div class="section-title">Распределение значений по полям</div>'
        f'<div class="dist-grid">{dist_cards}</div>'
    ) if dist_cards else ''

    base = csv_name[:-4] if csv_name.endswith('.csv') else csv_name
    dl_btn = (
        f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px">'
        f'<a href="/download/{csv_token}?fmt=csv" class="btn" style="text-decoration:none">⬇ CSV</a>'
        f'<a href="/download/{csv_token}?fmt=json" class="btn secondary" style="text-decoration:none">⬇ JSON</a>'
        f'<a href="/download/{csv_token}?fmt=xlsx" class="btn secondary" style="text-decoration:none">⬇ Excel</a>'
        f'</div>'
    )

    if preview_rows:
        cols_hdr  = csv_columns + ['err']
        th_cells  = "".join(f"<th>{_escape_html(c)}</th>" for c in cols_hdr)
        rows_html = ""
        for row in preview_rows:
            tds = ""
            for c in cols_hdr:
                val = _escape_html(str(row.get(c) or ''))
                cls = ' class="err-cell"' if c == 'err' and val else ""
                tds += f'<td{cls} title="{val}">{val}</td>'
            rows_html += f"<tr>{tds}</tr>"
        table = (
            f'<div class="section-title">Предпросмотр (первые {len(preview_rows)} строк)</div>'
            f'<div class="preview-wrap"><table><thead><tr>{th_cells}</tr></thead>'
            f'<tbody>{rows_html}</tbody></table></div>'
        )
    else:
        table = ""

    middle_cols = f'<div>{fill_html}</div><div>{err_html}</div>'
    if log_suspicious:
        middle_cols += f'<div>{susp_html}</div>'
        grid_cls = "three-col"
    else:
        grid_cls = "two-col"

    return f'{dl_btn}{cards}<div class="{grid_cls}">{middle_cols}</div>{dist_html}{table}'


def build_html(
    config_loaded: bool,
    raw_config: Optional[dict] = None,
    message: str = "",
    active_tab: str = "main",
    results_html: str = "",
    debug_html: str = "",
) -> str:
    if config_loaded:
        status_html = '<span class="ok">&#10003; Конфигурация загружена</span>'
    else:
        status_html = '<span class="fail">&#10007; Конфигурация не загружена</span>'
    if message:
        status_html += f" &nbsp;&middot;&nbsp; {message}"
    config_json = _escape_html(
        json.dumps(raw_config, ensure_ascii=False, indent=2)
    ) if raw_config else ""
    config_download_link = (
        '<a href="/download_config" class="btn secondary" '
        'style="display:inline-block;text-decoration:none;margin-top:8px" '
        'download="config.json">&#11015; Скачать текущий конфиг</a>'
    ) if raw_config else ""
    no_debug   = '<p style="color:var(--muted);font-size:.85rem">Загрузите TXT-файл и нажмите «Запустить отладку».</p>'
    no_results = '<p style="color:var(--muted);font-size:.85rem">Результаты появятся после анализа.</p>'
    return _HTML_TEMPLATE.safe_substitute(
        status_html          = status_html,
        config_json          = config_json,
        config_download_link = config_download_link,
        debug_html           = debug_html or no_debug,
        active_tab           = active_tab,
        results_html         = results_html or no_results,
    )


# ==========================================================
# HTTP-ОБРАБОТЧИК
# ==========================================================

class RequestHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        log.debug("HTTP %s", fmt % args)

    def _check_auth(self) -> bool:
        if not AUTH_ENABLED:
            return True
        header = self.headers.get('Authorization', '')
        if not header.startswith('Basic '):
            return False
        try:
            decoded      = base64.b64decode(header[6:]).decode('utf-8')
            user, _, pwd = decoded.partition(':')
        except Exception:
            return False
        return (hmac.compare_digest(user, AUTH_USER) and
                hmac.compare_digest(pwd,  AUTH_PASS))

    def _send_auth_required(self):
        body = 'Требуется авторизация (логин/пароль)'.encode('utf-8')
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="TriggerParse Engine"')
        self.send_header('Content-Type',   'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── GET ─────────────────────────────────────────────────────────

    def do_GET(self):
        # /health открыт без авторизации
        if self.path == '/health':
            raw_cfg2, compiled_cfg2 = _state.get_config()
            uptime_sec = round(time.monotonic() - _server_start_time)
            self._send_json({
                'status':          'ok',
                'version':         '3.1',
                'uptime_sec':      uptime_sec,
                'uptime_human':    _fmt_uptime(uptime_sec),
                'config_loaded':   compiled_cfg2 is not None,
                'config_name':     (raw_cfg2 or {}).get('parser_name', ''),
                'config_version':  (raw_cfg2 or {}).get('version', ''),
                'auth_enabled':    AUTH_ENABLED,
                'debug_log_limit': MAX_DEBUG_LOG_LINES,
            })
            return

        if not self._check_auth():
            self._send_auth_required()
            return
        raw_cfg, compiled_cfg = _state.get_config()

        if self.path == '/':
            self._send_html(build_html(compiled_cfg is not None, raw_cfg))

        elif self.path.startswith('/debug_log/'):
            # FIX: проверяем токен — принимаем только правильный
            req_token                        = self.path[len('/debug_log/'):]
            dbg_log, dbg_name, dbg_token     = _state.get_debug()
            if dbg_log is None or req_token != dbg_token:
                self.send_error(404, "Лог отладки недоступен или токен неверен")
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Disposition',
                             f'attachment; filename="{dbg_name or "debug_log.txt"}"')
            self.end_headers()
            self.wfile.write("\n".join(dbg_log).encode('utf-8'))

        elif self.path.startswith('/download/'):
            parsed    = urlparse(self.path)
            req_token = parsed.path[len('/download/'):]
            fmt       = parse_qs(parsed.query).get('fmt', ['csv'])[0]
            csv_bytes, json_bytes, xlsx_bytes, csv_name, _, _, token = _state.get_result()
            if csv_bytes is None or req_token != token:
                self.send_error(404, "Файл недоступен — выполните анализ заново")
                return
            base_name = csv_name[:-4] if csv_name.endswith('.csv') else csv_name
            if fmt == 'json':
                data, mime, fname_out = json_bytes or b'[]', 'application/json; charset=utf-8', base_name + '.json'
            elif fmt == 'xlsx':
                if not xlsx_bytes:
                    self.send_error(501, "openpyxl не установлен. Выполните: pip install openpyxl")
                    return
                data      = xlsx_bytes
                mime      = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                fname_out = base_name + '.xlsx'
            else:
                data, mime, fname_out = csv_bytes, 'text/csv; charset=utf-8', csv_name
            self.send_response(200)
            self.send_header('Content-Type',        mime)
            self.send_header('Content-Disposition', f'attachment; filename="{fname_out}"')
            self.send_header('Content-Length',      str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        elif self.path == '/docs':
            self._send_html(_build_docs_html())

        elif self.path == '/download_config':
            raw_cfg2, _ = _state.get_config()
            if raw_cfg2 is None:
                self.send_error(404, "Конфигурация не загружена")
                return
            data = json.dumps(raw_cfg2, ensure_ascii=False, indent=2).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type',        'application/json; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="config.json"')
            self.send_header('Content-Length',      str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        elif self.path == '/progress':
            self.send_response(200)
            self.send_header('Content-Type',  'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection',    'keep-alive')
            self.end_headers()
            _, _cfg       = _state.get_config()
            _sse_timeout  = (_cfg.get('process_timeout', PROCESS_TIMEOUT_SEC) if _cfg else PROCESS_TIMEOUT_SEC) + 15
            _sse_deadline = time.monotonic() + _sse_timeout
            while time.monotonic() < _sse_deadline:
                p = _state.get_progress()
                try:
                    self.wfile.write(f'data: {json.dumps(p)}\n\n'.encode('utf-8'))
                    self.wfile.flush()
                except (OSError, BrokenPipeError):
                    break
                if p.get('done'):
                    break
                time.sleep(0.25)

        elif self.path == '/run_tests':
            _, compiled_cfg = _state.get_config()
            if compiled_cfg is None:
                self._send_json({'error': 'Конфигурация не загружена'}, 400)
                return
            self._send_json(run_tests(compiled_cfg))

        else:
            self.send_error(404)

    # ── POST ────────────────────────────────────────────────────────

    def do_POST(self):
        if not self._check_auth():
            self._send_auth_required()
            return
        raw_cfg, compiled_cfg = _state.get_config()

        if self.path in ('/analyze', '/debug'):
            if compiled_cfg is None:
                self.send_error(400, "Конфигурация не загружена")
                return
            self._handle_analyze(compiled_cfg, raw_cfg, debug_mode=(self.path == '/debug'))

        elif self.path == '/upload_config':
            self._handle_upload_config()

        elif self.path == '/reset':
            _state.set_result(b'', b'', None, '', {}, [], '')
            _state.set_debug(None, None)
            _state.set_progress(0, '', done=True)
            log.info('Результаты сброшены пользователем')
            self._send_json({'ok': True})

        elif self.path == '/validate_config':
            body_bytes = self._read_body()
            if body_bytes is None:
                return
            try:
                raw  = json.loads(body_bytes.decode('utf-8'))
                errs = validate_config(raw)
                self._send_json({
                    'valid':     len(errs) == 0,
                    'errors':    errs,
                    'triggers':  len(raw.get('triggers', {})),
                    'columns':   len(raw.get('csv_columns', [])),
                    'has_tests': bool(raw.get('tests')),
                })
            except json.JSONDecodeError as e:
                self._send_json({'valid': False, 'errors': [f'JSON: {e}'],
                                 'triggers': 0, 'columns': 0, 'has_tests': False})
        else:
            self.send_error(404)

    # ── Вспомогательные ─────────────────────────────────────────────

    def _send_html(self, body: str):
        encoded = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type',   'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, data: dict, status: int = 200):
        encoded = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',   'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_body(self) -> Optional[bytes]:
        length = int(self.headers.get('Content-Length', 0))
        if length > MAX_UPLOAD_BYTES:
            self.send_error(413, f"Файл слишком большой (лимит {MAX_UPLOAD_BYTES // 1024 // 1024} МБ)")
            return None
        return self.rfile.read(length)

    def _parse_multipart(self) -> tuple[list[tuple[str, bytes]], str]:
        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            self.send_error(400, "Ожидается multipart/form-data")
            return [], ""
        body = self._read_body()
        if body is None:
            return [], ""
        msg      = BytesParser(policy=email_default).parsebytes(
            f'Content-Type: {content_type}\r\n\r\n'.encode() + body
        )
        files:    list[tuple[str, bytes]] = []
        csv_name: str                     = ""
        for part in msg.walk():
            if part.get_content_disposition() != 'form-data':
                continue
            name = part.get_param('name', header='content-disposition')
            if name == 'files':
                payload = part.get_payload(decode=True)
                fname   = part.get_filename()
                if fname and payload:
                    files.append((fname, payload))
            elif name == 'csvname':
                raw = part.get_payload(decode=True)
                if raw:
                    csv_name = raw.decode('utf-8').strip()
        return files, csv_name

    def _handle_analyze(self, compiled_cfg: dict, raw_cfg: Optional[dict], debug_mode: bool):
        files, csv_name = self._parse_multipart()
        if not files:
            self.send_error(400, "Файлы не выбраны")
            return

        debug_enabled = debug_mode or compiled_cfg.get('debug_logging', False)
        debug_log     = LimitedLog() if debug_enabled else None
        first_fname   = files[0][0]
        log.info(f"Анализ: {len(files)} файл(ов), debug={debug_mode}")

        # FIX: сбрасываем прогресс до нуля — клиент не увидит done=True от прошлого запроса
        _state.set_progress(0, 'Запуск...', done=False)

        # FIX: cancel_event — воркер проверяет флаг между файлами и останавливается
        # при таймауте, не продолжая писать в _state после того как обработчик вернул 503
        cancel_event = threading.Event()

        def _parse_all():
            _records:    list    = []
            _enc_notes:  list    = []   # имена файлов с нестандартной кодировкой
            _suspicious: Counter = Counter()
            for _fname, _content in files:
                if cancel_event.is_set():
                    log.warning(f"Парсинг прерван по таймауту на файле '{_fname}'")
                    break
                _text, _enc = decode_bytes(_content)
                if _enc not in ('utf-8', 'utf-8-sig'):
                    _enc_notes.append(_fname)   # сырое имя — экранируем при вставке в HTML
                    log.warning(f"Файл '{_fname}': нестандартная кодировка {_enc}")
                else:
                    log.debug(f"Файл '{_fname}': кодировка {_enc}")
                if debug_log is not None:
                    debug_log.append(f"Файл '{_fname}': кодировка {_enc}")
                _recs = parse_text(_text, compiled_cfg, _suspicious, debug_log)
                log.info(f"Файл '{_fname}': распознано {len(_recs)} записей")
                _records.extend(_recs)
            _state.set_progress(90, 'Формирование результатов...', done=False)
            return _records, _enc_notes, _suspicious

        timeout_sec = compiled_cfg.get('process_timeout', PROCESS_TIMEOUT_SEC)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_parse_all)
                try:
                    all_records, enc_notes, suspicious = future.result(timeout=timeout_sec)
                except concurrent.futures.TimeoutError:
                    cancel_event.set()
                    log.error(f"Превышен лимит времени обработки ({timeout_sec}с)")
                    _state.set_progress(0, '', done=True)
                    self.send_error(503,
                        f"Превышен лимит времени обработки ({timeout_sec} сек). "
                        f"Уменьшите файл или увеличьте process_timeout в конфиге.")
                    return
        except Exception as exc:
            log.exception(f"Ошибка парсинга: {exc}")
            _state.set_progress(0, '', done=True)
            self.send_error(500, f"Ошибка парсинга: {exc}")
            return

        _state.set_progress(100, 'Готово', done=True)

        # FIX: имена файлов из загрузок экранируем перед вставкой в HTML (XSS)
        enc_warn = ""
        if enc_notes:
            safe_names = ', '.join(_escape_html(n) for n in enc_notes)
            enc_warn   = (
                f" &nbsp;·&nbsp; <span style='color:#f0a030'>⚠ Кодировка: {safe_names}</span>"
            )

        if debug_mode:
            log_token = hashlib.md5(f"{time.time()}{first_fname}".encode()).hexdigest()[:16]
            log_name  = f"debug_{first_fname}.txt"
            _state.set_debug(debug_log, log_name, log_token)
            d_html = _render_debug_html(debug_log, log_token)
            self._send_html(build_html(True, raw_cfg, active_tab="debug", debug_html=d_html))
            return

        if not csv_name:
            csv_name = "result.csv"
        if not csv_name.endswith('.csv'):
            csv_name += '.csv'

        columns = list(compiled_cfg.get('csv_columns', []))
        if 'err' not in columns:
            columns.append('err')

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for rec in all_records:
            safe_rec = {k: _csv_escape(str(v)) if isinstance(v, str) else v
                        for k, v in rec.items()}
            writer.writerow(safe_rec)
        csv_bytes = output.getvalue().encode('utf-8-sig')

        stats      = compute_stats(all_records, compiled_cfg)
        preview    = all_records[:50]
        csv_cols   = compiled_cfg.get('csv_columns', [])
        token      = hashlib.md5(f"{time.time()}{csv_name}".encode()).hexdigest()[:12]
        json_bytes = build_json_bytes(all_records, list(compiled_cfg.get('csv_columns', [])))
        xlsx_bytes = build_xlsx_bytes(all_records, list(compiled_cfg.get('csv_columns', [])))
        if xlsx_bytes is None:
            log.debug("openpyxl не установлен, XLSX недоступен")
        _state.set_result(csv_bytes, json_bytes, xlsx_bytes, csv_name, stats, preview, token)

        res_html = _render_stats_html(
            stats, csv_cols, preview, csv_name, token,
            suspicious=suspicious,
            log_suspicious=bool(compiled_cfg.get('log_suspicious'))
        )
        self._send_html(build_html(True, raw_cfg, active_tab="results",
                                   results_html=res_html, message=enc_warn))

    def _handle_upload_config(self):
        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            self.send_error(400, "Ожидается multipart/form-data")
            return
        body = self._read_body()
        if body is None:
            return

        msg = BytesParser(policy=email_default).parsebytes(
            f'Content-Type: {content_type}\r\n\r\n'.encode() + body
        )

        # FIX: два отдельных прохода — файл всегда приоритетнее textarea,
        # независимо от порядка частей в multipart-теле.
        # Старый код перезаписывал config_data в одном цикле: если textarea
        # шла после config_file в multipart-порядке (а DOM так и отправляет),
        # data затиралась пустым или старым значением textarea.
        file_data:     Optional[str] = None
        textarea_data: Optional[str] = None

        for part in msg.walk():
            if part.get_content_disposition() != 'form-data':
                continue
            name    = part.get_param('name', header='content-disposition')
            payload = part.get_payload(decode=True)
            if not payload or not payload.strip():
                continue
            if name == 'config_file':
                file_data = payload.decode('utf-8')
            elif name == 'config_json':
                textarea_data = payload.decode('utf-8')

        config_data = file_data or textarea_data   # файл всегда приоритетнее

        if not config_data or not config_data.strip():
            self.send_error(400, "Нет данных конфигурации")
            return

        message      = ""
        raw_cfg, compiled_cfg = _state.get_config()
        try:
            raw  = json.loads(config_data)
            errs = validate_config(raw)
            if errs:
                raise ValueError("\n".join(errs))
            compiled     = compile_config(raw)
            _state.set_config(raw, compiled)
            raw_cfg      = raw
            compiled_cfg = compiled
            with open(DEFAULT_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
            log.info(f"Конфигурация загружена: {raw.get('parser_name','?')} v{raw.get('version','?')}")
            message = '<span class="ok">✓ Конфигурация сохранена</span>'
        except Exception as e:
            message = f'<span class="fail">✗ Ошибка: {_escape_html(str(e))}</span>'

        self._send_html(build_html(compiled_cfg is not None, raw_cfg, message, active_tab="config"))

# ==========================================================
# ТОЧКА ВХОДА
# ==========================================================

_server_start_time: float = 0.0


def run_server(port: int = 8000):
    global _server_start_time
    _server_start_time = time.monotonic()
    try_load_default_config()
    if AUTH_ENABLED:
        log.info(f"Базовая аутентификация включена (пользователь: '{AUTH_USER}')")
    else:
        log.info("Аутентификация отключена (задайте TRIGGERPARSE_USER и TRIGGERPARSE_PASS для включения)")
    # FIX: ThreadingHTTPServer вместо HTTPServer — SSE /progress обслуживается
    # в отдельном потоке параллельно с /analyze и /debug
    httpd = ThreadingHTTPServer(('', port), RequestHandler)
    log.info(f"Сервер запущен: http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Сервер остановлен")


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run_server(port)