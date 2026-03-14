from __future__ import annotations

import argparse
import asyncio

import AppKit  # type: ignore
import Foundation  # type: ignore
import cv2  # type: ignore
import objc  # type: ignore

from app.runtime import browser_runtime
from client.companion_runtime import CompanionRuntime
from client.companion_state import CompanionState, EventEntry
from client.cursor.displays import get_builtin_display_geometry
from client.cursor.mapper import get_main_display_size
from client.cursor.provider import HandCursorProvider
from client.session_ids import DEFAULT_WS_ROOT_URL, generate_session_id, get_stable_user_id, normalize_ws_root_url


def _get_builtin_nsscreen():
    """
    Return the NSScreen for the Mac's built-in display.
    Falls back to mainScreen() if no built-in display is detected.
    """
    try:
        import Quartz  # type: ignore

        geom = get_builtin_display_geometry()
        for screen in AppKit.NSScreen.screens():
            desc = screen.deviceDescription()
            sid = desc.get("NSScreenNumber")
            if sid is not None and int(sid) == geom.display_id:
                return screen
    except Exception:
        pass
    return AppKit.NSScreen.mainScreen()


# Cloud Run base URL — no user_id suffix; it is appended automatically.
DEFAULT_WS_BASE = "wss://adk-agent-orchestrator-385929302643.us-central1.run.app/ws"

PANEL_W = 380  # sidebar width in points

