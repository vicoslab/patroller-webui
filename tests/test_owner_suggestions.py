"""Synthetic history only: bounded sampling and nonblocking cache behavior."""
import importlib
import threading
import time

import pytest

from patroller_webui import owner_suggestions as owners


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(owners, 'DEFAULT_HISTORY_PATH', str(tmp_path / 'missing.parquet'))
    with owners._lock:
        owners._cache.clear()
    yield
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with owners._lock:
            if not any(entry.pending for entry in owners._cache.values()):
                break
        time.sleep(.005)


def settled(path):
    owners.suggestions([], {}, path)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with owners._lock:
            entry = owners._cache.get(str(path))
            done = entry is not None and not entry.pending
        if done:
            return owners.suggestions([], {}, path)
        time.sleep(.005)
    pytest.fail('history worker did not finish')


def parquet(path, values, **kwargs):
    pa = pytest.importorskip('pyarrow')
    pq = pytest.importorskip('pyarrow.parquet')
    pq.write_table(pa.table(values), path, **kwargs)


def test_memory_normalization_priority_and_cap():
    result = owners.suggestions([
        {'owner_email': ' A@Example.COM ', 'owner_name': ' Record '},
        {'owner_email': 'bare name'}, {'owner_email': 'bad\n@example.com'},
    ], {'reservation_users': [{'email': 'a@example.com', 'name': 'Config'},
                              {'email': 'b@example.com', 'name': ' Bee '}]})
    assert result == [{'email': 'a@example.com', 'name': 'Record'},
                      {'email': 'b@example.com', 'name': 'Bee'}]
    assert len(owners.suggestions([{'owner_email': f'u{i}@example.com'} for i in range(900)], {})) == 500


def test_real_user_labels_and_projected_columns(tmp_path, monkeypatch):
    path = tmp_path / 'data.parquet'
    parquet(path, {'user': ['Alice', 'Alice <A@Example.com>', ' B@example.com ', None],
                   'payload': ['x' * 100_000] * 4})
    pq = importlib.import_module('pyarrow.parquet')
    original = pq.ParquetFile
    seen = []
    class Spy:
        def __init__(self, *args, **kwargs):
            assert kwargs['thrift_string_size_limit'] <= owners.MAX_FOOTER_BYTES
            self.inner = original(*args, **kwargs)
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def read_row_group(self, index, columns, **kwargs):
            seen.append(columns)
            return self.inner.read_row_group(index, columns=columns, **kwargs)
    monkeypatch.setattr(pq, 'ParquetFile', Spy)
    assert settled(path) == [{'email': 'a@example.com', 'name': 'Alice'},
                             {'email': 'b@example.com', 'name': ''}]
    assert seen == [['user']]


def test_real_email_name_and_owner_columns(tmp_path):
    path = tmp_path / 'data.parquet'
    parquet(path, {'email': ['a@example.com'], 'name': ['Alice'],
                   'owner_email': ['b@example.com'], 'owner_name': ['Bob']})
    assert settled(path) == [{'email': 'b@example.com', 'name': 'Bob'},
                             {'email': 'a@example.com', 'name': 'Alice'}]


def test_exact_and_latest_four_indexed_files(tmp_path):
    path = tmp_path / 'data.parquet'
    parquet(path, {'user': ['exact@example.com']})
    for index in range(6):
        parquet(tmp_path / f'data_{index}.parquet', {'user': [f'u{index}@example.com']})
    parquet(tmp_path / 'database_99.parquet', {'user': ['wrong@example.com']})
    assert {v['email'] for v in settled(path)} == {
        'exact@example.com', 'u5@example.com', 'u4@example.com', 'u3@example.com'}


@pytest.mark.parametrize('kind', ['missing', 'corrupt', 'footer'])
def test_unreadable_history_safe(tmp_path, kind):
    path = tmp_path / 'bad.parquet'
    if kind == 'corrupt':
        path.write_bytes(b'not parquet')
    if kind == 'footer':
        path.write_bytes(b'PAR1' + (owners.MAX_FOOTER_BYTES + 1).to_bytes(4, 'little') + b'PAR1')
    assert settled(path) == []


