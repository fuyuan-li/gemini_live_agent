from __future__ import annotations

import secrets
from urllib.parse import urlparse, urlunparse


DEFAULT_WS_ROOT_URL = "ws://127.0.0.1:8000/ws/local_user"


def generate_session_id() -> str:
    return f"local_session_{secrets.token_hex(6)}"


def normalize_ws_root_url(ws_url: str) -> str:
    parsed = urlparse(ws_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        new_path = "/" + "/".join(parts[:2])
    else:
        new_path = parsed.path or "/ws/local_user"
    return urlunparse(parsed._replace(path=new_path))


def build_ws_session_url(ws_root_url: str, session_id: str) -> str:
    parsed = urlparse(ws_root_url)
    base_parts = [part for part in parsed.path.split("/") if part]
    path = "/" + "/".join([*base_parts, str(session_id)])
    return urlunparse(parsed._replace(path=path))
