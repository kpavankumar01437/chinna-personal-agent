from __future__ import annotations

import base64
import ctypes
import json
import os
import platform
import zipfile
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PrivateVault:
    def __init__(self, app_name: str = "PavanPrivateApp"):
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        self.root = Path(local) / app_name
        self.data_dir = self.root / "data"
        self.screenshot_dir = self.root / "screenshots"
        self.call_dir = self.root / "calls"
        self.export_dir = self.root / "exports"
        self.desktop_entry = Path.home() / "OneDrive" / "Desktop" / "PavanPrivate app.url"
        if not self.desktop_entry.parent.exists():
            self.desktop_entry = Path.home() / "Desktop" / "PavanPrivate app.url"

    def ensure(self) -> dict[str, str | bool]:
        for path in [self.root, self.data_dir, self.screenshot_dir, self.call_dir, self.export_dir]:
            path.mkdir(parents=True, exist_ok=True)
        self._write_desktop_entry()
        return {
            "vault_path": str(self.root),
            "desktop_entry": str(self.desktop_entry),
            "onedrive_safe": "onedrive" not in str(self.root).lower(),
            "encrypted": platform.system() == "Windows",
        }

    def store_json(self, category: str, name: str, payload: dict[str, Any]) -> Path:
        self.ensure()
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in name)[:80]
        path = self.data_dir / f"{category}-{safe_name}.dpapi"
        content = json.dumps(
            {"stored_at": datetime.now(timezone.utc).isoformat(), "payload": payload},
            ensure_ascii=True,
            indent=2,
        ).encode("utf-8")
        path.write_bytes(self.protect(content))
        return path

    def read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(self.unprotect(path.read_bytes()).decode("utf-8"))

    def list_records(self) -> list[dict[str, Any]]:
        self.ensure()
        records: list[dict[str, Any]] = []
        for path in sorted(self.data_dir.glob("*.dpapi"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = self.read_json(path)
                records.append({"path": str(path), **data})
            except Exception:
                records.append({"path": str(path), "stored_at": "", "payload": {"error": "Unable to decrypt"}})
        return records

    def delete(self, kind: str = "all", value: str | None = None) -> int:
        self.ensure()
        targets: list[Path] = []
        if kind == "all":
            targets = [p for p in self.root.rglob("*") if p.is_file()]
        elif kind == "screenshots":
            targets = list(self.screenshot_dir.glob("*"))
        elif kind == "calls":
            targets = list(self.call_dir.glob("*"))
        elif kind == "record" and value:
            candidate = Path(value)
            if candidate.exists() and self.root in candidate.parents:
                targets = [candidate]
        deleted = 0
        for path in targets:
            try:
                path.unlink()
                deleted += 1
            except OSError:
                pass
        self._write_desktop_entry()
        return deleted

    def export(self) -> Path:
        self.ensure()
        export_path = self.export_dir / f"chinna-private-export-{_stamp()}.zip"
        with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "README.txt",
                "Chinna Private local export. Decrypted JSON records are included for your personal review.\n",
            )
            for path in sorted(self.data_dir.glob("*.dpapi")):
                try:
                    data = self.read_json(path)
                    archive.writestr(f"records/{path.stem}.json", json.dumps(data, indent=2, ensure_ascii=True))
                except Exception as exc:
                    archive.writestr(f"records/{path.stem}-error.txt", f"Unable to decrypt record: {exc}")
            for folder_name, folder in [("screenshots", self.screenshot_dir), ("calls", self.call_dir)]:
                for path in sorted(folder.glob("*")):
                    if path.is_file():
                        archive.write(path, f"{folder_name}/{path.name}")
        return export_path

    def protect(self, data: bytes) -> bytes:
        if platform.system() != "Windows":
            return base64.b64encode(data)
        return _crypt_protect(data)

    def unprotect(self, data: bytes) -> bytes:
        if platform.system() != "Windows":
            return base64.b64decode(data)
        return _crypt_unprotect(data)

    def _write_desktop_entry(self) -> None:
        try:
            self.desktop_entry.parent.mkdir(parents=True, exist_ok=True)
            url = self.root.as_uri()
            self.desktop_entry.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")
        except Exception:
            pass


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_from_bytes(data: bytes) -> DATA_BLOB:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _bytes_from_blob(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _crypt_protect(data: bytes) -> bytes:
    in_blob = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise OSError("CryptProtectData failed")
    return _bytes_from_blob(out_blob)


def _crypt_unprotect(data: bytes) -> bytes:
    in_blob = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise OSError("CryptUnprotectData failed")
    return _bytes_from_blob(out_blob)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
