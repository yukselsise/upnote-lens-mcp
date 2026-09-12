"""Read-only access to the local UpNote SQLite database.

Everything here is read-only by design. The connection is opened with
``mode=ro`` so we never take a write lock or risk corrupting the file that
UpNote keeps in sync with the cloud.

Bu fork'ta ``immutable=1`` kaldirildi: UpNote veritabani WAL modunda
calisiyor ve ``immutable=1`` SQLite'a "-wal dosyasina hic bakma" dedigi
icin son gunlerin notlari gorunmez oluyordu (olcum: 222 yerine 225 not,
en yeni not 6 gun eski). ``mode=ro`` WAL'i okur; yazma yapmaz.

Facts verified against a real UpNote DB (macOS, ~5.7k notes):
- A note is "valid" when ``trashed=0 AND deleted=0 AND COALESCE(isTemplate,0)=0``.
  ``isTemplate`` is usually NULL (not 0), so ``isTemplate=0`` would drop everything.
- Timestamps (``updatedAt``/``createdAt``) are millisecond epochs stored as DOUBLE.
- ``notes.notebookLinks`` is empty for every row. The real note<->notebook
  relationship lives in ``notebooks.notes`` (a JSON array of note ids).
- ``tags.notes`` is likewise a JSON array of note ids.
"""

from __future__ import annotations

import json
import os
import platform
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

# A valid, user-facing note: not trashed, not deleted, not a template.
VALID_NOTE = "trashed = 0 AND deleted = 0 AND COALESCE(isTemplate, 0) = 0"

# Human-readable local time derived from the millisecond epoch.
_UPDATED_AT = "datetime(updatedAt / 1000, 'unixepoch', 'localtime')"


def _default_db_path() -> Path:
    """Best-effort default DB location per OS.

    macOS is verified. The Windows path is a best guess (UpNote is an Electron
    app, so its data lives under %APPDATA%) and is NOT verified — if it's wrong,
    set UPNOTE_LENS_DB explicitly.
    """
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData/Roaming")
        return Path(appdata) / "UpNote" / "upnote.sqlite3"
    return (
        Path.home()
        / "Library/Containers/com.getupnote.desktop/Data/Library/Application Support"
        / "UpNote/upnote.sqlite3"
    )


def db_path() -> Path:
    """Resolve the DB path, allowing an override via UPNOTE_LENS_DB."""
    override = os.environ.get("UPNOTE_LENS_DB")
    return Path(override).expanduser() if override else _default_db_path()


