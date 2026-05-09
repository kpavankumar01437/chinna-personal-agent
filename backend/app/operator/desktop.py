from __future__ import annotations

import subprocess
import os
import re
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlencode
from typing import Any

from .schemas import DesktopActionRequest
from .vault import PrivateVault


@dataclass
class DesktopResult:
    ok: bool
    message: str
    data: dict[str, Any]


class DesktopControlService:
    def __init__(self, vault: PrivateVault):
        self.vault = vault

    def observe(self, session_id: int | None = None) -> DesktopResult:
        self.vault.ensure()
        screenshot_path: str | None = None
        active_window = _active_window()
        ui_elements = _ui_elements()
        ocr_text = ""
        summary = "Screen observation is available; OCR tools may need setup for visible text extraction."
        try:
            from PIL import ImageGrab

            image = ImageGrab.grab()
            target = self.vault.screenshot_dir / f"session-{session_id or 0}-{_stamp()}.png"
            image.save(target)
            screenshot_path = str(target)
            ocr_text = _ocr_image(target)
            summary = _observation_summary(target.name, active_window, ocr_text, ui_elements)
        except Exception as exc:
            summary = f"Screenshot capture unavailable in current environment: {exc}"

        payload = {
            "session_id": session_id,
            "screenshot_path": screenshot_path,
            "summary": summary,
            "active_window": active_window,
            "ocr_text": ocr_text,
            "ui_elements": ui_elements,
        }
        self.vault.store_json("observation", f"session-{session_id or 0}-{_stamp()}", payload)
        return DesktopResult(True, summary, payload)

    def execute(self, action: DesktopActionRequest) -> DesktopResult:
        try:
            if action.action_type == "open-url" and action.url:
                webbrowser.open(action.url)
                return DesktopResult(True, f"Opened URL: {action.url}", {"url": action.url})
            if action.action_type == "web-search" and action.text:
                url = f"https://www.google.com/search?q={quote_plus(action.text)}"
                webbrowser.open(url)
                return DesktopResult(True, f"Opened web search for: {action.text}", {"url": url})
            if action.action_type == "launch-app" and action.target:
                command = _app_command(action.target)
                if not command:
                    return DesktopResult(False, f"Unsupported app target: {action.target}", {})
                subprocess.Popen(command, shell=True)
                return DesktopResult(True, f"Launched {action.target}.", {"target": action.target})
            if action.action_type == "click-target" and action.target:
                return _click_ui_target(action.target)
            if action.action_type == "run-command" and action.command:
                completed = subprocess.run(action.command, shell=True, capture_output=True, text=True, timeout=30)
                return DesktopResult(
                    completed.returncode == 0,
                    "Command executed.",
                    {"returncode": completed.returncode, "output": (completed.stdout + completed.stderr)[-2000:]},
                )
            import pyautogui

            if action.action_type == "click" and action.x is not None and action.y is not None:
                pyautogui.click(action.x, action.y)
                return DesktopResult(True, f"Clicked at {action.x}, {action.y}.", {"x": action.x, "y": action.y})
            if action.action_type == "type" and action.text:
                pyautogui.write(action.text, interval=0.01)
                return DesktopResult(True, "Typed requested text.", {"length": len(action.text)})
            if action.action_type == "hotkey" and action.text:
                pyautogui.hotkey(*[part.strip() for part in action.text.split("+")])
                return DesktopResult(True, f"Pressed hotkey {action.text}.", {"hotkey": action.text})
            if action.action_type == "scroll":
                pyautogui.scroll(action.y or -5)
                return DesktopResult(True, "Scrolled screen.", {"amount": action.y or -5})
            return DesktopResult(False, f"Unsupported action type: {action.action_type}", {})
        except Exception as exc:
            return DesktopResult(False, f"Desktop action failed safely: {exc}", {})

    def start_supervised_call(self, action_data: dict[str, Any]) -> DesktopResult:
        app = str(action_data.get("app") or "").strip().lower()
        contact = str(action_data.get("contact_or_url") or "").strip()
        if not contact:
            return DesktopResult(False, "Call target is missing.", {})
        if contact.startswith(("http://", "https://")):
            url = contact
        elif "meet" in app:
            url = f"https://meet.google.com/{contact}"
        elif "whatsapp" in app:
            phone = re.sub(r"[^0-9+]", "", contact)
            url = f"https://wa.me/{phone.lstrip('+')}" if phone else "https://web.whatsapp.com/"
        else:
            url = contact
        webbrowser.open(url)
        return DesktopResult(
            True,
            "Opened supervised call target. Read the AI/recording disclosure before speaking.",
            {"url": url, "disclosure": action_data.get("disclosure", "")},
        )

    def start_supervised_message(self, action_data: dict[str, Any]) -> DesktopResult:
        app = str(action_data.get("app") or "whatsapp").strip().lower()
        recipient = str(action_data.get("recipient") or "").strip()
        message = str(action_data.get("message") or "").strip()
        if not recipient or not message:
            return DesktopResult(False, "Message target or message body is missing.", {})
        if "whatsapp" not in app:
            return DesktopResult(False, f"Unsupported messaging app for v1: {action_data.get('app')}", {})
        phone = re.sub(r"[^0-9+]", "", recipient)
        if phone:
            url = f"https://wa.me/{phone.lstrip('+')}?text={quote_plus(message)}"
            webbrowser.open(url)
            return DesktopResult(True, "Opened supervised WhatsApp message flow. Verify the recipient and press send manually.", {"url": url})
        webbrowser.open("https://web.whatsapp.com/")
        return DesktopResult(
            True,
            "Opened WhatsApp Web in supervised mode. Select the chat manually, then send the prepared message.",
            {"url": "https://web.whatsapp.com/", "recipient": recipient, "message": message},
        )

    def start_supervised_payment(self, action_data: dict[str, Any]) -> DesktopResult:
        recipient = str(action_data.get("recipient") or "").strip()
        amount = action_data.get("amount")
        app = str(action_data.get("app") or "GPay").strip()
        upi_id = str(action_data.get("upi_id") or "").strip()
        note = str(action_data.get("note") or "").strip()
        if not recipient or amount in {None, ""}:
            return DesktopResult(False, "Payment recipient or amount is missing.", {})
        if not upi_id:
            return DesktopResult(
                False,
                "Payment approval is recorded, but a UPI ID or payment link is still required before Chinna can open the payment flow.",
                {"recipient": recipient, "amount": amount, "app": app},
            )
        query = urlencode(
            {
                "pa": upi_id,
                "pn": recipient,
                "am": amount,
                "tn": note,
                "cu": "INR",
            }
        )
        url = f"upi://pay?{query}"
        webbrowser.open(url)
        return DesktopResult(
            True,
            "Opened the supervised UPI payment flow. Verify the recipient, amount, and note before confirming.",
            {"url": url, "recipient": recipient, "amount": amount, "app": app},
        )


