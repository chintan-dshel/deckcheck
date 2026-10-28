import importlib.metadata


def test_packages_import():
    import bakeoff  # noqa: F401
    import deckcheck
    assert deckcheck.__version__ == "0.0.1"


def test_dynars_is_pinned_version():
    assert importlib.metadata.version("dynars") == "1.1.0"
