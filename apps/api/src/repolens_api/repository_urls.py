"""Validation and canonicalization for supported GitHub repository URLs."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class InvalidRepositoryUrl(ValueError):
    """Raised when a URL is not a supported public GitHub repository URL."""


@dataclass(frozen=True, slots=True)
class CanonicalRepository:
    """Validated canonical repository identity."""

    canonical_url: str
    owner: str
    name: str


def parse_repository_url(value: str) -> CanonicalRepository:
    """Validate a public GitHub repository URL and return its canonical identity."""
    if not value or value != value.strip() or "\\" in value or "%" in value:
        raise InvalidRepositoryUrl

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise InvalidRepositoryUrl from exc

    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise InvalidRepositoryUrl

    if parsed.netloc.lower() != "github.com":
        raise InvalidRepositoryUrl

    has_trailing_slash = parsed.path.endswith("/")
    path = parsed.path[:-1] if has_trailing_slash else parsed.path
    segments = path.split("/")
    if len(segments) != 3 or segments[0] or not segments[1] or not segments[2]:
        raise InvalidRepositoryUrl

    owner, repository_name = segments[1], segments[2]
    if repository_name.endswith(".git"):
        if has_trailing_slash:
            raise InvalidRepositoryUrl
        repository_name = repository_name[:-4]

    if (
        not OWNER_PATTERN.fullmatch(owner)
        or "--" in owner
        or not REPOSITORY_PATTERN.fullmatch(repository_name)
        or repository_name in {".", ".."}
    ):
        raise InvalidRepositoryUrl

    return CanonicalRepository(
        canonical_url=f"https://github.com/{owner}/{repository_name}",
        owner=owner,
        name=repository_name,
    )
