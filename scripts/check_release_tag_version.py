from __future__ import annotations

"""Guardrail: ensure release tag matches package version metadata."""

import argparse
import re
import sys
from pathlib import Path


_VERSION_RE = re.compile(r'(?m)^version\s*=\s*"(?P<version>[^"]+)"\s*$')
_MODULE_VERSION_RE = re.compile(r'(?m)^__version__\s*=\s*"(?P<version>[^"]+)"\s*$')


def normalize_tag(tag: str) -> str:
    """Normalize a git tag like `v0.0.7` to `0.0.7`."""

    cleaned = tag.strip()
    if cleaned.startswith("refs/tags/"):
        cleaned = cleaned.removeprefix("refs/tags/")
    if cleaned.startswith("v"):
        cleaned = cleaned[1:]
    if not cleaned:
        raise ValueError("release tag is empty")
    return cleaned


def read_pyproject_version(pyproject_path: Path) -> str:
    """Read `[project].version` from `pyproject.toml` using a simple regex."""

    text = pyproject_path.read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    if not match:
        raise ValueError(f"could not find version in {pyproject_path}")
    return str(match.group("version"))


def read_module_version(init_path: Path) -> str:
    """Read `__version__` from `src/capability_runtime/__init__.py`."""

    text = init_path.read_text(encoding="utf-8")
    match = _MODULE_VERSION_RE.search(text)
    if not match:
        raise ValueError(f"could not find __version__ in {init_path}")
    return str(match.group("version"))


def validate_versions(*, release_tag: str, pyproject_path: Path, init_path: Path) -> tuple[str, str, str]:
    """Return normalized values after verifying all version sources match."""

    tag_version = normalize_tag(release_tag)
    pyproject_version = read_pyproject_version(pyproject_path)
    module_version = read_module_version(init_path)
    versions = {
        "tag": tag_version,
        "pyproject": pyproject_version,
        "module": module_version,
    }
    if len(set(versions.values())) != 1:
        raise ValueError(
            "release version mismatch: "
            f"tag={tag_version}, pyproject={pyproject_version}, module={module_version}"
        )
    return tag_version, pyproject_version, module_version


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="release tag, for example v0.0.7")
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="path to pyproject.toml",
    )
    parser.add_argument(
        "--module-init",
        default="src/capability_runtime/__init__.py",
        help="path to capability_runtime/__init__.py",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        tag_version, pyproject_version, module_version = validate_versions(
            release_tag=str(args.tag),
            pyproject_path=Path(str(args.pyproject)),
            init_path=Path(str(args.module_init)),
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        "Release guard passed: "
        f"tag={tag_version}, pyproject={pyproject_version}, module={module_version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
