from __future__ import annotations

import pytest

from agently_skills_runtime.host_toolkit.approvals_profiles import ApprovalsProfile, validate_approvals_profile


def test_validate_approvals_profile_accepts_valid_values():
    profile = ApprovalsProfile(name="ok", approval_timeout_ms=60_000, max_wall_time_sec=600, buffer_ms=60_000)
    validate_approvals_profile(profile=profile)


def test_validate_approvals_profile_rejects_when_approval_timeout_exceeds_wall_time_minus_buffer():
    profile = ApprovalsProfile(name="bad", approval_timeout_ms=600_000, max_wall_time_sec=600, buffer_ms=60_000)
    with pytest.raises(ValueError, match="approval_timeout_ms"):
        validate_approvals_profile(profile=profile)

