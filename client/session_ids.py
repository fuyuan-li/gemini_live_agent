from __future__ import annotations

import pathlib
import secrets
import socket
from urllib.parse import urlparse, urlunparse


DEFAULT_WS_ROOT_URL = "ws://127.0.0.1:8000/ws/local_user"


def get_stable_user_id() -> str:
    """
    Return a stable, unique user ID for this machine.

    On first call the ID is generated from the hostname + 4 random hex bytes
    and persisted to ~/.config/companion-agent/user_id so every subsequent
    launch on the same Mac gets the same ID.  This lets the server distinguish
    users without requiring any sign-in.

    Example: "macbook-pro_a3f29c1b"
    """
    config_dir = pathlib.Path.home() / ".config" / "companion-agent"
    id_file = config_dir / "user_id"
    if id_file.exists():
        uid = id_file.read_text().strip()
        if uid:
            return uid
    # Build from hostname (stripped to safe chars) + random suffix
    raw_host = socket.gethostname().split(".")[0]
    hostname = "".join(c for c in raw_host.lower() if c.isalnum() or c == "-")[:20]
    uid = f"{hostname}_{secrets.token_hex(4)}"
    config_dir.mkdir(parents=True, exist_ok=True)
    id_file.write_text(uid)
    return uid


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