HEADER_H = 50
AGENT_H = 70
WEBCAM_H = int(PANEL_W * 9 / 16)  # ≈ 213px for 16:9 aspect ratio
CALIB_H = 28
BUTTON_H = 44
DEBUG_H = 150
LOG_BOTTOM = BUTTON_H + DEBUG_H + 4  # y of conversation log bottom edge
TOP_FIXED = HEADER_H + AGENT_H + WEBCAM_H + CALIB_H + 8  # height consumed at top


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Native macOS companion window for the live voice agent")
    p.add_argument("--ws-url", default=DEFAULT_WS_BASE,
                   help="WebSocket base URL up to and including /ws (user-id appended automatically)")
    p.add_argument("--user-id", default=None,
                   help="Stable user ID for this machine (auto-generated from hostname on first run)")
    p.add_argument("--camera-index", type=int, default=0)
    p.add_argument("--hand-smoothing", type=float, default=0.35)
    p.add_argument("--cursor-stale-ms", type=int, default=400)
    p.add_argument("--cursor-send-hz", type=float, default=20.0)
    p.add_argument("--hand-overlay", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--hand-overlay-radius", type=int, default=10)
    p.add_argument("--hand-mirror", action=argparse.BooleanOptionalAction, default=True)
    return p


def _make_label(frame, text: str, *, font_size: float = 12.0, bold: bool = False, color=None):
    label = AppKit.NSTextField.alloc().initWithFrame_(frame)
    label.setStringValue_(text)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setBordered_(False)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    font = AppKit.NSFont.boldSystemFontOfSize_(font_size) if bold else AppKit.NSFont.systemFontOfSize_(font_size)
    label.setFont_(font)
    if color is not None:
        label.setTextColor_(color)
    return label


def _ns_image_from_bgr(frame):
    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        return None
    payload = encoded.tobytes()
    data = Foundation.NSData.dataWithBytes_length_(payload, len(payload))
    return AppKit.NSImage.alloc().initWithData_(data)


def _ns_image_from_jpeg(jpeg_bytes: bytes):
    data = Foundation.NSData.dataWithBytes_length_(jpeg_bytes, len(jpeg_bytes))
    return AppKit.NSImage.alloc().initWithData_(data)


def _format_event_log(events: list[EventEntry]) -> str:
    # Collapse consecutive speech events of the same type — streaming sends
    # incremental partials followed by a final complete transcript, so we keep
    # only the last entry in each consecutive run of user_spoke/agent_spoke.
    SPEECH = {"user_spoke", "agent_spoke"}
    collapsed: list[EventEntry] = []
    for e in events:
        if e.event in {"cursor_sent", "cursor_received"}:
            continue
        if collapsed and collapsed[-1].event == e.event and e.event in SPEECH:
            collapsed[-1] = e  # replace partial with newer (longer) version
        else:
            collapsed.append(e)

    lines: list[str] = []
    for e in collapsed:
        if e.event == "session_connected":
            lines.append("─── connected ───")
        elif e.event == "session_disconnected":
            lines.append("─── disconnected ───")
        elif e.event == "session_error":
            lines.append(f"  ✗ {e.summary[:60]}")
        elif e.event == "user_spoke":
            lines.append(f"You: {e.summary}")
        elif e.event == "agent_spoke":
            name = e.agent_name or "Agent"
            lines.append(f"{name}: {e.summary}")
        elif e.event == "agent_started" and e.agent_name:
            lines.append(f"  → {e.agent_name}")
        elif e.tool_name:
            icon = "✓" if e.status == "ok" else "✗"
            lines.append(f"  {icon} {e.tool_name}: {e.summary[:50]}")
    return "\n".join(lines[-40:])


# ---------------------------------------------------------------------------
# Custom NSView for the embedded browser viewport
# ---------------------------------------------------------------------------

class BrowserView(AppKit.NSView):  # type: ignore[misc, valid-type]
    """
    Left-side view that displays headless Playwright frames via CDP screencast
    and forwards mouse events back to the browser.
    """

    def initWithFrame_(self, frame):
        self = objc.super(BrowserView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._owner = None
        self._image_view = AppKit.NSImageView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, frame.size.width, frame.size.height)
        )
        self._image_view.setImageScaling_(AppKit.NSImageScaleAxesIndependently)
        self.addSubview_(self._image_view)
        return self

    def setOwner_(self, owner) -> None:
        self._owner = owner

    # --- Mouse / scroll forwarding ---

    def mouseDown_(self, event) -> None:
        pt = self.convertPoint_fromView_(event.locationInWindow(), None)
        vp_x, vp_y = self._to_viewport(pt)
        if self._owner is not None:
            self._owner.forward_browser_click(vp_x, vp_y)

    def rightMouseDown_(self, event) -> None:
        pass  # ignore right-click

    def scrollWheel_(self, event) -> None:
        pt = self.convertPoint_fromView_(event.locationInWindow(), None)
        vp_x, vp_y = self._to_viewport(pt)
        delta_x = int(event.scrollingDeltaX() * 10)
        delta_y = int(event.scrollingDeltaY() * 10)
        if self._owner is not None:
            self._owner.forward_browser_scroll(vp_x, vp_y, delta_x, delta_y)

    def _to_viewport(self, pt):
        h = self.frame().size.height
        return int(pt.x), int(h - pt.y)  # flip y: NSView y=0 is bottom

    def acceptsFirstMouse_(self, event):
        return True

    def acceptsFirstResponder(self):
        return True

    # --- Frame update (called from tick on main thread) ---

    def update_image(self, jpeg_bytes: bytes) -> None:
        img = _ns_image_from_jpeg(jpeg_bytes)
        if img is not None:
            self._image_view.setImage_(img)

    def show_placeholder(self, text: str = "Browser not started") -> None:
        """Show a text label when no screencast frame is available yet."""
        pass  # NSImageView shows nothing when no image is set — that's fine


# ---------------------------------------------------------------------------
# Bridge (NSObject with selector methods)
# ---------------------------------------------------------------------------

