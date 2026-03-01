from __future__ import annotations

import threading
from typing import Optional

import AppKit  # type: ignore
import Foundation  # type: ignore
import objc  # type: ignore


class _MacDotView(AppKit.NSView):  # type: ignore[misc, valid-type]
    def initWithFrame_radius_(self, frame, radius: int):
        self = objc.super(_MacDotView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._radius = int(radius)
        return self

    def isOpaque(self):
        return False

    def drawRect_(self, rect):
        AppKit.NSColor.clearColor().set()
        AppKit.NSRectFill(rect)
        AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.88, 0.30, 0.95).set()
        size = self._radius * 2
        dot_rect = AppKit.NSMakeRect(2, 2, size - 4, size - 4)
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(dot_rect).fill()


class ScreenDotOverlay:
    """
    Native macOS overlay that renders a small transparent floating dot.
    """

    def __init__(
        self,
        radius: int = 10,
        visible: bool = True,
    ) -> None:
        self.radius = int(max(4, radius))
        self._visible = bool(visible)

        self._window = None
        self._view = None
        self._app = None
        self._screen_h: Optional[int] = None
        self._last_error: Optional[str] = None
        self._running = False
        self._x = 0
        self._y = 0

    def start(self) -> bool:
        if threading.current_thread() is not threading.main_thread():
            self._last_error = "native mac overlay must run on main thread"
            return False

        try:
            self._app = AppKit.NSApplication.sharedApplication()
            size = self.radius * 2
            rect = AppKit.NSMakeRect(0, 0, size, size)

            window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                rect,
                AppKit.NSWindowStyleMaskBorderless,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            window.setReleasedWhenClosed_(False)
            window.setOpaque_(False)
            window.setBackgroundColor_(AppKit.NSColor.clearColor())
            window.setHasShadow_(False)
            window.setIgnoresMouseEvents_(True)
            window.setLevel_(AppKit.NSScreenSaverWindowLevel)
            window.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            )

            view = _MacDotView.alloc().initWithFrame_radius_(rect, self.radius)
            window.setContentView_(view)

            if self._visible:
                window.orderFrontRegardless()
            else:
                window.orderOut_(None)

            main_screen = AppKit.NSScreen.mainScreen()
            if main_screen is not None:
                self._screen_h = int(main_screen.frame().size.height)

            self._window = window
            self._view = view
            self._running = True
            self._last_error = None
            return True
        except Exception as exc:
            self._last_error = str(exc)
            self._running = False
            return False

    def stop(self) -> None:
        if self._window is not None:
            try:
                self._window.orderOut_(None)
                self._window.close()
            except Exception:
                pass
        self._window = None
        self._view = None
        self._running = False

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        if not self._running or self._window is None:
            return
        try:
            if self._visible:
                self._window.orderFrontRegardless()
            else:
                self._window.orderOut_(None)
        except Exception as exc:
            self._last_error = str(exc)

    def toggle_visible(self) -> bool:
        self.set_visible(not self._visible)
        return self._visible

    def update_position(self, x: int, y: int) -> None:
        self._x = int(x)
        self._y = int(y)
        if not self._running or self._window is None:
            return
        try:
            if self._screen_h is None:
                main_screen = AppKit.NSScreen.mainScreen()
                if main_screen is not None:
                    self._screen_h = int(main_screen.frame().size.height)

            origin_x = int(self._x - self.radius)
            if self._screen_h is not None:
                origin_y = int(self._screen_h - self._y - self.radius)
            else:
                origin_y = int(self._y - self.radius)
            self._window.setFrameOrigin_((origin_x, origin_y))
            if self._view is not None:
                self._view.setNeedsDisplay_(True)
            self.pump()
        except Exception as exc:
            self._last_error = str(exc)

    def pump(self) -> None:
        if not self._running or self._app is None:
            return
        try:
            while True:
                event = self._app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                    AppKit.NSEventMaskAny,
                    Foundation.NSDate.dateWithTimeIntervalSinceNow_(0),
                    Foundation.NSDefaultRunLoopMode,
                    True,
                )
                if event is None:
                    break
                self._app.sendEvent_(event)
            self._app.updateWindows()
        except Exception:
            pass

    def get_last_error(self) -> Optional[str]:
        return self._last_error
