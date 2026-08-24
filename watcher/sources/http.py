from __future__ import annotations

from typing import Any

import requests


class BlockedResponse(RuntimeError):
    pass


class BrowserLikeClient:
    """Low-frequency HTTP client with curl_cffi fallback on blocking."""

    def __init__(self, headers: dict[str, str], timeout: float = 10.0) -> None:
        self.headers = headers
        self.timeout = timeout
        self.session = requests.Session()
        self._impersonated: Any | None = None

    @staticmethod
    def _looks_blocked(status: int, text: str) -> bool:
        # 429는 종료 조건이 아니라 "지문을 바꿔 다시 시도하라"는 신호다. 네이버는
        # 평범한 requests TLS 지문에 곧바로 429를 돌려주고, 브라우저 지문으로는
        # 같은 IP에서도 정상 응답한다.
        lowered = text[:10000].lower()
        return status in {403, 429, 503} or "captcha" in lowered or "자동입력" in lowered

    def _impersonated_session(self) -> Any:
        if self._impersonated is None:
            from curl_cffi import requests as curl_requests

            self._impersonated = curl_requests.Session(impersonate="chrome")
        return self._impersonated

    def _retry_with_impersonation(self, method: str, url: str, **kwargs: Any) -> Any:
        session = self._impersonated_session()
        return getattr(session, method)(url, headers=self.headers, timeout=self.timeout, **kwargs)

    def prime(self, url: str) -> None:
        """브라우저 지문 세션으로 페이지를 한 번 열어 세션 쿠키를 받아둔다.

        일부 엔드포인트는 페이지 방문으로 발급되는 쿠키가 없으면 429를 돌려준다.
        """
        session = self._impersonated_session()
        session.get(url, headers={**self.headers, "Accept": "text/html"}, timeout=self.timeout)

    @staticmethod
    def _json(response: Any, url: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"non-JSON response from {url}") from exc

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(url, params=params, headers=self.headers, timeout=self.timeout)
        if self._looks_blocked(response.status_code, response.text):
            response = self._retry_with_impersonation("get", url, params=params)
        if self._looks_blocked(response.status_code, response.text):
            raise BlockedResponse(f"blocked by {url} (HTTP {response.status_code})")
        response.raise_for_status()
        return self._json(response, url)

    def post_json(self, url: str, payload: dict[str, Any]) -> Any:
        headers = {**self.headers, "Content-Type": "application/json"}
        response = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
        if self._looks_blocked(response.status_code, response.text):
            response = self._retry_with_impersonation("post", url, json=payload)
        if self._looks_blocked(response.status_code, response.text):
            raise BlockedResponse(f"blocked by {url} (HTTP {response.status_code})")
        response.raise_for_status()
        return self._json(response, url)

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        response = self.session.get(url, params=params, headers=self.headers, timeout=self.timeout)
        if self._looks_blocked(response.status_code, response.text):
            response = self._retry_with_impersonation("get", url, params=params)
        if self._looks_blocked(response.status_code, response.text):
            raise BlockedResponse(f"blocked by {url} (HTTP {response.status_code})")
        response.raise_for_status()
        return response.text