@contextmanager
def _connect():
    path = db_path()
    if not path.exists():
        raise FileNotFoundError(
            f"UpNote database not found at: {path}\n"
            "Set UPNOTE_LENS_DB to point at your upnote.sqlite3 if it lives elsewhere."
        )
    # Salt okunur, ama immutable DEGIL: immutable=1 WAL'i gizler ve en son
    # notlar kaybolur. mode=ro yazma kilidi almaz, checkpoint tetiklemez.
    uri = "file:" + quote(str(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# Noktali/noktasiz i ailesinin tamami tek sinifa indirgeniyor: I, İ, ı, i -> i.
#
# Neden "Turkce dogru" olan I->ı esleme degil: Yuksel'in notlari karisik dilli.
# Ingilizce "Istanbul" basligindaki I'yi Turkce kurala gore ı'ya katlarsak,
# ASCII klavyeyle yazilan "istanbul" sorgusu artik o notu bulamaz — olculdu,
# eski LIKE aramasinin buldugu 6 not sifira dusuyordu. Ters yon de ayni sekilde
# kayipli. Tek sinifa indirgemek her iki yazimi da esler ve hicbir eslesmeyi
# kaybettirmez; Unicode'un kok katlamasi da ayni yolu izler.
#
# Python'un .lower() metodu burada tek basina yetmez: "İ".lower() iki karakter
# uretir ve uzunlugu bozar (snippet konumlari kayar).
_TR_CASE = {"I": "i", "İ": "i", "ı": "i"}

# Ikinci kademe (fuzzy): aksan dusurme, "gevsek" eslesme icin.
_TR_ASCII = {
    "ı": "i",
    "ş": "s",
    "ğ": "g",
    "ü": "u",
    "ö": "o",
    "ç": "c",
    "â": "a",
    "î": "i",
    "û": "u",
}


def _tr_fold(s: str, ascii_fold: bool = False) -> str:
    """Turkce duyarli kucuk harfe cevirme.

    Karakter karakter calisir; cikti girdiyle **ayni uzunlukta** olur. Bu sart,
    katlanmis metinde bulunan konumun orijinal metne birebir uymasi icin gerekli
    (snippet dogru yerden kesilsin diye).

    ascii_fold=True ise ayrica aksanlar dusurulur.
    """
    out = []
    for ch in s:
        c = _TR_CASE.get(ch)
        if c is None:
            low = ch.lower()
            # Bazi harfler kucultulunce birden fazla karaktere acilir; uzunlugu
            # korumak icin ilkini aliyoruz.
            c = low if len(low) == 1 else (low[0] if low else ch)
        if ascii_fold:
            c = _TR_ASCII.get(c, c)
        out.append(c)
    return "".join(out)


def _snippet(
    text: str | None, query: str, width: int = 160, fuzzy: bool = False
) -> str:
    """A short context window around the first match of `query`."""
    if not text:
        return ""
    flat = " ".join(text.split())
    # Konumu katlanmis metinde buluyoruz ama dilimi orijinalden aliyoruz;
    # _tr_fold uzunlugu korudugu icin indeksler ortusuyor.
    pos = _tr_fold(flat, fuzzy).find(_tr_fold(query, fuzzy))
    if pos < 0:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, pos - width // 3)
    end = min(len(flat), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flat) else ""
    return prefix + flat[start:end] + suffix


def _ids_in_clause(ids: list[str]) -> tuple[str, list[str]]:
    placeholders = ",".join("?" for _ in ids)
    return placeholders, ids


# --- read tools ------------------------------------------------------------


def search_notes(query: str, limit: int = 20, fuzzy: bool = False) -> list[dict]:
    """Turkish-aware substring search over title and body.

    Matching happens in Python, not in SQL: SQLite'in LIKE operatoru yalnizca
    ASCII'de buyuk/kucuk harf duyarsizdir, yani "İstanbul" ile "istanbul" ya da
    "IŞIK" ile "ışık" eslesmez. Gecerli notlarin tamamini cekip _tr_fold ile
    karsilastiriyoruz; birkac yuz notluk bir veritabani icin tam tarama ucuz.

    fuzzy=True aksanlari da dusurur ("gevsek" eslesme): "sarki" -> "şarkı".
    """
    if not query or not query.strip():
        return []
    sql = f"""
        SELECT id, title, {_UPDATED_AT} AS updated_at, text
        FROM notes
        WHERE {VALID_NOTE}
        ORDER BY updatedAt DESC
    """
    with _connect() as conn:
        rows = conn.execute(sql).fetchall()

    needle = _tr_fold(query, fuzzy)
    out: list[dict] = []
    for r in rows:
        title = r["title"] or ""
        text = r["text"] or ""
        if needle in _tr_fold(title, fuzzy) or needle in _tr_fold(text, fuzzy):
            out.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "updated_at": r["updated_at"],
                    "snippet": _snippet(text, query, fuzzy=fuzzy),
                }
            )
            if len(out) >= limit:
                break
    return out


def get_note(note_id: str, include_html: bool = False) -> dict | None:
    """Full title + body text of a single note (optionally raw HTML too)."""
    sql = f"""
        SELECT id, title, text, html, {_UPDATED_AT} AS updated_at
        FROM notes
        WHERE id = ?
    """
    with _connect() as conn:
        r = conn.execute(sql, (note_id,)).fetchone()
    if r is None:
        return None
    result = {
        "id": r["id"],
        "title": r["title"],
        "text": r["text"],
        "updated_at": r["updated_at"],
    }
    if include_html:
        result["html"] = r["html"]
    return result


def list_recent(limit: int = 20) -> list[dict]:
    """Most recently updated valid notes."""
    sql = f"""
        SELECT id, title, {_UPDATED_AT} AS updated_at
        FROM notes
        WHERE {VALID_NOTE}
        ORDER BY updatedAt DESC
        LIMIT ?
    """
    with _connect() as conn:
        rows = conn.execute(sql, (limit,)).fetchall()
    return [dict(r) for r in rows]


def list_notebooks() -> list[dict]:
    """All notebooks with their note counts (from notebooks.notes JSON)."""
    sql = """
        SELECT id, title, parent
        FROM notebooks
        WHERE deleted = 0
        ORDER BY title COLLATE NOCASE
    """
    with _connect() as conn:
        rows = conn.execute(sql).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "note_count": len(_notebook_note_ids(conn, r["id"])),
                "parent": r["parent"] or None,
            }
            for r in rows
        ]


def list_notes_in_notebook(notebook_id: str, limit: int = 50) -> list[dict]:
    """Notes belonging to a notebook, resolved via notebooks.notes JSON."""
    with _connect() as conn:
        nb = conn.execute(
            "SELECT id FROM notebooks WHERE id = ?", (notebook_id,)
        ).fetchone()
        if nb is None:
            return []
        note_ids = _notebook_note_ids(conn, notebook_id)
        if not note_ids:
            return []
        placeholders, params = _ids_in_clause(note_ids)
        sql = f"""
            SELECT id, title, {_UPDATED_AT} AS updated_at
            FROM notes
            WHERE id IN ({placeholders}) AND {VALID_NOTE}
            ORDER BY updatedAt DESC
            LIMIT ?
        """
        rows = conn.execute(sql, [*params, limit]).fetchall()
    return [dict(r) for r in rows]


