from __future__ import annotations

import asyncio
import subprocess


async def speak_text_locally(text: str) -> dict:
    """Speak text aloud using macOS built-in say command."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: subprocess.run(["say", text]))
    return {"ok": True}
