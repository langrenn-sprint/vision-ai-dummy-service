"""Nox sessions."""

import sys

import nox
from nox_poetry import Session, session

package = "vision-ai-dummy-service"
locations = "vision_ai_dummy_service", "tests", "noxfile.py"
nox.options.envdir = ".cache"
nox.options.reuse_existing_virtualenvs = True
nox.options.stop_on_first_error = True
nox.options.sessions = (
    "lint",
    "mypy",
    "black",
    "safety",
    "docker_build",
)


@session(python=["3.11"])
def clean(session: Session) -> None:
    """Clean the project."""
    session.run(
        "py3clean",
        ".",
        external=True,
    )
    session.run(
        "rm",
        "-rf",
        ".cache",
        external=True,
    )
    session.run(
        "rm",
        "-rf",
        ".pytest_cache",
        external=True,
    )
    session.run(
        "rm",
        "-rf",
        ".pytype",
        external=True,
    )
    session.run(
        "rm",
        "-rf",
        "dist",
        external=True,
    )
    session.run(
        "rm",
        "-rf",
        ".mypy_cache",
        external=True,
    )
    session.run(
        "rm",
        "-f",
        ".coverage",
        external=True,
    )


@session(python=["3.11"])
def docker_build(session: Session) -> None:
    """Build the Docker image."""
    session.run(
        "docker", "build", "-t", "ghcr.io/langrenn-sprint/vision-ai-dummy-service:test", "."
    )


@session(python=["3.11"])
def black(session: Session) -> None:
    """Run black code formatter."""
    args = session.posargs or locations
    session.install("black")
    session.run("black", *args)


@session(python=["3.11"])
def lint(session: Session) -> None:
    """Lint using flake8."""
    args = session.posargs or locations
    session.install(
        "flake8",
        "flake8-annotations",
        "flake8-bandit",
        "flake8-black",
        "flake8-bugbear",
        "flake8-docstrings",
        "flake8-import-order",
        "darglint",
        "flake8-assertive",
    )
    session.run("flake8", *args)


@session(python=["3.11"])
def safety(session: Session) -> None:
    """Scan dependencies for insecure packages."""
    requirements = session.poetry.export_requirements()
    session.install("safety")
    session.run(
        "safety",
        "check",
        "--full-report",
        f"--file={requirements}",
        "--ignore=70612,71670",  # TODO: Should be removed when jinja2 vulnerability is fixed
    )


@session(python=["3.11"])
def mypy(session: Session) -> None:
    """Type-check using mypy."""
    args = session.posargs or [
        "--install-types",
        "--non-interactive",
        "vision_ai_dummy_service",
        "tests",
    ]
    session.install(".")
    session.install("mypy", "pytest")
    session.run("mypy", *args)
    if not session.posargs:
        session.run("mypy", f"--python-executable={sys.executable}", "noxfile.py")