class _ControllerBridge(AppKit.NSObject):  # type: ignore[misc, valid-type]
    def initWithOwner_(self, owner):
        self = objc.super(_ControllerBridge, self).init()
        if self is None:
            return None
        self.owner = owner
        return self

    def tick_(self, timer) -> None:
        self.owner.tick()

    def toggleMute_(self, sender) -> None:
        self.owner.toggle_mute()

    def reconnect_(self, sender) -> None:
        self.owner.request_reconnect()

    def recalibrate_(self, sender) -> None:
        self.owner.recalibrate()

    def toggleDebug_(self, sender) -> None:
        self.owner.toggle_debug()

    def quit_(self, sender) -> None:
        AppKit.NSApp.terminate_(None)

    def windowWillClose_(self, notification) -> None:
        AppKit.NSApp.terminate_(None)


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

class CompanionWindowController:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        user_id = args.user_id or get_stable_user_id()
        full_ws_url = f"{args.ws_url.rstrip('/')}/{user_id}"
        self.ws_root_url = normalize_ws_root_url(full_ws_url)
        self.state = CompanionState(session_id=generate_session_id())
        self.provider = HandCursorProvider(
            camera_index=args.camera_index,
            smoothing=args.hand_smoothing,
            stale_timeout_s=max(0.0, args.cursor_stale_ms / 1000.0),
            tracker_start_timeout_s=8.0,
            mirror=args.hand_mirror,
            preview=True,
            preview_window=False,
            overlay=args.hand_overlay,
            overlay_radius=args.hand_overlay_radius,
        )
        self.runtime = CompanionRuntime(
            ws_url=self.ws_root_url,
            provider=self.provider,
            state=self.state,
            cursor_send_hz=args.cursor_send_hz,
        )
        self.debug_visible = False
        self._bridge = _ControllerBridge.alloc().initWithOwner_(self)
        self._timer = None

        self.window = None
        self.browser_view: BrowserView | None = None
        self.connection_label = None
        self.session_label = None
        self.agent_label = None
        self.tool_label = None
        self.webcam_view = None
        self.calibration_label = None
        self.log_scroll = None
        self.log_text = None
        self.mute_button = None
        self.debug_button = None
        self.debug_scroll = None
        self.debug_text = None
        self._calib_overlay = None  # shown over browser view during calibration

    def start(self) -> None:
        if not self.provider.start():
            raise RuntimeError(f"failed to start cursor provider: {self.provider.status()}")
        self._build_window()
        self._configure_headless_browser()
        self.window.makeKeyAndOrderFront_(None)
        self.recalibrate()
        self.runtime.start()
        self._timer = Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.1,
            self._bridge,
            "tick:",
            None,
            True,
        )

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        self.runtime.stop()
        self.provider.stop()

    def toggle_mute(self) -> None:
        muted = self.runtime.toggle_mute()
        if self.mute_button is not None:
            self.mute_button.setTitle_("Unmute" if muted else "Mute")

    def request_reconnect(self) -> None:
        self.runtime.request_reconnect()

    def recalibrate(self) -> None:
        if self._calib_overlay is not None:
            self._calib_overlay.setHidden_(False)
            # Force immediate redraw so instructions appear before the blocking loop
            AppKit.NSApp.updateWindows()
        self.state.set_calibration_state("uncalibrated", "Running guided hand calibration...")
        ok, msg = self.provider.run_guided_calibration(announce=self._calibration_announce)
        if self._calib_overlay is not None:
            self._calib_overlay.setHidden_(True)
        state = "calibrated" if ok else "uncalibrated"
        self.state.set_calibration_state(state, msg)
        self.state.record_local_event(
            request_id=self.state.session_id,
            event="cursor_calibration",
            status="ok" if ok else "error",
            summary=msg,
        )

    def toggle_debug(self) -> None:
        self.debug_visible = not self.debug_visible
        if self.debug_scroll is not None:
            self.debug_scroll.setHidden_(not self.debug_visible)
        if self.debug_button is not None:
            self.debug_button.setTitle_("Hide Debug" if self.debug_visible else "Debug")

    def forward_browser_click(self, vp_x: int, vp_y: int) -> None:
        loop = self.runtime._loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            browser_runtime.forward_mouse_click(vp_x, vp_y),
            loop,
        )

    def forward_browser_scroll(self, vp_x: int, vp_y: int, delta_x: int, delta_y: int) -> None:
        loop = self.runtime._loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            browser_runtime.forward_scroll(vp_x, vp_y, delta_x, delta_y),
            loop,
        )

    def tick(self) -> None:
        self.runtime.poll_capture()
        snapshot = self.state.snapshot()

        # --- Header ---
        if self.connection_label is not None:
            dot = "● " if snapshot.connected else "○ "
            status = "Connected" if snapshot.connected else "Reconnecting..."
            self.connection_label.setStringValue_(dot + status)
        if self.session_label is not None:
            # Show only the random hex suffix (strip "local_session_" prefix)
            sid = snapshot.session_id
            if "_" in sid:
                sid = sid.rsplit("_", 1)[-1]
            self.session_label.setStringValue_(f"session:{sid[:4]}")

        # --- Agent / Tool ---
        if self.agent_label is not None:
            self.agent_label.setStringValue_(snapshot.current_agent or "–")
        if self.tool_label is not None:
            self.tool_label.setStringValue_(snapshot.current_tool or "")

        # --- Calibration ---
        if self.calibration_label is not None:
            self.calibration_label.setStringValue_(
                f"{snapshot.calibration_state}  {snapshot.calibration_message or ''}"
            )

        # --- Conversation log ---
        if self.log_text is not None:
            text = _format_event_log(snapshot.latest_events)
            self.log_text.setString_(text)
            # Auto-scroll to bottom
            self.log_text.scrollRangeToVisible_(
                Foundation.NSMakeRange(len(text), 0)
            )

        # --- Debug ---
        if self.debug_text is not None and self.debug_visible:
            lines = [
                f"[{e.source}] {e.event} {e.status}  {e.summary[:40]}"
                for e in list(snapshot.latest_events)[-16:]
            ]
            self.debug_text.setString_("\n".join(lines))

        # --- Webcam preview in sidebar ---
        self._update_webcam_preview(snapshot)

        # --- Browser screencast frame ---
        frame_bytes = browser_runtime.get_latest_screencast_frame()
        if frame_bytes is not None and self.browser_view is not None:
            self.browser_view.update_image(frame_bytes)

    def _build_window(self) -> None:
        screen = _get_builtin_nsscreen()  # always the MacBook's built-in display
        visible = screen.visibleFrame()

        wx = int(visible.origin.x)
        wy = int(visible.origin.y)
        ww = int(visible.size.width)
        wh = int(visible.size.height)

        mask = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
        )
        # IMPORTANT: initWithContentRect: adds a titlebar ON TOP of the content rect,
        # making the window taller than visibleFrame by ~28px.  The bottom of the
        # content view then overlaps the Dock.
        # Fix: create with a dummy rect, then set the WINDOW FRAME (title bar
        # included) to visibleFrame via setFrame_display_.  AppKit subtracts the
        # titlebar so the content view exactly fills the space between Dock and
        # menu bar.
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, ww, wh),
            mask,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setFrame_display_(AppKit.NSMakeRect(wx, wy, ww, wh), False)
        window.setTitle_("Live Agent")
        window.setDelegate_(self._bridge)
        content = window.contentView()

        # Content view dimensions after titlebar has been subtracted
        content_frame = content.frame()
        ch = int(content_frame.size.height)
        cw = int(content_frame.size.width)
        actual_browser_w = cw - PANEL_W

        self.browser_view = BrowserView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, actual_browser_w, ch)
        )
        self.browser_view.setOwner_(self)
        content.addSubview_(self.browser_view)

        # ------------------------------------------------------------------
        # Calibration instruction overlay (covers browser area during calibration)
        # ------------------------------------------------------------------
        self._calib_overlay = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, actual_browser_w, ch)
        )
        self._calib_overlay.setWantsLayer_(True)
        overlay_layer = self._calib_overlay.layer()
        if overlay_layer is not None:
            overlay_layer.setBackgroundColor_(
                AppKit.NSColor.colorWithRed_green_blue_alpha_(0.05, 0.05, 0.08, 0.92).CGColor()
            )

        calib_title = _make_label(
            AppKit.NSMakeRect(60, ch // 2 + 10, actual_browser_w - 120, 50),
            "Hand Calibration",
            bold=True,
            font_size=32.0,
        )
        calib_title.setAlignment_(AppKit.NSTextAlignmentCenter)

        calib_steps = _make_label(
            AppKit.NSMakeRect(60, ch // 2 - 80, actual_browser_w - 120, 80),
            "Follow the cyan ring on screen and hold your fingertip inside it.\n"
            "Order:  Top-Left  →  Top-Right  →  Bottom-Right  →  Bottom-Left",
            font_size=18.0,
        )
        calib_steps.setAlignment_(AppKit.NSTextAlignmentCenter)
        cell = calib_steps.cell()
        if cell is not None:
            cell.setWraps_(True)

        self._calib_overlay.addSubview_(calib_title)
        self._calib_overlay.addSubview_(calib_steps)
        self._calib_overlay.setHidden_(True)
        content.addSubview_(self._calib_overlay)

        # ------------------------------------------------------------------
        # Sidebar (right side, 380px wide)
        # ------------------------------------------------------------------
        sidebar_x = actual_browser_w
        sidebar = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(sidebar_x, 0, PANEL_W, ch)
        )

        # Draw a thin separator line on the left edge of the sidebar
        sep = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 1, ch))
        sep.setBoxType_(AppKit.NSBoxSeparator)
        sidebar.addSubview_(sep)

        pad = 10  # horizontal padding inside sidebar

        # --- 1. Header bar (top 50px) ---
        header_y = ch - HEADER_H
        self.connection_label = _make_label(
            AppKit.NSMakeRect(pad, header_y + 16, PANEL_W - 120, 22),
            "● Connecting...",
            bold=True,
            font_size=13.0,
        )
        self.session_label = _make_label(
            AppKit.NSMakeRect(PANEL_W - 110, header_y + 18, 100, 16),
            "",
            font_size=10.0,
            color=AppKit.NSColor.secondaryLabelColor(),
        )
        sidebar.addSubview_(self.connection_label)
        sidebar.addSubview_(self.session_label)

        # Thin separator below header
        hsep = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, header_y - 1, PANEL_W, 1))
        hsep.setBoxType_(AppKit.NSBoxSeparator)
        sidebar.addSubview_(hsep)

        # --- 2. Agent / Tool (70px) ---
        agent_y = header_y - AGENT_H
        self.agent_label = _make_label(
            AppKit.NSMakeRect(pad, agent_y + 36, PANEL_W - pad * 2, 26),
            "–",
            bold=True,
            font_size=18.0,
        )
        self.tool_label = _make_label(
            AppKit.NSMakeRect(pad, agent_y + 14, PANEL_W - pad * 2, 20),
            "",
            font_size=12.0,
            color=AppKit.NSColor.secondaryLabelColor(),
        )
        sidebar.addSubview_(self.agent_label)
        sidebar.addSubview_(self.tool_label)

        # --- 3. Webcam preview (213px ≈ 380 * 9/16) ---
        webcam_y = agent_y - WEBCAM_H
        self.webcam_view = AppKit.NSImageView.alloc().initWithFrame_(
            AppKit.NSMakeRect(pad, webcam_y, PANEL_W - pad * 2, WEBCAM_H)
        )
        self.webcam_view.setImageScaling_(AppKit.NSImageScaleAxesIndependently)
        sidebar.addSubview_(self.webcam_view)

        # --- 4. Calibration strip (28px) ---
        calib_y = webcam_y - CALIB_H
        self.calibration_label = _make_label(
            AppKit.NSMakeRect(pad, calib_y + 6, PANEL_W - pad * 2, 18),
            "Calibration: uncalibrated",
            font_size=10.0,
            color=AppKit.NSColor.secondaryLabelColor(),
        )
        sidebar.addSubview_(self.calibration_label)

        # Separator above conversation log
        mid_sep = AppKit.NSBox.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, calib_y - 2, PANEL_W, 1)
        )
        mid_sep.setBoxType_(AppKit.NSBoxSeparator)
        sidebar.addSubview_(mid_sep)

        # --- 5. Button bar (bottom 44px) ---
        btn_y = 0
        btn_w = (PANEL_W - pad * 2 - 4 * 3) // 5  # 5 buttons with small gaps

        self.mute_button = _make_small_button("Mute", AppKit.NSMakeRect(pad, btn_y + 7, btn_w, 28))
        self.mute_button.setTarget_(self._bridge)
        self.mute_button.setAction_("toggleMute:")
        sidebar.addSubview_(self.mute_button)

        reconnect_btn = _make_small_button("Reconnect", AppKit.NSMakeRect(pad + btn_w + 3, btn_y + 7, btn_w + 10, 28))
        reconnect_btn.setTarget_(self._bridge)
        reconnect_btn.setAction_("reconnect:")
        sidebar.addSubview_(reconnect_btn)

        calibrate_btn = _make_small_button("Calibrate", AppKit.NSMakeRect(pad + btn_w * 2 + 16, btn_y + 7, btn_w + 10, 28))
        calibrate_btn.setTarget_(self._bridge)
        calibrate_btn.setAction_("recalibrate:")
        sidebar.addSubview_(calibrate_btn)

        self.debug_button = _make_small_button("Debug", AppKit.NSMakeRect(pad + btn_w * 3 + 30, btn_y + 7, btn_w, 28))
        self.debug_button.setTarget_(self._bridge)
        self.debug_button.setAction_("toggleDebug:")
        sidebar.addSubview_(self.debug_button)

        quit_btn = _make_small_button("Quit", AppKit.NSMakeRect(PANEL_W - pad - btn_w, btn_y + 7, btn_w, 28))
        quit_btn.setTarget_(self._bridge)
        quit_btn.setAction_("quit:")
        sidebar.addSubview_(quit_btn)

        # Separator above buttons
        btn_sep = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, BUTTON_H, PANEL_W, 1))
        btn_sep.setBoxType_(AppKit.NSBoxSeparator)
        sidebar.addSubview_(btn_sep)

        # --- 6. Debug console (150px above buttons, hidden by default) ---
        self.debug_text = AppKit.NSTextView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, PANEL_W - 14, DEBUG_H)
        )
        self.debug_text.setEditable_(False)
        self.debug_text.setFont_(
            AppKit.NSFont.monospacedSystemFontOfSize_weight_(9.0, AppKit.NSFontWeightRegular)
        )
        self.debug_scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            AppKit.NSMakeRect(pad, BUTTON_H + 2, PANEL_W - pad * 2, DEBUG_H)
        )
        self.debug_scroll.setDocumentView_(self.debug_text)
        self.debug_scroll.setHasVerticalScroller_(True)
        self.debug_scroll.setHidden_(True)
        sidebar.addSubview_(self.debug_scroll)

        # --- 7. Conversation log (flexible middle area) ---
        log_y = LOG_BOTTOM
        log_h = calib_y - 6 - log_y
        if log_h < 60:
            log_h = 60

        self.log_text = AppKit.NSTextView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, PANEL_W - 14, max(log_h, 200))
        )
        self.log_text.setEditable_(False)
        self.log_text.setFont_(AppKit.NSFont.systemFontOfSize_(11.0))
        self.log_scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            AppKit.NSMakeRect(pad, log_y, PANEL_W - pad * 2, log_h)
        )
        self.log_scroll.setDocumentView_(self.log_text)
        self.log_scroll.setHasVerticalScroller_(True)
        sidebar.addSubview_(self.log_scroll)

        content.addSubview_(sidebar)

        self.window = window

    def _configure_headless_browser(self) -> None:
        """
        Tell browser_runtime where the BrowserView sits on screen so that
        click_here / scroll_here cursor math stays correct in headless mode.
        """
        if self.window is None or self.browser_view is None:
            return

        full_frame = _get_builtin_nsscreen().frame()
        screen_h_pts = int(full_frame.size.height)

        win_frame = self.window.frame()
        win_origin_y_ns = int(win_frame.origin.y)
        win_h = int(win_frame.size.height)

        content_h = int(self.window.contentView().frame().size.height)
        bv_frame = self.browser_view.frame()
        bv_w = int(bv_frame.size.width)
        bv_h = int(bv_frame.size.height)

        # Browser view's top-left in Quartz coordinates (y=0 at top of screen):
        # NSScreen y for the content view top = win_origin_y_ns + win_h
        # Quartz y for content view top = screen_h_pts - (win_origin_y_ns + win_h)
        # Then offset by (win_h - content_h) for the titlebar:
        titlebar_h = win_h - content_h
        origin_x = int(win_frame.origin.x)
        origin_y = screen_h_pts - (win_origin_y_ns + win_h) + titlebar_h

        browser_runtime.configure_headless_browser(
            viewport_width=bv_w,
            viewport_height=bv_h,
            origin_x=origin_x,
            origin_y=origin_y,
        )

    def _update_webcam_preview(self, snapshot) -> None:
        if self.webcam_view is None:
            return
        frame = self.runtime.get_preview_frame()
        if frame is None:
            return
        composed = frame.copy()
        height, width = composed.shape[:2]
        screen_w, screen_h = get_main_display_size()

        if snapshot.fingertip is not None:
            px = int(snapshot.fingertip.x * (width - 1))
            py = int(snapshot.fingertip.y * (height - 1))
            cv2.circle(composed, (px, py), 10, (0, 255, 255), -1)

        def draw_cursor(point, color) -> None:
            if point is None:
                return
            px = int((point.x / max(1, screen_w - 1)) * (width - 1))
            py = int((point.y / max(1, screen_h - 1)) * (height - 1))
            cv2.circle(composed, (px, py), 9, color, 2)

        draw_cursor(snapshot.local_cursor, (0, 255, 0))
        draw_cursor(snapshot.server_cursor, (0, 100, 255))

        image = _ns_image_from_bgr(composed)
        if image is not None:
            self.webcam_view.setImage_(image)

    def _calibration_announce(self, message: str) -> None:
        self.state.set_calibration_state("uncalibrated", message)