def _active_window() -> dict[str, Any]:
    try:
        import pygetwindow as gw

        window = gw.getActiveWindow()
        if not window:
            return {}
        return {
            "title": window.title,
            "left": window.left,
            "top": window.top,
            "width": window.width,
            "height": window.height,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _ui_elements(limit: int = 20) -> list[dict[str, Any]]:
    try:
        import uiautomation as auto

        foreground = auto.GetForegroundControl()
        controls = foreground.GetChildren()[:limit] if foreground else []
        elements: list[dict[str, Any]] = []
        for control in controls:
            rect = control.BoundingRectangle
            elements.append(
                {
                    "name": control.Name,
                    "control_type": control.ControlTypeName,
                    "rect": [rect.left, rect.top, rect.right, rect.bottom],
                }
            )
        return elements
    except Exception as exc:
        return [{"error": str(exc)}]


def _click_ui_target(target: str) -> DesktopResult:
    try:
        import pyautogui
        import uiautomation as auto

        foreground = auto.GetForegroundControl()
        if not foreground:
            return DesktopResult(False, "No active window was available for UI target clicking.", {})
        needle = target.lower().strip()
        for control in _walk_controls(foreground, limit=80):
            name = (control.Name or "").lower().strip()
            if not name or needle not in name:
                continue
            rect = control.BoundingRectangle
            x = int((rect.left + rect.right) / 2)
            y = int((rect.top + rect.bottom) / 2)
            pyautogui.click(x, y)
            return DesktopResult(True, f"Clicked UI target: {control.Name}.", {"target": control.Name, "x": x, "y": y})
        return DesktopResult(False, f"Could not find a visible UI target matching: {target}", {"target": target})
    except Exception as exc:
        return DesktopResult(False, f"UI target click failed safely: {exc}", {"target": target})


def _walk_controls(root: Any, limit: int = 80) -> list[Any]:
    found: list[Any] = []
    stack = [root]
    while stack and len(found) < limit:
        control = stack.pop(0)
        found.append(control)
        try:
            stack.extend(control.GetChildren())
        except Exception:
            continue
    return found


def _ocr_image(path: Path) -> str:
    try:
        import pytesseract

        tesseract_path = _tesseract_path()
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)
        text = pytesseract.image_to_string(str(path)).strip()
        return text[:4000]
    except Exception:
        return ""


def _tesseract_path() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _observation_summary(
    screenshot_name: str,
    active_window: dict[str, Any],
    ocr_text: str,
    ui_elements: list[dict[str, Any]],
) -> str:
    title = active_window.get("title") or "unknown window"
    element_names = [item.get("name") for item in ui_elements if item.get("name")]
    parts = [f"Captured screenshot {screenshot_name} locally in the private vault.", f"Active window: {title}."]
    if ocr_text:
        preview = " ".join(ocr_text.split())[:240]
        parts.append(f"Visible text: {preview}.")
    elif element_names:
        parts.append(f"Detected UI elements: {', '.join(element_names[:6])}.")
    else:
        parts.append("No OCR text detected yet; install Tesseract if this stays empty.")
    return " ".join(parts)


def _app_command(target: str) -> str | None:
    lowered = target.lower().strip()
    known = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "paint": "mspaint.exe",
        "chrome": "start chrome",
        "edge": "start msedge",
        "browser": "start msedge",
        "whatsapp": "start whatsapp:",
    }
    return known.get(lowered)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
