"""Advisory owner identities, with a bounded asynchronous history sample.

Only the daemon touches history paths or imports pyarrow. A stuck filesystem or
reader occupies that one worker; callers continue to receive memory/cache data.
History is sampled, never an exhaustive user directory or an authority check.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from itertools import islice
import os
import re
import threading
import time

from patroller_webui import __DEFAULT_DATABASE_PATH as DEFAULT_HISTORY_PATH

MAX_CANDIDATES = 500
MAX_PATHS = 8
TTL_SECONDS = 300
MAX_DIRECTORY_ENTRIES = 256
MAX_FILES = 4
MAX_FOOTER_BYTES = 1024 * 1024
MAX_COLUMN_BYTES = 8 * 1024 * 1024
MAX_ROWS = 8192
MAX_GROUPS = 8
MAX_NAME = 200
MAX_LABEL = 512
_COLUMNS = ('owner_email', 'owner_name', 'email', 'name', 'user')
_EMAIL = re.compile(r"[^\s<>@\x00-\x20\x7f]+@[^\s<>@\x00-\x20\x7f.]+(?:\.[^\s<>@\x00-\x20\x7f.]+)+\Z")
_LABEL = re.compile(r'\s*([^<>]*)\s*<([^<>]+)>\s*\Z')
_lock = threading.Lock()
_wake = threading.Event()
_cache = OrderedDict()
_worker = None


@dataclass
class _Entry:
    values: list = field(default_factory=list)
    updated: float = 0
    pending: bool = True
    running: bool = False


def _email(value):
    if not isinstance(value, str) or len(value) > MAX_LABEL:
        return ''
    value = value.strip().casefold()
    return value if len(value) <= 254 and _EMAIL.fullmatch(value) else ''


def _name(value):
    if not isinstance(value, str) or len(value) > MAX_LABEL:
        return ''
    value = value.strip()
    if len(value) > MAX_NAME or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return ''
    return value


def _add(result, email, name=''):
    email = _email(email)
    if email and email not in result and len(result) < MAX_CANDIDATES:
        result[email] = {'email': email, 'name': _name(name)}
    elif email in result and not result[email]['name']:
        result[email]['name'] = _name(name)


def _history_rows(rows, result):
    for row in rows:
        _add(result, row.get('owner_email'), row.get('owner_name'))
        _add(result, row.get('email'), row.get('name'))
        user = row.get('user')
        if isinstance(user, str) and len(user) <= MAX_LABEL:
            match = _LABEL.fullmatch(user)
            if match:
                _add(result, match[2], match[1].strip().strip('"'))
            else:
                _add(result, user)
        if len(result) >= MAX_CANDIDATES:
            break


def _paths(path):
    """Lexical exact path plus newest indices; no recursion or entry stats."""
    directory, filename = os.path.split(path)
    base, _ = os.path.splitext(filename)
    pattern = re.compile(re.escape(base) + r'_([0-9]{1,18})\.parquet\Z')
    indexed = []
    try:
        with os.scandir(directory or '.') as entries:
            for entry in islice(entries, MAX_DIRECTORY_ENTRIES):
                match = pattern.fullmatch(entry.name)
                if match:
                    indexed.append((int(match[1]), os.path.join(directory, entry.name)))
    except OSError:
        pass
    indexed.sort(reverse=True)
    # The exact file counts towards the four-file budget when present.
    return [path] + [value for _, value in indexed[:MAX_FILES]]


def _read_history(path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    result = {}
    rows_left, bytes_left, groups_left = MAX_ROWS, MAX_COLUMN_BYTES, MAX_GROUPS
    files = 0
    for candidate in _paths(path):
        if files >= MAX_FILES or groups_left <= 0 or rows_left <= 0:
            break
        try:
            with open(candidate, 'rb') as source:
                files += 1
                source.seek(0, os.SEEK_END)
                size = source.tell()
                if size < 12:
                    continue
                source.seek(-8, os.SEEK_END)
                tail = source.read(8)
                footer_size = int.from_bytes(tail[:4], 'little')
                if tail[4:] != b'PAR1' or not 0 < footer_size <= min(MAX_FOOTER_BYTES, size - 12):
                    continue
                source.seek(0)
                if source.read(4) != b'PAR1':
                    continue
                source.seek(0)
                parquet = pq.ParquetFile(
                    source, pre_buffer=False, buffer_size=0,
                    thrift_string_size_limit=MAX_FOOTER_BYTES,
                    thrift_container_size_limit=MAX_ROWS,
                )
                metadata = parquet.metadata
                if metadata.num_columns > 256:
                    continue
                schema = parquet.schema_arrow
                columns = [name for name in _COLUMNS if name in schema.names
                           and schema.names.count(name) == 1
                           and (pa.types.is_string(schema.field(name).type)
                                or pa.types.is_large_string(schema.field(name).type))]
                if not columns:
                    continue
                for index in range(min(metadata.num_row_groups, groups_left)):
                    groups_left -= 1
                    group = metadata.row_group(index)
                    if group.num_rows <= 0 or group.num_rows > rows_left:
                        continue
                    chunks = [group.column(i) for i in range(group.num_columns)
                              if group.column(i).path_in_schema in columns]
                    # Bound both compressed input and expanded column buffers.
                    sizes = [(chunk.total_compressed_size, chunk.total_uncompressed_size)
                             for chunk in chunks]
                    if len(chunks) != len(columns) or any(a < 0 or b < 0 for a, b in sizes):
                        continue
                    # Chunk sizes include dictionary/delta encodings, not decoded
                    # string allocation. A value can be reused for every row.
                    # Reject on a conservative worst-case expansion BEFORE Arrow
                    # decoding or Python string materialization. Six covers Arrow
                    # data plus Python's up-to-four-byte Unicode and slack;
                    # the row allowance covers offsets, dictionaries and strings.
                    cost = (sum(max(a, b) for a, b in sizes) * group.num_rows * 6
                            + group.num_rows * (256 + 64 * len(columns)))
                    if cost > bytes_left:
                        continue
                    bytes_left -= cost
                    rows_left -= group.num_rows
                    table = parquet.read_row_group(index, columns=columns, use_threads=False)
                    _history_rows(table.to_pylist(), result)
                    if len(result) >= MAX_CANDIDATES or rows_left <= 0:
                        return list(result.values())
        except Exception:
            # Missing, corrupt, permission errors and unsupported schemas are advisory.
            continue
    return list(result.values())


def _run():
    while True:
        _wake.wait()
        with _lock:
            task = next(((path, entry) for path, entry in _cache.items()
                         if entry.pending and not entry.running), None)
            if task is None:
                _wake.clear()
                continue
            path, entry = task
            entry.running = True
        try:
            values = _read_history(path)
        except Exception:
            values = []
        with _lock:
            if _cache.get(path) is entry:
                entry.values = values
                entry.updated = time.monotonic()
                entry.pending = False
                entry.running = False


def _cached_history(path):
    global _worker
    # Path conversion is lexical: no resolve/exists/stat on the UI thread.
    try:
        path = os.fspath(path)
    except TypeError:
        return []
    if not isinstance(path, str) or not path or len(path) > 4096:
        return []
    with _lock:
        entry = _cache.get(path)
        if entry is None:
            entry = _Entry()
            _cache[path] = entry
            if len(_cache) > MAX_PATHS:
                _cache.popitem(last=False)
        else:
            _cache.move_to_end(path)
            if not entry.pending and time.monotonic() - entry.updated >= TTL_SECONDS:
                entry.pending = True
        if entry.pending:
            _wake.set()
            if _worker is None:
                _worker = threading.Thread(target=_run, name='owner-history', daemon=True)
                _worker.start()
        return list(entry.values)


def suggestions(records, config, history_path=None):
    """Return up to 500 normalized email/name choices, without waiting for I/O.

    Record names take precedence over config and history names. The explicit
    history path overrides the chronicle default. Refreshes keep stale results
    available until the one background worker completes its bounded sample.
    """
    result = {}
    for row in islice(records or (), MAX_ROWS):
        if isinstance(row, dict):
            _add(result, row.get('owner_email'), row.get('owner_name'))
    users = config.get('reservation_users') if isinstance(config, dict) else ()
    if isinstance(users, (list, tuple)):
        for user in islice(users, MAX_ROWS):
            if isinstance(user, dict):
                _add(result, user.get('email'), user.get('name'))
    path = DEFAULT_HISTORY_PATH if history_path is None else history_path
    for row in _cached_history(path):
        _add(result, row.get('email'), row.get('name'))
    return list(result.values())
