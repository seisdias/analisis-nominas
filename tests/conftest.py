from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-private", action="store_true", default=False,
        help="Collect and run integration tests against local private documents.",
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    if collection_path == Path(__file__).parent / "integration":
        if not config.getoption("--run-private"):
            return True
    return None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in item.path.relative_to(Path(__file__).parent).parts:
            item.add_marker(pytest.mark.private)
