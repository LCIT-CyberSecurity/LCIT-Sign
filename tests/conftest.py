from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

_MOCK_OIDC_BASE_URL = "http://127.0.0.1:8099"


class _ServerThread(threading.Thread):
    def __init__(self, app, host: str, port: int) -> None:
        super().__init__(daemon=True)
        self.config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self.server = uvicorn.Server(self.config)

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True


@pytest.fixture(scope="session")
def mock_oidc_base_url() -> Iterator[str]:
    """Run the real mock OIDC provider app on a loopback port for the whole
    test session, so the OIDC client code (discovery, PKCE, token exchange,
    JWKS signature validation) is exercised end-to-end rather than stubbed.
    """
    os.environ["MOCK_OIDC_ISSUER"] = _MOCK_OIDC_BASE_URL
    os.environ["MOCK_OIDC_PUBLIC_BASE_URL"] = _MOCK_OIDC_BASE_URL
    import app as mock_oidc_app  # mock_oidc/app.py, added to pythonpath

    thread = _ServerThread(mock_oidc_app.app, "127.0.0.1", 8099)
    thread.start()
    for _ in range(100):
        if thread.server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("mock OIDC server did not start in time")

    yield _MOCK_OIDC_BASE_URL

    thread.stop()
    thread.join(timeout=5)
