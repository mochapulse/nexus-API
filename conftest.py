"""Shared pytest fixtures for the nexus-API test suite.

This file lives at the project root so ``pytest`` prepends the root
directory to ``sys.path`` (default ``prepend`` import mode), making the
``api`` package importable from the ``api/test`` test modules.
"""

import pytest
from fastapi.testclient import TestClient

import api.config.runtime as runtime
from api.main import app

TEST_API_KEY = "test-api-key-123"


@pytest.fixture(autouse=True)
def _api_key():
    """Pin a known API key so auth behavior is deterministic in every test."""
    runtime.API_KEY = TEST_API_KEY
    yield
    runtime.API_KEY = TEST_API_KEY


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {"X-API-Key": TEST_API_KEY}
