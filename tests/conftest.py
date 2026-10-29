"""Keep offline UI fixtures away from any node's real history directory."""
import pytest


@pytest.fixture(autouse=True)
def isolated_reservation_history(monkeypatch):
    import webui_reservations as ui
    from patroller_webui.owner_suggestions import suggestions

    # Unit tests for the history reader call that module directly with synthetic
    # Parquet files. Ordinary page/form fixtures need only memory suggestions.
    monkeypatch.setattr(ui, 'suggestions', lambda records, config, history_path=None, users=None:
                        suggestions(records, config, history_path='', users=users))
