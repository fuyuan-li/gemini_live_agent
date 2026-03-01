from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, Protocol, Tuple

from client.cursor.provider import HandCursorProvider
from client.cursor.types import CursorSample


class RunnerProvider(Protocol):
    def start(self) -> bool:
        ...

    def stop(self) -> None:
        ...

    def get_cursor(self) -> Optional[CursorSample]:
        ...

    def status(self) -> Dict[str, Any]:
        ...

    def toggle_overlay(self) -> Optional[bool]:
        ...

    def set_overlay_visible(self, visible: bool) -> Optional[bool]:
        ...

    def run_guided_calibration(
        self, *, announce: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str]:
        ...

    def clear_calibration(self) -> Tuple[bool, str]:
        ...

    def pump_ui(self) -> None:
        ...


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run standalone webcam hand cursor tracker")
    p.add_argument("--camera-index", type=int, default=0)
    p.add_argument("--smoothing", type=float, default=0.35)
    p.add_argument("--stale-ms", type=int, default=400)
    p.add_argument("--overlay", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--preview", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--mirror", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--overlay-radius", type=int, default=10)
    p.add_argument("--poll-hz", type=float, default=30.0)
    p.add_argument("--print-hz", type=float, default=5.0)
    p.add_argument("--duration-seconds", type=float, default=0.0)
    p.add_argument("--stdin-controls", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--global-hotkeys", action=argparse.BooleanOptionalAction, default=True)
    return p


def _stdin_command_worker(cmd_q: "queue.Queue[str]", stop_evt: threading.Event) -> None:
    while not stop_evt.is_set():
        line = sys.stdin.readline()
        if not line:
            time.sleep(0.05)
            continue
        cmd_q.put(line.strip().lower())


def _start_hotkey_listener(cmd_q: "queue.Queue[str]", stop_evt: threading.Event):
    try:
        from pynput import keyboard
    except Exception:
        return None

    def on_press(key: object) -> None:
        if stop_evt.is_set():
            return None

        try:
            key_char = getattr(key, "char", None)
            ch = key_char.lower() if isinstance(key_char, str) else None
        except Exception:
            ch = None

        if ch == "q":
            cmd_q.put("quit")
        elif ch == "o":
            cmd_q.put("toggle_overlay")
        elif ch == "c":
            cmd_q.put("calibrate")
        return None

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    return listener


def _handle_command(provider: RunnerProvider, cmd: str) -> bool:
    if cmd in {"q", "quit", "exit"}:
        return True

    if cmd in {"o", "toggle_overlay"}:
        vis = provider.toggle_overlay()
        print(f"[cursor_debug] overlay_visible={vis}")
    elif cmd in {"show_overlay"}:
        vis = provider.set_overlay_visible(True)
        print(f"[cursor_debug] overlay_visible={vis}")
    elif cmd in {"hide_overlay"}:
        vis = provider.set_overlay_visible(False)
        print(f"[cursor_debug] overlay_visible={vis}")
    elif cmd in {"calibrate", "calib"}:
        ok, msg = provider.run_guided_calibration(announce=print)
        print(f"[cursor_debug] calibrate: ok={ok} msg={msg}")
    elif cmd in {"clear_calibration", "clear_calib"}:
        ok, msg = provider.clear_calibration()
        print(f"[cursor_debug] clear_calibration: ok={ok} msg={msg}")
    elif cmd in {"status", "s"}:
        print(f"[cursor_debug] status={provider.status()}")
    elif cmd in {"help", "h", "?"}:
        print(
            "[cursor_debug] commands: "
            "o/toggle_overlay, show_overlay, hide_overlay, "
            "c/calibrate, clear_calibration, status, q/quit"
        )
    return False


def run_cursor_debug(
    provider: RunnerProvider,
    *,
    poll_hz: float = 30.0,
    print_hz: float = 5.0,
    duration_seconds: float = 0.0,
    command_queue: Optional["queue.Queue[str]"] = None,
) -> None:
    poll_dt = 1.0 / max(1.0, float(poll_hz))
    print_dt = 1.0 / max(0.5, float(print_hz))

    started = provider.start()
    if not started:
        raise RuntimeError(f"failed to start hand cursor provider: {provider.status()}")

    t0 = time.time()
    last_print = 0.0

    try:
        while True:
            now = time.time()
            if duration_seconds > 0 and now - t0 >= duration_seconds:
                break

            if command_queue is not None:
                try:
                    while True:
                        cmd = command_queue.get_nowait()
                        if _handle_command(provider, cmd):
                            return
                except queue.Empty:
                    pass

            provider.pump_ui()
            cur = provider.get_cursor()
            if now - last_print >= print_dt:
                status = provider.status()
                if cur is None:
                    print(f"[cursor_debug] cursor=None status={status}")
                else:
                    print(
                        "[cursor_debug] "
                        f"cursor=({cur.x},{cur.y}) ts={cur.ts:.3f} conf={cur.confidence} "
                        f"status={{running:{status.get('running')}, preview:{status.get('preview_enabled')}, calibrated:{status.get('calibrated')}}}"
                    )
                last_print = now

            time.sleep(poll_dt)
    finally:
        provider.stop()


def main() -> None:
    args = build_arg_parser().parse_args()

    provider = HandCursorProvider(
        camera_index=args.camera_index,
        smoothing=args.smoothing,
        stale_timeout_s=max(0.0, args.stale_ms / 1000.0),
        tracker_start_timeout_s=8.0,
        mirror=args.mirror,
        preview=args.preview,
        overlay=args.overlay,
        overlay_radius=args.overlay_radius,
    )

    cmd_q: "queue.Queue[str]" = queue.Queue()
    stop_evt = threading.Event()

    cmd_thread: Optional[threading.Thread] = None
    hotkey_listener = None

    if args.stdin_controls:
        print(
            "[cursor_debug] commands: o(toggle overlay), c(calibrate), "
            "clear_calibration, status, q(quit)"
        )
        cmd_thread = threading.Thread(target=_stdin_command_worker, args=(cmd_q, stop_evt), daemon=True)
        cmd_thread.start()

    if args.global_hotkeys:
        hotkey_listener = _start_hotkey_listener(cmd_q, stop_evt)
        if hotkey_listener is not None:
            print("[cursor_debug] global hotkeys active: o(toggle overlay), c(calibrate), q(quit)")
        else:
            print("[cursor_debug] global hotkeys unavailable; use terminal commands + Enter.")

    try:
        run_cursor_debug(
            provider,
            poll_hz=args.poll_hz,
            print_hz=args.print_hz,
            duration_seconds=args.duration_seconds,
            command_queue=cmd_q if (args.stdin_controls or args.global_hotkeys) else None,
        )
    except KeyboardInterrupt:
        pass
    finally:
        stop_evt.set()
        if hotkey_listener is not None:
            try:
                hotkey_listener.stop()
            except Exception:
                pass
        if cmd_thread and cmd_thread.is_alive():
            cmd_thread.join(timeout=0.3)


if __name__ == "__main__":
    main()
