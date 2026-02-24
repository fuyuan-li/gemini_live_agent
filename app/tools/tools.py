import webbrowser
from urllib.parse import urlparse


def open_url(url: str) -> dict:
    """
    Open a URL in the user's default browser on this machine.

    Args:
      url: The URL to open. If scheme is missing, https:// will be assumed.

    Returns:
      A dict with success status.
    """
    url = url.strip()
    if not url:
        return {"ok": False, "error": "Empty URL"}

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url

    ok = webbrowser.open(url, new=2)  # new=2 -> new tab if possible
    return {"ok": bool(ok), "opened": url}