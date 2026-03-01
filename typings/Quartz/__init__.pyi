from typing import Protocol

class _CGSize(Protocol):
    width: float
    height: float

class _CGRect(Protocol):
    size: _CGSize


def CGMainDisplayID() -> int: ...
def CGDisplayBounds(display_id: int) -> _CGRect: ...
