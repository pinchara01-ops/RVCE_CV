"""Repository-wide test safeguards and environment gates.

Several retrieval integration fixtures recreate their target Qdrant
collection. Tests must never default to the interactive video library.
"""
import os

import pytest

os.environ["COLLECTION_NAME"] = "video_windows_query_test"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-qdrant",
        action="store_true",
        default=False,
        help=(
            "fail before collection if the Qdrant integration endpoint is not ready; "
            "otherwise qdrant-marked tests are skipped with an actionable reason"
        ),
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Turn an absent local service into an explicit test-environment result.

    The unit/contract suite must remain useful on a clean machine.  The
    integration suite is still strict whenever a caller asks for it with
    ``--require-qdrant`` (as CI does), so an unavailable database cannot be
    mistaken for a passing integration run.
    """
    qdrant_items = [item for item in items if item.get_closest_marker("qdrant")]
    if not qdrant_items:
        return

    # ``-m 'not qdrant'`` is the documented offline contract suite; it should
    # not perform any network probe merely because Qdrant tests were collected.
    mark_expression = str(config.getoption("markexpr") or "")
    if "not qdrant" in mark_expression.lower():
        return

    from query_retrieval import config as retrieval_config
    from query_retrieval.environment_checks import qdrant_readiness

    readiness = qdrant_readiness(retrieval_config.QDRANT_URL)
    if readiness.available:
        return

    message = (
        f"Qdrant integration tests require a healthy local endpoint "
        f"({readiness.label}); {readiness.reason}. "
        "Start the pinned Qdrant service with 'docker compose up -d qdrant', "
        "then rerun with --require-qdrant."
    )
    if config.getoption("require_qdrant"):
        raise pytest.UsageError(message)

    skip = pytest.mark.skip(reason=message)
    for item in qdrant_items:
        item.add_marker(skip)
