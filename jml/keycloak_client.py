"""
Keycloak Admin REST API Client with session pooling, token caching, exponential retries, and strict secret masking.
"""

import time
import urllib.parse
from typing import Any, Dict, List, Optional, Union
import requests
from requests.exceptions import ConnectionError, Timeout, RequestException


class KeycloakAPIError(Exception):
    """Custom exception for Keycloak REST API errors without leaking secrets."""

    def __init__(self, status_code: Optional[int], endpoint: str, message: str):
        self.status_code = status_code
        self.endpoint = endpoint
        self.message = message
        super().__init__(f"Keycloak API Error [{status_code or 'CONN'}] at {endpoint}: {message}")


class KeycloakAdmin:
    def __init__(
        self,
        base_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
        session: Optional[requests.Session] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        authenticated: bool = True,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        req_headers = headers.copy() if headers else {}

        if authenticated:
            token = self.get_token()
            req_headers["Authorization"] = f"Bearer {token}"

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    json=json,
                    data=data,
                    headers=req_headers,
                    params=params,
                    timeout=self.timeout,
                )

                # Never retry on 4xx client errors
                if 400 <= resp.status_code < 500:
                    try:
                        err_json = resp.json()
                        msg = err_json.get("errorMessage") or err_json.get("error_description") or resp.text
                    except Exception:
                        msg = resp.text
                    raise KeycloakAPIError(
                        status_code=resp.status_code,
                        endpoint=path,
                        message=f"Client error ({resp.status_code}): {msg[:200]}",
                    )

                # Retry on 5xx server errors
                if 500 <= resp.status_code < 600:
                    if attempt <= self.max_retries:
                        time.sleep(self.backoff_factor * (2 ** (attempt - 1)))
                        continue
                    else:
                        raise KeycloakAPIError(
                            status_code=resp.status_code,
                            endpoint=path,
                            message=f"Server error ({resp.status_code}) after {self.max_retries} retries",
                        )

                # 2xx / 3xx Success
                return resp

            except (ConnectionError, Timeout) as exc:
                if attempt <= self.max_retries:
                    time.sleep(self.backoff_factor * (2 ** (attempt - 1)))
                    continue
                else:
                    raise KeycloakAPIError(
                        status_code=None,
                        endpoint=path,
                        message=f"Network connectivity failure after {self.max_retries} retries: {str(exc)}",
                    )
            except KeycloakAPIError:
                raise
            except Exception as exc:
                raise KeycloakAPIError(
                    status_code=None,
                    endpoint=path,
                    message=f"Unexpected error: {str(exc)}",
                )

    def get_token(self) -> str:
        """Obtains and caches client credentials access token."""
        now = time.time()
        if self._token and now < (self._token_expires_at - 30):
            return self._token

        token_path = f"/realms/{self.realm}/protocol/openid-connect/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        resp = self._request(
            method="POST",
            path=token_path,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            authenticated=False,
        )

        data = resp.json()
        self._token = data["access_token"]
        expires_in = data.get("expires_in", 300)
        self._token_expires_at = now + expires_in
        return self._token

    def find_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Finds user by exact username."""
        path = f"/admin/realms/{self.realm}/users"
        resp = self._request("GET", path, params={"username": username, "exact": "true"})
        users = resp.json()
        if isinstance(users, list):
            for u in users:
                if u.get("username", "").lower() == username.lower():
                    return u
        return None

    def create_user(self, payload: Dict[str, Any]) -> str:
        """Creates a new user and returns the Keycloak user_id."""
        path = f"/admin/realms/{self.realm}/users"
        resp = self._request("POST", path, json=payload)

        # Extract user ID from Location header if available
        location = resp.headers.get("Location") or resp.headers.get("location")
        if location:
            user_id = location.rstrip("/").split("/")[-1]
            return user_id

        # Fallback: search for user ID by username
        username = payload.get("username")
        if username:
            created = self.find_user(username)
            if created and "id" in created:
                return created["id"]

        raise KeycloakAPIError(
            status_code=resp.status_code,
            endpoint=path,
            message="User created but failed to extract user ID from response header or search.",
        )

    def set_temp_password(self, user_id: str, password: str) -> None:
        """Sets temporary initial password with required action UPDATE_PASSWORD."""
        path = f"/admin/realms/{self.realm}/users/{user_id}/reset-password"
        payload = {
            "type": "password",
            "value": password,
            "temporary": True,
        }
        self._request("PUT", path, json=payload)

    def get_role(self, role_name: str) -> Dict[str, Any]:
        """Fetches realm role representation by name."""
        encoded_name = urllib.parse.quote(role_name)
        path = f"/admin/realms/{self.realm}/roles/{encoded_name}"
        resp = self._request("GET", path)
        return resp.json()

    def user_roles(self, user_id: str) -> List[Dict[str, Any]]:
        """Returns list of realm roles currently assigned to the user."""
        path = f"/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm"
        resp = self._request("GET", path)
        return resp.json()

    def add_roles(self, user_id: str, roles: List[Dict[str, Any]]) -> None:
        """Assigns realm roles to user."""
        if not roles:
            return
        path = f"/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm"
        self._request("POST", path, json=roles)

    def remove_roles(self, user_id: str, roles: List[Dict[str, Any]]) -> None:
        """Revokes realm roles from user."""
        if not roles:
            return
        path = f"/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm"
        self._request("DELETE", path, json=roles)

    def update_user(self, user_id: str, payload: Dict[str, Any]) -> None:
        """Updates user profile and attributes (fetches existing, merges, and PUTs)."""
        get_path = f"/admin/realms/{self.realm}/users/{user_id}"
        existing = self._request("GET", get_path).json()

        merged = existing.copy()
        for k, v in payload.items():
            if k == "attributes" and isinstance(v, dict):
                attrs = merged.get("attributes", {}).copy()
                attrs.update(v)
                merged["attributes"] = attrs
            else:
                merged[k] = v

        self._request("PUT", get_path, json=merged)

    def logout_user(self, user_id: str) -> None:
        """Revokes all active sessions for user."""
        path = f"/admin/realms/{self.realm}/users/{user_id}/logout"
        self._request("POST", path)