def test_optional_dependency_failure(tmp_path, monkeypatch):
    import builtins
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name.startswith('pyarrow'):
            raise ImportError('optional')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', importing)
    assert settled(tmp_path / 'x.parquet') == []


def test_oversized_groups_skipped_before_decode(tmp_path, monkeypatch):
    path = tmp_path / 'large.parquet'
    parquet(path, {'user': ['a@example.com'] * (owners.MAX_ROWS + 1)})
    pq = importlib.import_module('pyarrow.parquet')
    original = pq.ParquetFile
    class NoDecode:
        def __init__(self, *args, **kwargs): self.inner = original(*args, **kwargs)
        def __getattr__(self, name): return getattr(self.inner, name)
        def read_row_group(self, *args, **kwargs): pytest.fail('oversized group decoded')
    monkeypatch.setattr(pq, 'ParquetFile', NoDecode)
    assert settled(path) == []


def test_selected_bytes_budget_and_group_budget(tmp_path, monkeypatch):
    path = tmp_path / 'data.parquet'
    parquet(path, {'user': ['a@example.com'] * 12}, row_group_size=1)
    monkeypatch.setattr(owners, 'MAX_GROUPS', 2)
    monkeypatch.setattr(owners, 'MAX_COLUMN_BYTES', 1)
    assert settled(path) == []


def test_bounded_directory_scan(tmp_path, monkeypatch):
    seen = []
    class Entries:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def __iter__(self):
            for i in range(1000):
                seen.append(i)
                yield type('Entry', (), {'name': f'unrelated{i}'})()
    monkeypatch.setattr(owners.os, 'scandir', lambda path: Entries())
    assert settled(tmp_path / 'data.parquet') == []
    assert len(seen) <= 256


