# upnote-lens-mcp — çalışma notları

UpNote'un yerel SQLite veritabanını **salt okunur** okuyan, yazma işlemlerini
**yalnızca** `upnote://x-callback-url` URL şemasıyla yapan bir MCP sunucusu.
Bu ikili yapı değişmez.

## Kırmızı çizgiler

1. **`upnote.sqlite3` ve `-wal` dosyalarına asla yazma, checkpoint yapma.**
   Hiçbir `UPDATE`/`INSERT`/`DELETE`, dosyayı değiştirecek hiçbir `PRAGMA`
   (`wal_checkpoint` dahil). Bağlantı her zaman `mode=ro`.

   `-shm` SQLite'ın yeniden üretilebilir paylaşımlı bellek indeksidir; salt
   okunur bağlantının ona dokunması (mtime tazelenmesi) beklenen ve kabul
   edilen davranıştır — içerik değişmez, MD5 ile doğrulandı 2026-09-12.

2. Yazma tarafında yalnızca resmi uç noktalar: `note/new`, `notebook/new`,
   `openNote`, `openNotebook`, `tag/view`, `openFilter`, `view`. Başka yol
   icat etme.
3. `subprocess` çağrıları shell'siz kalsın (`["open", url]`).
4. Yeni bağımlılık ekleme; `mcp` paketi yeter.
5. Kod yorumları ve dokümantasyon Türkçe; araç adları ve docstring'leri
   İngilizce kalsın (Claude bunları okuyor).

## Dosya haritası

| dosya | işi |
|---|---|
| `src/upnote_lens/db.py` | Salt okunur SQLite erişimi, arama, ters aramalar |
| `src/upnote_lens/writer.py` | `upnote://` URL şeması, `create_note`, `supersede_note` |
| `src/upnote_lens/server.py` | MCP araç kaydı (11 araç), stdio girişi |
| `docs/wal-notes.md` | WAL ölçümü ve `mode=ro` kararının gerekçesi |
| `docs/url-limits.md` | URL uzunluk ölçümü, `MAX_NOTE_BYTES` eşiğinin çıkışı |
| `docs/sonraki-oturum.md` | Açık işler (Görev 8: mcp 2.x geçişi) |

## Şema gerçekleri — bu UpNote sürümünde

Upstream'in dayandığı alanların bir kısmı artık doldurulmuyor. Ölçüldü
2026-09-12, 225 geçerli notluk bir veritabanında.

- **`notebooks.notes` boş** — 16 defterin hepsinde `[]`. Gerçek defter–not
  ilişkisi `lists` tablosunda: `notebooks_<notebookId>` anahtarlı satırın
  `content` alanı not id'lerinden oluşan JSON dizisi. 15 böyle satır var,
  219 notu eşliyor. Eski sürümler için `notebooks.notes`'a geri dönüş duruyor.
- **`tags.notes` boş** — 1137 tag'in hepsinde `[]`. Gerçek tag ilişkisi
  `notes.tagLinks`'te ve **slug** biçiminde (`miguel-caló`, `tango`).
- **slug = başlıktan `#` düşür + küçük harf.** `#Miguel-Caló` →
  `miguel-caló`. 76 notun 1.534 tagLink referansının tamamı bu kuralla
  eşleşti (%100), çakışan slug yok.
- **`notes.notebookLinks` boş** — 238 satırın hepsinde. Kullanma.
- **`isTemplate` NULL olabilir**, 0 değil. `isTemplate = 0` yazarsan her şeyi
  elersin; `COALESCE(isTemplate, 0) = 0` kullan. Geçerli not tanımı
  `VALID_NOTE` sabitinde.
- **Timestamp'ler milisaniye epoch, DOUBLE** (`updatedAt`, `createdAt`).
- **`journal_mode` = `wal`** ve **UpNote çıkarken checkpoint yapmıyor** —
  `-wal` ana dosyadan günlerce yeni kalabilir. Bu yüzden `immutable=1`
  kullanılamaz: SQLite'a `-wal`'a bakmama der ve son günlerin notları
  görünmez olur (ölçümde 222 yerine 225, en yeni not 6 gün eski).

## Bağımlılık durumu

`pyproject.toml` `mcp>=1.2.0,<2` ile pinli. `uv` kısıtsız bırakılınca mcp
2.2.0 çekiyor ve sunucu **hiç import edilemiyor**:

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x,
where FastMCP was renamed to MCPServer
```

Pin geçici. **Açık iş — Görev 8: mcp 2.x (MCPServer API) geçişi**, ayrıntısı
`docs/sonraki-oturum.md`'de. Yalnızca `server.py` etkileniyor.

## Test komutları

```bash
# not sayısı (WAL görünür olmalı; immutable=1 ile 3 not eksik gelirdi)
uv run python -c "from upnote_lens import db; print(len(db.list_recent(500)))"

# WAL gerçekten okunuyor mu (beklenen: wal)
uv run python -c "from upnote_lens import db
with db._connect() as c: print(c.execute('PRAGMA journal_mode').fetchone()[0])"

# salt okunurluk (beklenen: attempt to write a readonly database)
uv run python -c "from upnote_lens import db
with db._connect() as c: c.execute('UPDATE notes SET title=title WHERE 0')"

# defter ve tag ilişkileri (0 dönerse şema yine değişmiş demektir)
uv run python -c "from upnote_lens import db; \
  print(sum(n['note_count'] for n in db.list_notebooks()), 'not in defterler'); \
  print(len(db.list_tags()), 'kullanilan tag')"

# Türkçe arama: ikisi de aynı sayıyı vermeli
uv run python -c "from upnote_lens import db; \
  print(len(db.search_notes('istanbul')), len(db.search_notes('İSTANBUL')))"

# MCP sunucusu stdio'da ayağa kalkıyor mu (11 araç listelenmeli)
uv run python -c "import asyncio, upnote_lens.server as s; \
  print(sorted(t.name for t in asyncio.run(s.mcp.list_tools())))"
```

Veritabanına yazan bir test yazma. Not oluşturan testler UpNote'ta gerçek
not bırakır; başlıklarını `[TEST]` ile başlat ve sonra sil.
