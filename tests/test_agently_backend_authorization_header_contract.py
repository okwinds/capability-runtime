from __future__ import annotations

import agently

from capability_runtime.adapters.agently_backend import (
    build_openai_compatible_requester_factory,
    build_openai_responses_compatible_requester_factory,
)


def test_openai_compatible_requester_keeps_preconfigured_authorization_header() -> None:
    """
    OpenAICompatible 路径不得在已有 Authorization header 时由 bridge 覆盖鉴权事实。
    """

    agent = agently.Agently.create_agent("auth-openai-compatible")
    agent.settings.set(
        "plugins.ModelRequester.OpenAICompatible.headers",
        {"Authorization": "Bearer existing-token"},
    )
    agent.settings.set("plugins.ModelRequester.OpenAICompatible.auth", {"api_key": "new-token"})

    requester = build_openai_compatible_requester_factory(agently_agent=agent)()
    request_data = requester.generate_request_data()

    assert request_data.headers["Authorization"] == "Bearer existing-token"


def test_openai_responses_requester_keeps_preconfigured_authorization_header() -> None:
    """
    OpenAIResponsesCompatible 路径不得在已有 Authorization header 时由 bridge 覆盖鉴权事实。
    """

    agent = agently.Agently.create_agent("auth-openai-responses")
    agent.settings.set(
        "plugins.ModelRequester.OpenAIResponsesCompatible.headers",
        {"Authorization": "Bearer existing-token"},
    )
    agent.settings.set("plugins.ModelRequester.OpenAIResponsesCompatible.auth", {"api_key": "new-token"})

    requester = build_openai_responses_compatible_requester_factory(agently_agent=agent)()
    request_data = requester.generate_request_data()
    headers = requester._build_headers_with_auth(request_data)  # noqa: SLF001 - upstream contract probe

    assert headers["Authorization"] == "Bearer existing-token"