def list_tags() -> list[dict]:
    """All tags with their note counts (from tags.notes JSON)."""
    sql = """
        SELECT id, title, notes
        FROM tags
        WHERE deleted = 0
        ORDER BY title COLLATE NOCASE
    """
    with _connect() as conn:
        rows = conn.execute(sql).fetchall()
    out = []
    for r in rows:
        try:
            note_ids = json.loads(r["notes"]) if r["notes"] else []
        except (ValueError, TypeError):
            note_ids = []
        out.append(
            {"id": r["id"], "title": r["title"], "note_count": len(note_ids)}
        )
    return out


def list_notes_by_tag(tag_title: str, limit: int = 50) -> list[dict]:
    """Notes carrying a tag, matched by tag title (via tags.notes JSON)."""
    with _connect() as conn:
        tag = conn.execute(
            "SELECT id, title, notes FROM tags WHERE title = ? COLLATE NOCASE",
            (tag_title,),
        ).fetchone()
        if tag is None:
            return []
        try:
            note_ids = json.loads(tag["notes"]) if tag["notes"] else []
        except (ValueError, TypeError):
            note_ids = []
        if not note_ids:
            return []
        placeholders, params = _ids_in_clause(note_ids)
        sql = f"""
            SELECT id, title, {_UPDATED_AT} AS updated_at
            FROM notes
            WHERE id IN ({placeholders}) AND {VALID_NOTE}
            ORDER BY updatedAt DESC
            LIMIT ?
        """
        rows = conn.execute(sql, [*params, limit]).fetchall()
    return [dict(r) for r in rows]


def _json_ids(raw: object) -> list[str]:
    """JSON dizisi tutan bir kolonu guvenle coz. Bos/NULL/bozuk -> []."""
    try:
        ids = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []
    return ids if isinstance(ids, list) else []


def _note_ids_of(row: sqlite3.Row) -> list[str]:
    """notebooks.notes / tags.notes JSON dizisini guvenle coz."""
    return _json_ids(row["notes"])


def _notebook_note_ids(conn: sqlite3.Connection, notebook_id: str) -> list[str]:
    """Bir defterin not id'leri.

    Bu UpNote surumunde iliski ``lists`` tablosunda duruyor: ``notebooks_<id>``
    anahtarli satirin ``content`` alani not id'lerinden olusan bir JSON dizisi.
    ``notebooks.notes`` bu veritabaninda 16 defterin **hepsinde** bos ([]);
    upstream'in dayandigi alan artik doldurulmuyor. Eski surumler icin ona
    geri donus olarak bakiyoruz.
    """
    r = conn.execute(
        "SELECT content FROM lists WHERE id = ? AND deleted = 0",
        (f"notebooks_{notebook_id}",),
    ).fetchone()
    ids = _json_ids(r["content"]) if r is not None else []
    if ids:
        return ids
    nb = conn.execute(
        "SELECT notes FROM notebooks WHERE id = ?", (notebook_id,)
    ).fetchone()
    return _note_ids_of(nb) if nb is not None else []


def notebooks_of_note(note_id: str) -> list[dict]:
    """Notu iceren defterler (ters arama, notebooks.notes JSON'undan).

    URL semasi defteri **adla** esledigi icin title da donuyor.
    """
    sql = """
        SELECT id, title
        FROM notebooks
        WHERE deleted = 0
        ORDER BY title COLLATE NOCASE
    """
    with _connect() as conn:
        rows = conn.execute(sql).fetchall()
        return [
            {"id": r["id"], "title": r["title"]}
            for r in rows
            if note_id in _notebook_note_ids(conn, r["id"])
        ]


def find_created_since(title: str, since_ms: float) -> dict | None:
    """Verilen basliga sahip ve `since_ms`'ten sonra olusmus en yeni not.

    supersede_note'un yoklama dongusu icin: yeni notun DB'ye gercekten
    dustugunu dogrulamaya yariyor. Baslik birebir eslesir -- UpNote ardisik
    URL'lerde basligi bozabiliyor (bkz. docs/url-limits.md) ve o durumda
    bulunamamasi istenen davranis.
    """
    sql = f"""
        SELECT id, title, createdAt, {_UPDATED_AT} AS updated_at
        FROM notes
        WHERE {VALID_NOTE} AND title = ? AND createdAt >= ?
        ORDER BY createdAt DESC
        LIMIT 1
    """
    with _connect() as conn:
        r = conn.execute(sql, (title, since_ms)).fetchone()
    if r is None:
        return None
    return {"id": r["id"], "title": r["title"], "updated_at": r["updated_at"]}
