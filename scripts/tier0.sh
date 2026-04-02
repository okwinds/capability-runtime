#!/usr/bin/env bash
set -euo pipefail

python -m pytest \
  tests/test_public_api_exports.py \
  tests/test_public_repo_hygiene.py \
  tests/test_repo_no_deep_imports_in_user_facing_docs.py \
  tests/test_docs_scheme2_no_skilladapter_residue.py \
  tests/test_docs_pinned_dependency_versions.py \
  tests/test_bilingual_docs_surface.py \
  tests/test_release_tag_version_guardrail.py \
  tests/test_examples_smoke.py \
  tests/test_coding_agent_examples_atomic.py \
  tests/test_coding_agent_examples_recipes.py \
  -q
