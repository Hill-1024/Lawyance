"""Explicit remote retrieval must bypass every local hybrid path."""

import builtins
from contextlib import contextmanager
import json
import os
from unittest import mock

import pytest
import requests

from mcp import law_service_client, legal_search_router, pkulaw_client


REMOTE_ENV = {
    "LAWVER_LAW_SOURCE": "remote",
    "LAWVER_LAW_SERVICE_URL": "https://law.example.test",
    "LAWVER_LAW_SERVICE_KEY": "lvk_routing-test",
    "LAWVER_LAW_SERVICE_TIMEOUT": "10",
    "LAWVER_VECTOR_DB_ENABLED": "1",
    "LAWVER_VECTOR_RETRIEVAL_ENABLED": "1",
    "PKU_LAW_SOURCE": "remote",
}
ARTICLE = {
    "law_name": "Routing Test Law",
    "article_number": "1",
    "content": "Remote routing test provision.",
    "url": "https://example.test/law/1",
}


class Response:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self.body = json.dumps(payload).encode("utf-8")
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        self.closed = True


@contextmanager
def forbid_local_retrieval():
    """Record even forbidden imports swallowed by hybrid's fallback handler."""
    attempted = []
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"RAG", "vector_store"}:
            attempted.append(name)
            raise ImportError("local retrieval is absent from the customer package")
        return original_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=guarded_import), mock.patch.object(
        legal_search_router, "_hybrid_search_article",
        wraps=legal_search_router._hybrid_search_article,
    ) as hybrid, mock.patch.object(
        pkulaw_client, "_local_search_engine",
        side_effect=AssertionError("remote retrieval fell back to local data"),
    ) as local:
        yield
        hybrid.assert_not_called()
        local.assert_not_called()
        assert attempted == []


def test_remote_search_bypasses_enabled_hybrid_and_calls_only_remote():
    response = Response({"success": True, "data": [ARTICLE]})
    with mock.patch.dict(os.environ, REMOTE_ENV), forbid_local_retrieval(), mock.patch.object(
        law_service_client.requests.Session, "post", return_value=response,
    ) as post:
        result = json.loads(legal_search_router.search_article("contract", jurisdiction="中国"))

    assert result["success"] is True
    assert ARTICLE["content"] in result["result"]
    assert ARTICLE["url"] in result["result"]
    post.assert_called_once_with(
        "https://law.example.test/v1/laws/search",
        json={"query": "contract", "limit": 5},
        headers={"Authorization": "Bearer lvk_routing-test", "Accept": "application/json"},
        timeout=(3.0, 10.0), allow_redirects=False, stream=True,
    )
    assert response.closed


@pytest.mark.parametrize("failure, attempts", [("unauthorized", 1), ("unavailable", 2), ("timeout", 2), ("no_match", 1)])
def test_remote_failures_never_fall_back_to_hybrid(failure, attempts):
    responses = []
    if failure == "timeout":
        effect = [requests.Timeout(), requests.Timeout()]
    else:
        status = {"unauthorized": 401, "unavailable": 503, "no_match": 200}[failure]
        responses = [Response({"success": False, "message": "no match"}, status) for _ in range(attempts)]
        effect = responses
    with mock.patch.dict(os.environ, REMOTE_ENV), forbid_local_retrieval(), mock.patch.object(
        law_service_client.requests.Session, "post", side_effect=effect,
    ) as post:
        result = json.loads(legal_search_router.search_article("contract"))

    assert result["success"] is False
    assert result.get("message")
    assert post.call_count == attempts
    assert all(response.closed for response in responses)


def test_invalid_explicit_source_reports_error_without_importing_hybrid():
    with mock.patch.dict(os.environ, {**REMOTE_ENV, "LAWVER_LAW_SOURCE": "invalid"}), forbid_local_retrieval(), mock.patch.object(
        law_service_client.requests.Session, "post",
    ) as post:
        result = json.loads(legal_search_router.search_article("contract"))
    assert result["success"] is False
    assert "LAWVER_LAW_SOURCE" in result["message"]
    post.assert_not_called()


@pytest.mark.parametrize("source", ["", "local"])
def test_default_and_explicit_local_still_prefer_hybrid(source):
    hybrid_result = json.dumps({"success": True, "result": "hybrid provision"})
    with mock.patch.dict(os.environ, {**REMOTE_ENV, "LAWVER_LAW_SOURCE": source}), mock.patch.object(
        legal_search_router, "_hybrid_search_article", return_value=hybrid_result,
    ) as hybrid, mock.patch.object(legal_search_router, "china_search_article") as legacy:
        assert legal_search_router.search_article("contract") == hybrid_result
    hybrid.assert_called_once_with("contract")
    legacy.assert_not_called()


@pytest.mark.parametrize("source", ["", "local"])
def test_local_still_falls_back_when_hybrid_has_no_result(source):
    legacy_result = json.dumps({"success": True, "result": "legacy provision"})
    with mock.patch.dict(os.environ, {**REMOTE_ENV, "LAWVER_LAW_SOURCE": source}), mock.patch.object(
        legal_search_router, "_hybrid_search_article", return_value=None,
    ) as hybrid, mock.patch.object(
        legal_search_router, "china_search_article", return_value=legacy_result,
    ) as legacy:
        assert legal_search_router.search_article("contract") == legacy_result
    hybrid.assert_called_once_with("contract")
    legacy.assert_called_once_with("contract")
