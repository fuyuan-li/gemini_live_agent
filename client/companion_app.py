from __future__ import annotations

import argparse

import AppKit  # type: ignore
import Foundation  # type: ignore
import cv2  # type: ignore
import objc  # type: ignore

from client.companion_runtime import CompanionRuntime
from client.companion_state import CompanionState
from client.cursor.mapper import get_main_display_size
from client.cursor.provider import HandCursorProvider
from client.session_ids import DEFAULT_WS_ROOT_URL, generate_session_id, normalize_ws_root_url


DEFAULT_WS_URL = DEFAULT_WS_ROOT_URL


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Native macOS companion window for the live voice agent")
    p.add_argument("--ws-url", default=DEFAULT_WS_URL)
    p.add_argument("--camera-index", type=int, default=0)
    p.add_argument("--hand-smoothing", type=float, default=0.35)
    p.add_argument("--cursor-stale-ms", type=int, default=400)
    p.add_argument("--cursor-send-hz", type=float, default=20.0)
    p.add_argument("--hand-overlay", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--hand-overlay-radius", type=int, default=10)
    p.add_argument("--hand-mirror", action=argparse.BooleanOptionalAction, default=True)
    return p

def _make_label(frame, text: str, *, font_size: float = 12.0, bold: bool = False):
    label = AppKit.NSTextField.alloc().initWithFrame_(frame)
    label.setStringValue_(text)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setBordered_(False)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    font = AppKit.NSFont.boldSystemFontOfSize_(font_size) if bold else AppKit.NSFont.systemFontOfSize_(font_size)
    label.setFont_(font)
    return label


def _ns_image_from_bgr(frame):
    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        return None
    payload = encoded.tobytes()
    data = Foundation.NSData.dataWithBytes_length_(payload, len(payload))
    return AppKit.NSImage.alloc().initWithData_(data)


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


class CompanionWindowController:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.ws_root_url = normalize_ws_root_url(args.ws_url)
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
        self.preview_view = None
        self.connection_label = None
        self.cloud_label = None
        self.status_label = None
        self.calibration_label = None
        self.agent_label = None
        self.tool_label = None
        self.summary_label = None
        self.mute_button = None
        self.debug_button = None
        self.debug_scroll = None
        self.debug_text = None

    def start(self) -> None:
        if not self.provider.start():
            raise RuntimeError(f"failed to start cursor provider: {self.provider.status()}")
        self._build_window()
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
        self.state.set_calibration_state("uncalibrated", "Running guided hand calibration...")
        ok, msg = self.provider.run_guided_calibration(announce=self._calibration_announce)
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
            self.debug_button.setTitle_("Hide Debug" if self.debug_visible else "Show Debug")
        if self.window is not None:
            frame = self.window.frame()
            frame.size.height = 820 if self.debug_visible else 560
            self.window.setFrame_display_animate_(frame, True, True)

    def tick(self) -> None:
        self.runtime.poll_capture()
        snapshot = self.state.snapshot()
        if self.connection_label is not None:
            self.connection_label.setStringValue_("Connected" if snapshot.connected else "Reconnecting...")
        if self.cloud_label is not None:
            if snapshot.session_meta is None:
                self.cloud_label.setStringValue_("Cloud Run: waiting for service metadata")
            else:
                self.cloud_label.setStringValue_(
                    f"Cloud Run: {snapshot.session_meta.service}  rev={snapshot.session_meta.revision}  commit={snapshot.session_meta.commit}"
                )
        if self.status_label is not None:
            self.status_label.setStringValue_(
                f"Mic={'Muted' if snapshot.muted else 'Live'}   Camera=Live   Session={snapshot.session_id}"
            )
        if self.calibration_label is not None:
            self.calibration_label.setStringValue_(
                f"Calibration: {snapshot.calibration_state}  {snapshot.calibration_message or '-'}"
            )
        if self.agent_label is not None:
            self.agent_label.setStringValue_(f"Agent: {snapshot.current_agent or '-'}")
        if self.tool_label is not None:
            self.tool_label.setStringValue_(f"Tool: {snapshot.current_tool or '-'}")
        if self.summary_label is not None:
            self.summary_label.setStringValue_(f"Summary: {snapshot.last_summary or '-'}")
        if self.debug_text is not None:
            lines = [
                f"[{entry.source}] {entry.event} {entry.status} rid={entry.request_id} {entry.summary}"
                for entry in list(snapshot.latest_events)[-16:]
            ]
            self.debug_text.setString_("\n".join(lines))
        self._update_preview(snapshot)

    def _build_window(self) -> None:
        rect = AppKit.NSMakeRect(120, 120, 960, 560)
        mask = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
        )
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            mask,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setTitle_("Live Agent Companion")
        window.setDelegate_(self._bridge)
        content = window.contentView()

        self.connection_label = _make_label(AppKit.NSMakeRect(20, 520, 220, 22), "Connecting...", bold=True)
        self.cloud_label = _make_label(AppKit.NSMakeRect(250, 520, 680, 22), "Cloud Run: waiting for service metadata")
        self.status_label = _make_label(AppKit.NSMakeRect(20, 494, 420, 20), "Mic=Live   Camera=Live")
        self.calibration_label = _make_label(
            AppKit.NSMakeRect(20, 470, 900, 20),
            "Calibration: uncalibrated",
        )
        content.addSubview_(self.connection_label)
        content.addSubview_(self.cloud_label)
        content.addSubview_(self.status_label)
        content.addSubview_(self.calibration_label)

        self.preview_view = AppKit.NSImageView.alloc().initWithFrame_(AppKit.NSMakeRect(20, 170, 460, 290))
        self.preview_view.setImageScaling_(AppKit.NSImageScaleAxesIndependently)
        content.addSubview_(self.preview_view)

        self.agent_label = _make_label(AppKit.NSMakeRect(520, 410, 380, 24), "Agent: -", bold=True, font_size=18.0)
        self.tool_label = _make_label(AppKit.NSMakeRect(520, 380, 380, 22), "Tool: -", font_size=15.0)
        self.summary_label = _make_label(AppKit.NSMakeRect(520, 320, 380, 52), "Summary: -", font_size=13.0)
        summary_cell = self.summary_label.cell()
        if summary_cell is not None:
            summary_cell.setWraps_(True)
            summary_cell.setScrollable_(False)
            summary_cell.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        content.addSubview_(self.agent_label)
        content.addSubview_(self.tool_label)
        content.addSubview_(self.summary_label)

        self.mute_button = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(520, 250, 120, 32))
        self.mute_button.setTitle_("Mute")
        self.mute_button.setTarget_(self._bridge)
        self.mute_button.setAction_("toggleMute:")
        content.addSubview_(self.mute_button)

        reconnect_button = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(650, 250, 120, 32))
        reconnect_button.setTitle_("Reconnect")
        reconnect_button.setTarget_(self._bridge)
        reconnect_button.setAction_("reconnect:")
        content.addSubview_(reconnect_button)

        calibrate_button = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(780, 250, 120, 32))
        calibrate_button.setTitle_("Calibrate")
        calibrate_button.setTarget_(self._bridge)
        calibrate_button.setAction_("recalibrate:")
        content.addSubview_(calibrate_button)

        self.debug_button = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(520, 210, 120, 32))
        self.debug_button.setTitle_("Show Debug")
        self.debug_button.setTarget_(self._bridge)
        self.debug_button.setAction_("toggleDebug:")
        content.addSubview_(self.debug_button)

        quit_button = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(780, 20, 120, 32))
        quit_button.setTitle_("Quit")
        quit_button.setTarget_(self._bridge)
        quit_button.setAction_("quit:")
        content.addSubview_(quit_button)

        self.debug_text = AppKit.NSTextView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 900, 220))
        self.debug_text.setEditable_(False)
        self.debug_text.setFont_(AppKit.NSFont.monospacedSystemFontOfSize_weight_(11.0, AppKit.NSFontWeightRegular))
        self.debug_scroll = AppKit.NSScrollView.alloc().initWithFrame_(AppKit.NSMakeRect(20, 20, 740, 140))
        self.debug_scroll.setDocumentView_(self.debug_text)
        self.debug_scroll.setHasVerticalScroller_(True)
        self.debug_scroll.setHidden_(True)
        content.addSubview_(self.debug_scroll)

        self.window = window

    def _update_preview(self, snapshot) -> None:
        if self.preview_view is None:
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
            cv2.putText(composed, "finger", (px + 8, py - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

        def draw_screen_cursor(point, label: str, color) -> None:
            if point is None:
                return
            px = int((point.x / max(1, screen_w - 1)) * (width - 1))
            py = int((point.y / max(1, screen_h - 1)) * (height - 1))
            cv2.circle(composed, (px, py), 9, color, 2)
            cv2.putText(composed, label, (px + 8, py + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

        draw_screen_cursor(snapshot.local_cursor, "virtual", (0, 255, 0))
        draw_screen_cursor(snapshot.server_cursor, "server", (0, 100, 255))

        image = _ns_image_from_bgr(composed)
        if image is not None:
            self.preview_view.setImage_(image)

    def _calibration_announce(self, message: str) -> None:
        self.state.set_calibration_state("uncalibrated", message)


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

    def applicationWillTerminate_(self, notification) -> None:
        if self.controller is not None:
            self.controller.stop()


def main() -> None:
    args = build_arg_parser().parse_args()
    app = AppKit.NSApplication.sharedApplication()
    delegate = _AppDelegate.alloc().initWithArgs_(args)
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    app.setDelegate_(delegate)
    app.activateIgnoringOtherApps_(True)
    app.run()


if __name__ == "__main__":
    main()
