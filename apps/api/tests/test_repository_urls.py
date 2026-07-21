"""Tests for the supported public GitHub repository URL policy."""

import pytest

from repolens_api.repository_urls import InvalidRepositoryUrl, parse_repository_url


@pytest.mark.parametrize(
    ("value", "canonical_url", "owner", "name"),
    [
        (
            "https://github.com/openai/openai-python",
            "https://github.com/openai/openai-python",
            "openai",
            "openai-python",
        ),
        (
            "https://github.com/openai/openai-python/",
            "https://github.com/openai/openai-python",
            "openai",
            "openai-python",
        ),
        (
            "https://github.com/openai/openai-python.git",
            "https://github.com/openai/openai-python",
            "openai",
            "openai-python",
        ),
    ],
)
def test_supported_urls_are_canonicalized(
    value: str,
    canonical_url: str,
    owner: str,
    name: str,
) -> None:
    repository = parse_repository_url(value)

    assert repository.canonical_url == canonical_url
    assert repository.owner == owner
    assert repository.name == name


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/openai/openai-python",
        "https://gitlab.com/openai/openai-python",
        "git@github.com:openai/openai-python.git",
        "ssh://git@github.com/openai/openai-python.git",
        "https://github.com/openai",
        "https://github.com/openai/openai-python/issues",
        "https://github.com/openai/openai-python?tab=readme",
        "https://github.com/openai/openai-python#readme",
        "https://user@github.com/openai/openai-python",
        "https://localhost/openai/openai-python",
        "https://127.0.0.1/openai/openai-python",
        "https://github.com:443/openai/openai-python",
        "https://github.com:invalid/openai/openai-python",
        "https://github.com//openai/openai-python",
        "https://github.com/openai/.git",
        "https://github.com/openai/openai-python.git/",
        "https://github.com/open--ai/openai-python",
        "https://github.com/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/openai-python",
        "https://github.com/openai/.",
        "https://github.com/openai/..",
        "https://github.com/openai/openai%2Fpython",
        "https://github.com/openai\\openai-python",
    ],
)
def test_unsupported_urls_are_rejected(value: str) -> None:
    with pytest.raises(InvalidRepositoryUrl):
        parse_repository_url(value)
