"""Cold first-request /reservations bootstrap stays packaged and delegates once."""
import ast
from pathlib import Path
from setuptools import find_packages

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_is_packaged_for_installed_entrypoint():
    assert 'patroller_webui.pages' in find_packages(str(ROOT))


def test_bootstrap_uses_normal_entrypoint_without_duplicate_page_or_credentials():
    path = ROOT / 'patroller_webui/pages/reservations.py'
    tree = ast.parse(path.read_text())
    statements = tree.body[1:] if isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) else tree.body
    assert len(statements) == 2
    imported, called = statements
    assert isinstance(imported, ast.ImportFrom)
    assert imported.module == 'patroller_webui.webui'
    assert [(alias.name, alias.asname) for alias in imported.names] == [('run', None)]
    assert isinstance(called, ast.Expr) and isinstance(called.value, ast.Call)
    assert isinstance(called.value.func, ast.Name) and called.value.func.id == 'run'
    assert called.value.args == [] and called.value.keywords == []
