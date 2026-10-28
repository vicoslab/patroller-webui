"""Navigation icons share the theme's monochrome Material styling."""
from types import SimpleNamespace
from unittest.mock import Mock


def test_reservations_uses_material_lock_like_other_navigation_icons(monkeypatch):
    import webui

    pages = []

    def page(function, **options):
        item = SimpleNamespace(function=function, **options)
        pages.append(item)
        return item

    monkeypatch.setattr(webui.st, 'set_page_config', Mock())
    monkeypatch.setattr(webui.st, 'Page', page)
    monkeypatch.setattr(webui.st, 'navigation', Mock(return_value=SimpleNamespace(run=Mock())))
    webui.run()

    reservation = next(item for item in pages if item.title == 'Reservations')
    assert reservation.icon == ':material/lock:'
    assert all(item.icon.startswith(':material/') for item in pages)
