#!/usr/bin/env python3
"""
castletool.tui — a tap/click-driven front end for castletool, built with
Textual.

This module intentionally does not reimplement any of castletool's actual
logic (image/MIDI conversion, Castle GraphQL calls, etc). Instead it swaps
out the plain-terminal I/O primitives that module.castletool uses
(`p`, `pb`, `pw`, `pe`, `ps`, `ask`, `yn`, `choose`, `ask_path`) for
equivalents backed by Textual widgets, then drives the exact same
`do_add_image` / `do_add_midi` / `do_edit_background_color` /
`do_upload_deck` / `do_upload_html` functions that the classic CLI uses.

Everything runs in a background thread (see `CastletoolApp.run_flow`) since
that logic is written as ordinary blocking, synchronous code. Prompts are
bridged to the UI thread with `App.call_from_thread` plus a
`threading.Event`, so the worker thread blocks waiting for a tap/click
without ever blocking the UI's event loop.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

try:
    from rich.markup import escape
    from textual.app import App, ComposeResult
    from textual.containers import Vertical
    from textual.message import Message
    from textual.widgets import Input, RichLog, Static
except ImportError:
    print("The tap/click TUI needs the 'textual' package.")
    print("Install it with: pip install castletool[all]")
    raise SystemExit(1)

from . import castletool as ct

STATE_FILE = Path.home() / ".castletool_tui_state.json"

UPDATE_MESSAGE = """PLEASE READ!

Hey, thanks for using castletool! You recently updated, and I want to let you know how things are changing.

We are moving to textual! Many users have requested that we have a UI instead of purely terminal, so we are making the move now.

From now on, you can click or tap things to choose what you want to do, and no longer have to type numbers.

As always, you can report an issue on my github or in my discord, links are below.
https://discord.gg/S86ZYzTXWw
https://github.com/MGoosePlayZ/castletool/issues

Thanks, MGoosePlayZ"""


def _load_last_version() -> str | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("version")
    except Exception:
        return None


def _save_last_version(version: str) -> None:
    try:
        STATE_FILE.write_text(json.dumps({"version": version}), encoding="utf-8")
    except Exception:
        pass


# ── tappable widgets ─────────────────────────────────────────────────────────

class TapOption(Static, can_focus=True):
    """A single plain line of text that can be tapped, clicked, or entered."""

    class Chosen(Message):
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    def __init__(self, text: str, index: int) -> None:
        super().__init__(text)
        self.index = index

    def on_click(self) -> None:
        self.post_message(self.Chosen(self.index))

    def on_key(self, event) -> None:
        if event.key == "enter":
            event.stop()
            self.post_message(self.Chosen(self.index))


class AnyKeyPrompt(Static, can_focus=True):
    """A plain line that dismisses on a tap/click OR any key press."""

    class Dismissed(Message):
        pass

    def on_click(self) -> None:
        self.post_message(self.Dismissed())

    def on_key(self, event) -> None:
        event.stop()
        self.post_message(self.Dismissed())


# ── bridges castletool's blocking I/O calls onto the Textual UI ─────────────

class TuiIO:
    """Drop-in replacement for castletool's p/pb/pw/pe/ps/ask/yn/choose/ask_path."""

    def __init__(self, app: "CastletoolApp") -> None:
        self.app = app

    # output -- fire onto the UI thread and don't wait
    def p(self, msg: str = "") -> None:
        self.app.call_from_thread(self.app.log_line, msg, "")

    def pb(self, msg: str) -> None:
        self.app.call_from_thread(self.app.log_line, msg, "bold")

    def pw(self, msg: str) -> None:
        self.app.call_from_thread(self.app.log_line, f"\u26a0  {msg}", "yellow")

    def pe(self, msg: str) -> None:
        self.app.call_from_thread(self.app.log_line, f"\u2717  {msg}", "red")

    def ps(self, msg: str) -> None:
        self.app.call_from_thread(self.app.log_line, f"\u2713  {msg}", "green")

    # input -- mount a prompt on the UI thread, then block *this* (worker)
    # thread until the UI thread reports back that the user tapped/typed.
    def choose(self, prompt: str, options: list[str]) -> str:
        event = threading.Event()
        box: dict = {}
        self.app.call_from_thread(self.app.mount_choice, prompt, options, event, box)
        event.wait()
        return options[box["index"]]

    def yn(self, prompt: str, default: str = "y") -> bool:
        event = threading.Event()
        box: dict = {}
        self.app.call_from_thread(self.app.mount_yesno, prompt, default, event, box)
        event.wait()
        return box["index"] == 0

    def ask(self, prompt: str, default: str | None = None) -> str:
        event = threading.Event()
        box: dict = {}
        self.app.call_from_thread(self.app.mount_text, prompt, default, event, box)
        event.wait()
        val = box.get("value", "").strip()
        return val if val else (default or "")

    def ask_path(self, prompt: str, default=None, search_dir: Path | None = None) -> str:
        return self.ask(prompt, default)

    def pause(self, message: str = "Press anything to exit") -> None:
        """Block until the user taps/clicks or presses any key."""
        event = threading.Event()
        self.app.call_from_thread(self.app.mount_pause, message, event)
        event.wait()