def test_first_refresh_and_hung_worker_are_nonblocking(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow(path):
        calls.append(path)
        entered.set()
        release.wait(3)
        return [{'email': 'old@example.com', 'name': ''}]
    monkeypatch.setattr(owners, '_read_history', slow)
    path = tmp_path / 'data.parquet'
    try:
        start = time.monotonic()
        assert owners.suggestions([], {}, path) == []
        assert time.monotonic() - start < .2
        assert entered.wait(1)
        worker = owners._worker
        assert worker.daemon
        for i in range(100):
            start = time.monotonic()
            owners.suggestions([], {}, tmp_path / f'{i}.parquet')
            assert time.monotonic() - start < .2
            assert owners._worker is worker
        assert len(calls) == 1
        assert len(owners._cache) <= 8
    finally:
        release.set()
    settled(path)
    entered.clear()
    release.clear()
    try:
        with owners._lock:
            owners._cache[str(path)].updated -= 301
        start = time.monotonic()
        assert owners.suggestions([], {}, path) == [{'email': 'old@example.com', 'name': ''}]
        assert time.monotonic() - start < .2
        assert entered.wait(1)
        assert owners._worker is worker
    finally:
        release.set()


def test_history_cap_and_name_validation(tmp_path):
    path = tmp_path / 'data.parquet'
    # Small safe groups exercise the 500-entry cap without exceeding the
    # conservative pre-decode dictionary-expansion allowance.
    parquet(path, {'user': [f'u{i}@example.com' for i in range(700)]}, row_group_size=100)
    assert len(settled(path)) == 500
    result = owners.suggestions([
        {'owner_email': 'valid@example.com', 'owner_name': 'x' * 201},
        {'owner_email': 'other@example.com', 'owner_name': 'unsafe\x7fname'},
        {'owner_email': 'not-an-email'}, {'owner_email': 123},
    ], {})
    assert result == [{'email': 'valid@example.com', 'name': ''},
                      {'email': 'other@example.com', 'name': ''}]


def test_real_eight_megabyte_column_is_not_decoded(tmp_path, monkeypatch):
    path = tmp_path / 'data.parquet'
    parquet(path, {'user': ['x' * (owners.MAX_COLUMN_BYTES + 1)]}, compression='snappy')
    pq = importlib.import_module('pyarrow.parquet')
    original = pq.ParquetFile
    class NoDecode:
        def __init__(self, *args, **kwargs): self.inner = original(*args, **kwargs)
        def __getattr__(self, name): return getattr(self.inner, name)
        def read_row_group(self, *args, **kwargs): pytest.fail('oversized column decoded')
    monkeypatch.setattr(pq, 'ParquetFile', NoDecode)
    assert settled(path) == []


def test_dictionary_expansion_is_rejected_before_decode(tmp_path, monkeypatch):
    path = tmp_path / 'dictionary.parquet'
    parquet(path, {'user': ['x' * 16_384] * 1024}, use_dictionary=True)
    pq = importlib.import_module('pyarrow.parquet')
    original = pq.ParquetFile
    metadata = original(path).metadata.row_group(0)
    assert metadata.column(0).total_uncompressed_size < owners.MAX_COLUMN_BYTES
    assert metadata.column(0).total_uncompressed_size * metadata.num_rows > owners.MAX_COLUMN_BYTES
    class NoDecode:
        def __init__(self, *args, **kwargs): self.inner = original(*args, **kwargs)
        def __getattr__(self, name): return getattr(self.inner, name)
        def read_row_group(self, *args, **kwargs): pytest.fail('dictionary expansion decoded before validation')
    monkeypatch.setattr(pq, 'ParquetFile', NoDecode)
    assert settled(path) == []


def test_real_total_group_and_row_budgets(tmp_path):
    groups = tmp_path / 'groups.parquet'
    parquet(groups, {'user': [f'u{i}@example.com' for i in range(10)]}, row_group_size=1)
    assert len(settled(groups)) == 8
    rows = tmp_path / 'rows.parquet'
    parquet(rows, {'user': ['a@example.com'] * 4096 + ['b@example.com'] * 4096
                           + ['c@example.com'] * 4096}, row_group_size=4096)
    assert settled(rows) == [{'email': 'a@example.com', 'name': ''},
                             {'email': 'b@example.com', 'name': ''}]


def test_history_io_stays_on_worker_and_ttl_reuses_cache(tmp_path, monkeypatch):
    import builtins
    path = tmp_path / 'data.parquet'
    parquet(path, {'user': ['a@example.com']})
    original_open, original_scan = builtins.open, owners.os.scandir
    threads = []
    def opening(*args, **kwargs):
        threads.append(threading.current_thread())
        assert threading.current_thread() is not threading.main_thread()
        return original_open(*args, **kwargs)
    def scanning(*args, **kwargs):
        threads.append(threading.current_thread())
        assert threading.current_thread() is not threading.main_thread()
        return original_scan(*args, **kwargs)
    monkeypatch.setattr(builtins, 'open', opening)
    monkeypatch.setattr(owners.os, 'scandir', scanning)
    assert settled(path) == [{'email': 'a@example.com', 'name': ''}]
    count = len(threads)
    for _ in range(20):
        assert owners.suggestions([], {}, path) == [{'email': 'a@example.com', 'name': ''}]
    assert len(threads) == count
    assert threads and all(t is owners._worker for t in threads)


def test_reader_exception_is_safe_and_worker_recovers(tmp_path, monkeypatch):
    def broken(path): raise PermissionError('synthetic denied')
    monkeypatch.setattr(owners, '_read_history', broken)
    assert settled(tmp_path / 'broken.parquet') == []
    monkeypatch.setattr(owners, '_read_history', lambda path: [{'email': 'ok@example.com', 'name': ''}])
    assert settled(tmp_path / 'ok.parquet') == [{'email': 'ok@example.com', 'name': ''}]
