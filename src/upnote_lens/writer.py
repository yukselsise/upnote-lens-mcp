"""Write side: drive UpNote through its ``upnote://`` URL scheme.

We never touch the SQLite DB for writes — UpNote syncs to the cloud, so direct
DB writes risk breaking sync. Note creation/navigation goes through the
x-callback-url endpoints instead, launched via macOS ``open``.

URL formats and the launch approach are adapted from chadthornton/upnote-mcp
(MIT). See LICENSE for attribution.
"""

from __future__ import annotations

import os
import platform
import subprocess
from urllib.parse import quote, urlencode

# Icerik ust siniri. Olcum (macOS, 2026-09-12): 512 KB'lik bir not sorunsuz
# olusuyor, 1 MB'lik ise `open` cagrisinda patliyor:
#   OSError: [Errno 7] Argument list too long: 'open'
# Sinir UpNote'un URL semasindan degil, isletim sisteminden geliyor --
# `open` execve() ile calisir ve tum argv+env ARG_MAX icine sigmak zorunda
# (bu makinede 1 MiB). Yuzde kodlamasi metni sisiriyor: saf ASCII'de ~1.11x,
# ama her Turkce karakter (UTF-8'de 2 bayt) 6 karaktere, emoji 12 karaktere
# cikabiliyor. En kotu durumda her bayt "%XX" olur, yani 3x.
#
# 256 KB esigi en kotu 3x sismede bile ~768 KB URL demek; ARG_MAX'a 256 KB
# pay kaliyor. Kanitlanmis 512 KB'in yarisi.
MAX_NOTE_BYTES = 256 * 1024

_CREATE_NOTE = "upnote://x-callback-url/note/new"
_OPEN_NOTE = "upnote://x-callback-url/openNote"
_OPEN_NOTEBOOK = "upnote://x-callback-url/openNotebook"


def _build_url(base: str, params: dict) -> str:
    """Build a URL, dropping empty values and normalizing booleans."""
    clean: dict[str, str] = {}
    for key, value in params.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        clean[key] = str(value)
    query = urlencode(clean, quote_via=quote)
    return f"{base}?{query}" if query else base


def _open_url(url: str) -> str:
    """Hand the URL to the OS so UpNote's scheme handler picks it up."""
    system = platform.system()
    if system == "Darwin":
        # Pass the URL as a separate argv entry (no shell) — it is already
        # percent-encoded, so there is nothing for a shell to misinterpret.
        subprocess.run(["open", url], check=True)
    elif system == "Windows":
        # os.startfile routes the URL through the registered scheme handler.
        os.startfile(url)  # type: ignore[attr-defined]  # Windows-only
    else:
        raise RuntimeError(
            f"Launching upnote:// URLs is not supported on {system}; "
            "only macOS and Windows are supported."
        )
    return url


def _check_size(content: str | None) -> None:
    """Icerik ARG_MAX sinirina takilacaksa, URL'yi hic acmadan hata ver."""
    if not content:
        return
    size = len(content.encode("utf-8"))
    if size > MAX_NOTE_BYTES:
        raise ValueError(
            f"Not icerigi cok uzun: {size} bayt, ust sinir {MAX_NOTE_BYTES} bayt. "
            "Notu birden fazla parcaya bolun.\n"
            f"Note content too long: {size} bytes, limit {MAX_NOTE_BYTES} bytes. "
            "Split the note into smaller parts."
        )


# --- write tools -----------------------------------------------------------


def create_note(
    title: str | None = None,
    content: str | None = None,
    notebook: str | None = None,
    markdown: bool = True,
    new_window: bool = False,
) -> str:
    """Create a note. Returns the upnote:// URL that was launched.

    Note: UpNote's note/new endpoint cannot set tags — there is no tag
    parameter, and hashtags injected into the body stay as plain text rather
    than becoming real tags. Tag a note manually in the app afterwards.
    """
    _check_size(content)
    params: dict[str, object] = {
        "title": title,
        "text": content,
        "notebook": notebook,
        "markdown": markdown,
    }
    if new_window:
        params["new_window"] = True
    return _open_url(_build_url(_CREATE_NOTE, params))


def open_note(note_id: str, new_window: bool = False) -> str:
    """Open an existing note by id. Returns the launched URL."""
    params: dict[str, object] = {"noteId": note_id}
    if new_window:
        params["new_window"] = True
    return _open_url(_build_url(_OPEN_NOTE, params))


def open_notebook(notebook_id: str) -> str:
    """Open a notebook by id. Returns the launched URL."""
    return _open_url(_build_url(_OPEN_NOTEBOOK, {"notebookId": notebook_id}))