# ── the app itself ───────────────────────────────────────────────────────────

class CastletoolApp(App):
    """A plain-text, tap/click-driven front end for castletool."""

    # Use the terminal's own ANSI palette rather than Textual's themed
    # truecolor look -- no custom background, just the colors already
    # sitting in the user's terminal.
    ansi_color = True

    CSS = """
    Screen {
        background: transparent;
    }

    #log {
        background: transparent;
        border: none;
        scrollbar-size: 1 1;
    }

    #prompt {
        background: transparent;
        height: auto;
    }

    TapOption {
        width: auto;
        background: transparent;
        color: white;
    }

    TapOption:hover {
        text-style: bold underline;
    }

    TapOption:focus {
        text-style: bold underline;
    }

    AnyKeyPrompt {
        width: auto;
        background: transparent;
        color: white;
    }

    AnyKeyPrompt:hover {
        text-style: bold underline;
    }

    AnyKeyPrompt:focus {
        text-style: bold underline;
    }

    Input {
        background: transparent;
        border: none;
        color: white;
        height: 1;
        padding: 0;
    }

    Input:focus {
        border: none;
    }
    """

    def compose(self) -> ComposeResult:
        yield RichLog(id="log", markup=True, wrap=True, highlight=False, auto_scroll=True)
        yield Vertical(id="prompt")

    def on_mount(self) -> None:
        self.io = TuiIO(self)
        # Redirect castletool's module-level I/O primitives at the ones
        # backed by this UI. do_add_image/do_add_midi/etc all look these
        # names up as plain globals at call time, so this is enough to
        # make every existing action function tap/click-driven with no
        # changes to castletool.py itself.
        ct.p = self.io.p
        ct.pb = self.io.pb
        ct.pw = self.io.pw
        ct.pe = self.io.pe
        ct.ps = self.io.ps
        ct.ask = self.io.ask
        ct.yn = self.io.yn
        ct.choose = self.io.choose
        ct.ask_path = self.io.ask_path

        self._pending: tuple | None = None
        threading.Thread(target=self.run_flow, daemon=True).start()

    # ---- log ----------------------------------------------------------

    def log_line(self, msg: str = "", style: str = "") -> None:
        log = self.query_one("#log", RichLog)
        safe = escape(msg)
        log.write(f"[{style}]{safe}[/{style}]" if style else safe)

    def _clear_prompt(self) -> None:
        self.query_one("#prompt", Vertical).remove_children()

    # ---- mounting prompts (always called on the UI thread) ------------

    def mount_choice(self, prompt: str, options: list[str], event: threading.Event, box: dict) -> None:
        self.log_line(prompt, "bold")
        container = self.query_one("#prompt", Vertical)
        container.remove_children()
        self._pending = ("choice", event, box)
        widgets = [TapOption(f"  {i + 1}) {opt}", i) for i, opt in enumerate(options)]
        for widget in widgets:
            container.mount(widget)
        widgets[0].focus()

    def mount_yesno(self, prompt: str, default: str, event: threading.Event, box: dict) -> None:
        hint = "Y/n" if default == "y" else "y/N"
        self.log_line(f"{prompt} ({hint})", "bold")
        container = self.query_one("#prompt", Vertical)
        container.remove_children()
        self._pending = ("choice", event, box)
        yes, no = TapOption("  Yes", 0), TapOption("  No", 1)
        container.mount(yes)
        container.mount(no)
        (yes if default == "y" else no).focus()

    def mount_text(self, prompt: str, default: str | None, event: threading.Event, box: dict) -> None:
        suffix = f" [{default}]" if default else ""
        self.log_line(prompt + suffix, "bold")
        container = self.query_one("#prompt", Vertical)
        container.remove_children()
        self._pending = ("text", event, box)
        field = Input(placeholder=default or "")
        container.mount(field)
        field.focus()

    def mount_pause(self, message: str, event: threading.Event) -> None:
        self.log_line()
        container = self.query_one("#prompt", Vertical)
        container.remove_children()
        self._pending = ("pause", event, {})
        widget = AnyKeyPrompt(message)
        container.mount(widget)
        widget.focus()

    # ---- prompt responses -----------------------------------------------

    def on_tap_option_chosen(self, message: TapOption.Chosen) -> None:
        if not self._pending or self._pending[0] != "choice":
            return
        _, event, box = self._pending
        box["index"] = message.index
        self._pending = None
        self._clear_prompt()
        self.log_line()
        event.set()

    def on_input_submitted(self, message: Input.Submitted) -> None:
        if not self._pending or self._pending[0] != "text":
            return
        _, event, box = self._pending
        box["value"] = message.value
        self._pending = None
        self._clear_prompt()
        self.log_line()
        event.set()

    def on_any_key_prompt_dismissed(self, message: AnyKeyPrompt.Dismissed) -> None:
        if not self._pending or self._pending[0] != "pause":
            return
        _, event, _box = self._pending
        self._pending = None
        self._clear_prompt()
        event.set()

    # ---- update-notice help screen -------------------------------------

    def _do_suspend_and_edit(self, editor: str, tmp_path: str) -> bool:
        try:
            with self.suspend():
                subprocess.run([editor, tmp_path])
            return True
        except Exception:
            return False

    def _show_update_message(self) -> None:
        # Suspending the TUI to hand off to an external editor is flaky on
        # Termux's terminal driver (same reason fzf/prompt_toolkit got
        # dropped from the classic CLI) -- just print it there instead.
        editor = None if ct.is_termux() else (shutil.which("micro") or shutil.which("nano"))
        opened = False
        tmp_path = None
        if editor:
            try:
                with tempfile.NamedTemporaryFile(
                    "w", suffix=".txt", delete=False, encoding="utf-8"
                ) as tmp:
                    tmp.write(UPDATE_MESSAGE)
                    tmp_path = tmp.name
                opened = self.call_from_thread(self._do_suspend_and_edit, editor, tmp_path)
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        if not opened:
            self.io.p()
            for line in UPDATE_MESSAGE.splitlines():
                self.io.p(line)
            self.io.p()

    def _maybe_show_update_message(self) -> None:
        installed = ct.get_installed_version()
        last_seen = _load_last_version()
        if last_seen is not None and last_seen != installed:
            self._show_update_message()
        _save_last_version(installed)

    # ---- main flow (runs entirely on a background thread) -------------

    def run_flow(self) -> None:
        try:
            self._flow()
        except SystemExit:
            self.io.pause()
        except Exception as exc:  # pragma: no cover - defensive
            self.io.pe(f"Unexpected error: {exc}")
            self.io.pause()
        finally:
            self.call_from_thread(self.exit)

    def _flow(self) -> None:
        io = self.io

        self._maybe_show_update_message()

        ct.check_for_update()
        ct.ensure_dependencies()

        # ── select deck ──
        home = Path.cwd()
        decks = ct.find_decks(home)
        if not decks:
            io.pe("No decks were found. Are you in the right directory?")
            io.pause()
            return

        deck_names = [d.name for d in decks]
        if len(decks) == 1:
            deck = decks[0]
            io.ps(f"Auto selecting {deck.name}")
        else:
            io.pb(f"Detected decks: {', '.join(deck_names)}")
            chosen = io.choose("Select the deck you would like to modify:", deck_names)
            deck = home / chosen
        io.p()

        # ── select card ──
        cards = ct.find_cards(deck)
        if not cards:
            io.pe(f"No cards found in {deck}.")
            io.pause()
            return
        card_names = [c.name for c in cards]
        if len(cards) == 1:
            card = cards[0]
            io.ps(f"Auto selecting {card.name}")
        else:
            chosen = io.choose("Select the card you would like to edit:", card_names)
            card = deck / "cards" / chosen
        io.p()

        # ── select blueprint (actor) ──
        blueprints = ct.find_blueprints(card)
        if not blueprints:
            io.pe(f"No blueprints found in {card}.")
            io.pause()
            return
        bp_names = [b.name for b in blueprints]
        if len(blueprints) == 1:
            bp_path = blueprints[0]
            io.ps(f"Auto selecting {bp_path.name}")
        else:
            chosen = io.choose("Select the actor you want to edit:", bp_names)
            bp_path = card / "scene" / "blueprints" / chosen
        io.p()

        with open(bp_path, "r", encoding="utf-8") as f:
            actor = json.load(f)

        # ── action menu ──
        while True:
            options = []
            if ct.HAS_PIL:
                options.append("Add image")
            if ct.HAS_MIDO:
                options.append("Add MIDI")
            options.append("Edit Background Color")
            if ct._env_flag("CASTLETOOL_HTML"):
                options.append("Upload HTML")
            options.append("Upload Deck")
            options.append("Exit Tool")

            action = io.choose("Select the action you want to perform:", options)

            if action == "Add image":
                ct.do_add_image(bp_path, actor, card)
            elif action == "Add MIDI":
                ct.do_add_midi(bp_path, actor, card)
            elif action == "Edit Background Color":
                ct.do_edit_background_color(card)
            elif action == "Upload HTML":
                ct.do_upload_html(deck, card)
            elif action == "Upload Deck":
                ct.do_upload_deck(deck)
            elif action == "Exit Tool":
                break


def main() -> None:
    argv = sys.argv[1:]

    if "--cli" in argv:
        sys.argv = [sys.argv[0], *[a for a in argv if a != "--cli"]]
        ct.main()
        return

    if "--version" in argv or "-v" in argv:
        print(f"castletool {ct.get_installed_version()}")
        return

    CastletoolApp().run()


if __name__ == "__main__":
    main()
