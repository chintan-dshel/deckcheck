import importlib.metadata


def test_packages_import():
    import bakeoff  # noqa: F401
    import deckcheck
    assert deckcheck.__version__ == "0.0.1"


def test_dynars_is_pinned_version():
    assert importlib.metadata.version("dynars") == "1.1.0"


def test_deckcheck_has_no_runtime_dependencies():
    requires = importlib.metadata.requires("deckcheck") or []
    assert all("extra ==" in r for r in requires), [r for r in requires if "extra ==" not in r]
