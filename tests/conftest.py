import pytest


@pytest.fixture(autouse=True)
def spanish_by_default(monkeypatch):
    """Most tests check Spanish output; test_i18n switches to English on purpose.
    La mayoría de las pruebas revisan la salida en español; test_i18n cambia a inglés."""
    monkeypatch.setenv("TOPOS_LANG", "es")
