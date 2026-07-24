"""Stable thresholds, filenames, and fixed quality-finding text."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from repolens_api.quality_findings.contracts import (
    QualityCategory,
    QualityFindingCode,
    QualitySeverity,
)

README_MIN_BYTES = 512
README_MIN_NONEMPTY_LINES = 8
SPARSE_TEST_MIN_SOURCE_FILES = 10
SPARSE_TEST_RATIO_PER_MILLE = 100
OVERSIZED_SOURCE_FILE_BYTES = 131_072
SYMBOL_DENSE_FILE_COUNT = 100
IMPORT_DENSE_FILE_COUNT = 50
METHOD_DENSE_FILE_COUNT = 50
SOURCE_CONCENTRATION_MIN_FILES = 3
SOURCE_CONCENTRATION_MIN_SYMBOLS = 20
SOURCE_CONCENTRATION_PER_MILLE = 600
STRUCTURE_WARNING_HIGH_COUNT = 10
STRUCTURE_SUCCESS_PER_MILLE = 900
ROOT_FILE_DENSITY_COUNT = 25
MAX_QUALITY_PATH_LENGTH = 512

TEST_CONFIGURATION_NAMES = frozenset(
    {
        "pytest.ini",
        "tox.ini",
        "noxfile.py",
        "jest.config.js",
        "jest.config.cjs",
        "jest.config.mjs",
        "jest.config.ts",
        "vitest.config.js",
        "vitest.config.mjs",
        "vitest.config.ts",
        "playwright.config.js",
        "playwright.config.ts",
    }
)
TEST_FRAMEWORK_NAMES = frozenset(
    {
        "pytest",
        "unittest",
        "vitest",
        "jest",
        "mocha",
        "playwright",
        "cypress",
        "junit",
        "testng",
        "rspec",
    }
)
LOCKFILE_NAMES = frozenset(
    {
        "cargo.lock",
        "composer.lock",
        "go.sum",
        "package-lock.json",
        "pnpm-lock.yaml",
        "poetry.lock",
        "uv.lock",
        "yarn.lock",
    }
)
MANIFEST_NAMES = frozenset(
    {
        "cargo.toml",
        "composer.json",
        "go.mod",
        "package.json",
        "pom.xml",
        "pyproject.toml",
        "requirements.txt",
    }
)
MANIFEST_LOCKFILE_NAMES: dict[str, frozenset[str]] = {
    "cargo.toml": frozenset({"cargo.lock"}),
    "composer.json": frozenset({"composer.lock"}),
    "go.mod": frozenset({"go.sum"}),
    "package.json": frozenset({"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}),
    "pyproject.toml": frozenset({"poetry.lock", "uv.lock"}),
    "requirements.txt": frozenset({"poetry.lock", "uv.lock"}),
}
CI_EXACT_PATHS = frozenset(
    {
        ".gitlab-ci.yml",
        ".travis.yml",
        "azure-pipelines.yml",
        ".circleci/config.yml",
    }
)
DEPENDENCY_AUTOMATION_PATHS = frozenset(
    {
        ".github/dependabot.yml",
        ".github/dependabot.yaml",
        "renovate.json",
        "renovate.json5",
        ".renovaterc",
        ".renovaterc.json",
    }
)
CONTAINER_NAMES = frozenset(
    {
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
    }
)
COMMUNITY_PATH_MARKERS = (
    "/issue_template/",
    "/pull_request_template",
    "/codeowners",
)
INSTALLATION_HEADINGS = frozenset(
    {"install", "installation", "setup", "getting started", "quickstart", "prerequisites"}
)
USAGE_HEADINGS = frozenset({"usage", "use", "example", "examples", "quickstart"})
TESTING_HEADINGS = frozenset({"test", "tests", "testing", "development"})

CI_TEST_PATTERN = re.compile(
    r"\b(pytest|vitest|jest|mocha|test|tests|testing|ctest|go\s+test|cargo\s+test)\b",
    re.IGNORECASE,
)
CI_LINT_PATTERN = re.compile(
    r"\b(lint|eslint|ruff|flake8|pylint|mypy|type-check|typecheck)\b",
    re.IGNORECASE,
)
CI_BUILD_PATTERN = re.compile(
    r"\b(build|compile|package|next\s+build|docker\s+build|cargo\s+build)\b",
    re.IGNORECASE,
)
CI_COMMAND_LINE_PATTERN = re.compile(
    r"^\s*(?:-\s*)?(?:run|script|command)\s*:\s*\S+",
    re.IGNORECASE,
)
CI_LIST_COMMAND_PATTERN = re.compile(
    r"^\s*-\s+(?!uses\s*:|name\s*:)[A-Za-z0-9_./-]+(?:\s|$)",
    re.IGNORECASE,
)
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]\r\n]{1,200}\]\([^) \r\n]{1,512}\)")
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.{1,200})$")


@dataclass(frozen=True, slots=True)
class FindingText:
    """Fixed metadata for one finding code."""

    category: QualityCategory
    severity: QualitySeverity
    title: str
    message: str
    recommendation: str


def _text(
    category: QualityCategory,
    severity: QualitySeverity,
    title: str,
    message: str,
    recommendation: str,
) -> FindingText:
    return FindingText(category, severity, title, message, recommendation)


FINDING_TEXTS: dict[QualityFindingCode, FindingText] = {
    QualityFindingCode.README_MISSING: _text(
        QualityCategory.DOCUMENTATION,
        QualitySeverity.HIGH,
        "README is missing",
        "No repository README was detected.",
        "Add a README that explains the project, setup, usage, and testing workflow.",
    ),
    QualityFindingCode.README_TOO_SMALL: _text(
        QualityCategory.DOCUMENTATION,
        QualitySeverity.MEDIUM,
        "README is very small",
        "The README contains too little material for reliable onboarding.",
        "Expand the README with concise setup, usage, testing, and project context.",
    ),
    QualityFindingCode.README_INSTALLATION_MISSING: _text(
        QualityCategory.DOCUMENTATION,
        QualitySeverity.MEDIUM,
        "Installation guidance is missing",
        "No reliable installation or setup section was detected in the README.",
        "Add a clearly titled installation or setup section.",
    ),
    QualityFindingCode.README_USAGE_MISSING: _text(
        QualityCategory.DOCUMENTATION,
        QualitySeverity.LOW,
        "Usage guidance is missing",
        "No reliable usage or example section was detected in the README.",
        "Add a clearly titled usage section with a minimal example.",
    ),
    QualityFindingCode.README_TESTING_MISSING: _text(
        QualityCategory.DOCUMENTATION,
        QualitySeverity.LOW,
        "Testing guidance is missing",
        "No reliable testing section was detected in the README.",
        "Document how contributors run the supported test suite.",
    ),
    QualityFindingCode.DOCUMENTATION_PRESENT: _text(
        QualityCategory.DOCUMENTATION,
        QualitySeverity.INFO,
        "Project documentation is present",
        "The repository contains useful documentation signals.",
        "Keep documentation aligned with the implemented developer workflow.",
    ),
    QualityFindingCode.TESTS_MISSING: _text(
        QualityCategory.TESTING,
        QualitySeverity.MEDIUM,
        "Tests are missing",
        "No test files were detected for the supported source inventory.",
        "Add focused automated tests for important behavior and failure paths.",
    ),
    QualityFindingCode.TESTS_SPARSE: _text(
        QualityCategory.TESTING,
        QualitySeverity.LOW,
        "Tests appear sparse",
        "The test-to-source file ratio is below the documented heuristic threshold.",
        "Review high-risk source areas and add representative automated tests.",
    ),
    QualityFindingCode.TESTS_PRESENT: _text(
        QualityCategory.TESTING,
        QualitySeverity.INFO,
        "Tests are present",
        "The repository contains detected test files.",
        "Keep tests deterministic and maintain them with behavior changes.",
    ),
    QualityFindingCode.TEST_CONFIGURATION_PRESENT: _text(
        QualityCategory.TESTING,
        QualitySeverity.INFO,
        "Test configuration is present",
        "A recognized test configuration or manifest test command was detected.",
        "Keep test configuration and contributor documentation consistent.",
    ),
    QualityFindingCode.MULTIPLE_TEST_FRAMEWORKS_PRESENT: _text(
        QualityCategory.TESTING,
        QualitySeverity.INFO,
        "Multiple test frameworks are present",
        "More than one recognized test framework signal was detected.",
        "Document the purpose and invocation of each test framework.",
    ),
    QualityFindingCode.EXAMPLE_ONLY_TESTS: _text(
        QualityCategory.TESTING,
        QualitySeverity.LOW,
        "Only example-like tests were detected",
        "All detected test paths are marked as examples, demos, samples, or fixtures.",
        "Add tests that directly exercise production behavior.",
    ),
    QualityFindingCode.TEST_CI_INTEGRATION_MISSING: _text(
        QualityCategory.TESTING,
        QualitySeverity.MEDIUM,
        "Tests are not integrated with CI",
        "Tests exist, but no reliable CI test signal was detected.",
        "Run the supported test suite in continuous integration.",
    ),
    QualityFindingCode.TEST_CI_INTEGRATION_PRESENT: _text(
        QualityCategory.TESTING,
        QualitySeverity.INFO,
        "Tests run in CI",
        "Test files and a reliable CI test signal were both detected.",
        "Keep CI test commands aligned with the documented local workflow.",
    ),
    QualityFindingCode.LICENSE_MISSING: _text(
        QualityCategory.PROJECT_GOVERNANCE,
        QualitySeverity.MEDIUM,
        "License is missing",
        "No license file was detected.",
        "Add an explicit license appropriate for the project.",
    ),
    QualityFindingCode.LICENSE_PRESENT: _text(
        QualityCategory.PROJECT_GOVERNANCE,
        QualitySeverity.INFO,
        "License is present",
        "An explicit repository license file was detected.",
        "Keep licensing information clear and current.",
    ),
    QualityFindingCode.CONTRIBUTING_MISSING: _text(
        QualityCategory.PROJECT_GOVERNANCE,
        QualitySeverity.LOW,
        "Contributing guidance is missing",
        "No contributing guide was detected.",
        "Add concise contribution and local-development guidance.",
    ),
    QualityFindingCode.CONTRIBUTING_PRESENT: _text(
        QualityCategory.PROJECT_GOVERNANCE,
        QualitySeverity.INFO,
        "Contributing guidance is present",
        "A contributing guide was detected.",
        "Keep contribution guidance synchronized with repository tooling.",
    ),
    QualityFindingCode.SECURITY_POLICY_MISSING: _text(
        QualityCategory.PROJECT_GOVERNANCE,
        QualitySeverity.INFO,
        "Security policy is missing",
        "No security policy file was detected.",
        "Consider documenting a private vulnerability-reporting process.",
    ),
    QualityFindingCode.SECURITY_POLICY_PRESENT: _text(
        QualityCategory.PROJECT_GOVERNANCE,
        QualitySeverity.INFO,
        "Security policy is present",
        "A security policy file was detected.",
        "Review the security policy periodically.",
    ),
    QualityFindingCode.COMMUNITY_FILES_PRESENT: _text(
        QualityCategory.PROJECT_GOVERNANCE,
        QualitySeverity.INFO,
        "Community files are present",
        "Repository community and ownership files were detected.",
        "Keep templates and ownership data concise and current.",
    ),
    QualityFindingCode.CI_MISSING: _text(
        QualityCategory.AUTOMATION,
        QualitySeverity.MEDIUM,
        "Continuous integration is missing",
        "No recognized continuous-integration configuration was detected.",
        "Add CI that runs the repository's documented quality checks.",
    ),
    QualityFindingCode.CI_PRESENT: _text(
        QualityCategory.AUTOMATION,
        QualitySeverity.INFO,
        "Continuous integration is present",
        "A recognized continuous-integration configuration was detected.",
        "Keep CI checks aligned with local contributor commands.",
    ),
    QualityFindingCode.CI_QUALITY_CHECKS_MISSING: _text(
        QualityCategory.AUTOMATION,
        QualitySeverity.MEDIUM,
        "CI quality checks are unclear",
        "CI exists, but no reliable lint, test, or build signal was detected.",
        "Add explicit lint, test, or build validation to CI.",
    ),
    QualityFindingCode.DEPENDENCY_UPDATE_AUTOMATION_PRESENT: _text(
        QualityCategory.AUTOMATION,
        QualitySeverity.INFO,
        "Dependency update automation is present",
        "A recognized dependency-update configuration was detected.",
        "Review automated dependency updates with the normal quality gates.",
    ),
    QualityFindingCode.CONTAINER_SETUP_PRESENT: _text(
        QualityCategory.AUTOMATION,
        QualitySeverity.INFO,
        "Container setup is present",
        "A Dockerfile or Compose configuration was detected.",
        "Keep container setup documented and reproducible.",
    ),
    QualityFindingCode.OVERSIZED_SOURCE_FILE: _text(
        QualityCategory.MAINTAINABILITY,
        QualitySeverity.MEDIUM,
        "Source file is very large",
        "A supported source file exceeds the documented size heuristic.",
        "Review whether the file can be separated into cohesive modules.",
    ),
    QualityFindingCode.SYMBOL_DENSE_FILE: _text(
        QualityCategory.MAINTAINABILITY,
        QualitySeverity.MEDIUM,
        "Source file is symbol-dense",
        "A source file contains more declarations than the documented heuristic.",
        "Review whether declarations can be grouped into smaller cohesive modules.",
    ),
    QualityFindingCode.IMPORT_DENSE_FILE: _text(
        QualityCategory.MAINTAINABILITY,
        QualitySeverity.LOW,
        "Source file is import-dense",
        "A source file contains more imports than the documented heuristic.",
        "Review module responsibilities and dependency boundaries.",
    ),
    QualityFindingCode.METHOD_DENSE_FILE: _text(
        QualityCategory.MAINTAINABILITY,
        QualitySeverity.LOW,
        "Source file is method-dense",
        "A source file contains more methods than the documented heuristic.",
        "Review class responsibilities and consider cohesive separation.",
    ),
    QualityFindingCode.SOURCE_CONCENTRATION_HIGH: _text(
        QualityCategory.MAINTAINABILITY,
        QualitySeverity.MEDIUM,
        "Source declarations are highly concentrated",
        "A single source file contains a large share of detected declarations.",
        "Review whether the dominant file has too many responsibilities.",
    ),
    QualityFindingCode.SOURCE_PARSE_ERRORS_PRESENT: _text(
        QualityCategory.MAINTAINABILITY,
        QualitySeverity.MEDIUM,
        "Source parse errors are present",
        "One or more supported source files could not be parsed cleanly.",
        "Review supported source syntax and generated-file exclusions.",
    ),
    QualityFindingCode.STRUCTURE_WARNINGS_HIGH: _text(
        QualityCategory.MAINTAINABILITY,
        QualitySeverity.LOW,
        "Source-structure warnings are numerous",
        "The number of source-structure warnings reached the documented heuristic.",
        "Review skipped, malformed, or truncated source files.",
    ),
    QualityFindingCode.STRUCTURE_ANALYSIS_SUCCESSFUL: _text(
        QualityCategory.MAINTAINABILITY,
        QualitySeverity.INFO,
        "Source structure parsed successfully",
        "Most supported source files produced reliable structure.",
        "Keep supported source syntax and repository exclusions predictable.",
    ),
    QualityFindingCode.ROOT_FILE_DENSITY_HIGH: _text(
        QualityCategory.MAINTAINABILITY,
        QualitySeverity.LOW,
        "Repository root is file-dense",
        "The repository root contains many regular files.",
        "Review whether related files belong in clearly named directories.",
    ),
    QualityFindingCode.ENTRY_POINT_MISSING: _text(
        QualityCategory.ONBOARDING,
        QualitySeverity.MEDIUM,
        "Entry point is unclear",
        "A dependency manifest exists, but no reliable entry point was detected.",
        "Document or expose the primary application entry point.",
    ),
    QualityFindingCode.ENTRY_POINTS_PRESENT: _text(
        QualityCategory.ONBOARDING,
        QualitySeverity.INFO,
        "Entry points are present",
        "One or more reliable application entry points were detected.",
        "Keep entry points documented for new contributors.",
    ),
    QualityFindingCode.ENVIRONMENT_EXAMPLE_PRESENT: _text(
        QualityCategory.ONBOARDING,
        QualitySeverity.INFO,
        "Environment example is present",
        "An example environment file was detected.",
        "Keep example variables safe and aligned with documented configuration.",
    ),
    QualityFindingCode.LOCKFILE_MISSING: _text(
        QualityCategory.ONBOARDING,
        QualitySeverity.LOW,
        "Lockfile is missing",
        "A dependency manifest was detected without a recognized lockfile.",
        "Consider committing the ecosystem's lockfile for reproducible setup.",
    ),
    QualityFindingCode.LOCKFILE_PRESENT: _text(
        QualityCategory.ONBOARDING,
        QualitySeverity.INFO,
        "Lockfile is present",
        "A recognized dependency lockfile was detected.",
        "Update dependency declarations and lockfiles together.",
    ),
    QualityFindingCode.DEVELOPMENT_SETUP_PRESENT: _text(
        QualityCategory.ONBOARDING,
        QualitySeverity.INFO,
        "Development setup guidance is present",
        "Reliable setup documentation or contributor guidance was detected.",
        "Keep development setup guidance tested and current.",
    ),
}

POSITIVE_FINDING_CODES = frozenset(
    {
        QualityFindingCode.DOCUMENTATION_PRESENT,
        QualityFindingCode.TESTS_PRESENT,
        QualityFindingCode.TEST_CONFIGURATION_PRESENT,
        QualityFindingCode.TEST_CI_INTEGRATION_PRESENT,
        QualityFindingCode.LICENSE_PRESENT,
        QualityFindingCode.CONTRIBUTING_PRESENT,
        QualityFindingCode.SECURITY_POLICY_PRESENT,
        QualityFindingCode.COMMUNITY_FILES_PRESENT,
        QualityFindingCode.CI_PRESENT,
        QualityFindingCode.DEPENDENCY_UPDATE_AUTOMATION_PRESENT,
        QualityFindingCode.CONTAINER_SETUP_PRESENT,
        QualityFindingCode.STRUCTURE_ANALYSIS_SUCCESSFUL,
        QualityFindingCode.ENTRY_POINTS_PRESENT,
        QualityFindingCode.ENVIRONMENT_EXAMPLE_PRESENT,
        QualityFindingCode.LOCKFILE_PRESENT,
        QualityFindingCode.DEVELOPMENT_SETUP_PRESENT,
    }
)


def validate_quality_path(value: str) -> str:
    """Return one bounded repository-relative POSIX path or fail."""
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > MAX_QUALITY_PATH_LENGTH
        or path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("unsafe quality path")
    return value


def normalized_heading(value: str) -> str:
    """Normalize a bounded Markdown heading into a non-persisted signal."""
    folded = value.casefold().strip()
    folded = re.sub(r"[`*_~\[\]():.!?/#-]+", " ", folded)
    return " ".join(folded.split())[:100]


def is_ci_path(relative_path: str) -> bool:
    """Return whether a path is a recognized CI configuration."""
    folded = relative_path.casefold()
    path = PurePosixPath(folded)
    return folded in CI_EXACT_PATHS or (
        len(path.parts) >= 3
        and path.parts[:2] == (".github", "workflows")
        and path.suffix in {".yml", ".yaml"}
    )
