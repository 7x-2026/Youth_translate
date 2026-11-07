import pytest


@pytest.fixture(autouse=True)
def isolate_course_database(tmp_path, monkeypatch):
    # Existing relay tests must never write fixture captions into real history.
    monkeypatch.setattr('backend.app.records_path', lambda: tmp_path / 'records.sqlite3')