def _make_small_button(title: str, frame) -> AppKit.NSButton:
    btn = AppKit.NSButton.alloc().initWithFrame_(frame)
    btn.setTitle_(title)
    btn.setFont_(AppKit.NSFont.systemFontOfSize_(11.0))
    btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
    return btn


# ---------------------------------------------------------------------------
# App delegate
# ---------------------------------------------------------------------------

class _AppDelegate(AppKit.NSObject):  # type: ignore[misc, valid-type]
    def initWithArgs_(self, args):
        self = objc.super(_AppDelegate, self).init()
        if self is None:
            return None
        self.args = args
        self.controller = None
        return self

    def applicationDidFinishLaunching_(self, notification) -> None:
        self.controller = CompanionWindowController(self.args)
        self.controller.start()
        # Bring window to front after it's been created and shown
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        if self.controller.window is not None:
            self.controller.window.makeKeyAndOrderFront_(None)
            self.controller.window.orderFrontRegardless()

    def applicationWillTerminate_(self, notification) -> None:
        if self.controller is not None:
            self.controller.stop()


def main() -> None:
    args = build_arg_parser().parse_args()
    app = AppKit.NSApplication.sharedApplication()
    # Force dark mode regardless of system setting
    dark = AppKit.NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua")
    if dark is not None:
        app.setAppearance_(dark)
    delegate = _AppDelegate.alloc().initWithArgs_(args)
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    main()
