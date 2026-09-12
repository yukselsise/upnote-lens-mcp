# WAL ölçümü ve salt okunur bağlantı kararı

Tarih: 2026-09-12. Ortam: macOS, UpNote masaüstü, `upnote.sqlite3` WAL modunda.

## Sorun

Upstream `db.py` bağlantıyı `?mode=ro&immutable=1` ile açıyordu. `immutable=1`
SQLite'a "bu dosya değişmiyor, `-wal` dosyasına hiç bakma" der. UpNote'un
veritabanı WAL modunda çalıştığı ve checkpoint nadiren olduğu için son
günlerin notları hiç okunmuyordu.

Bu kurulumda `-wal` 4.15 MB ve ana dosyadan 6 gün daha yeniydi. UpNote
**çıkarken de checkpoint yapmıyor**; yani sorun uygulama kapalıyken de sürüyor.

## Ölçüm: iki URI yan yana

Aynı veritabanı, aynı sorgular, UpNote açıkken:

| | `mode=ro&immutable=1` | `mode=ro` |
|---|---|---|
| `PRAGMA journal_mode` | `delete` | `wal` |
| `VALID_NOTE` sayısı | 222 | 225 |
| `trashed=0 AND deleted=0` | 223 | 226 |
| en yeni notun tarihi | 2026-09-02 23:35 | 2026-09-08 16:30 |

6 günlük not görünmüyordu. En yeni 5 notun listesi de tamamen farklıydı.

### Canlı doğrulama

UpNote'ta elle "WAL test" notu oluşturuldu. Saniyeler içinde:

- `mode=ro` → notu görüyor, toplam 225 → 226.
- `mode=ro&immutable=1` → notu **görmüyor**, toplam hâlâ 222.

## Seçenek tablosu

| seçenek | UpNote kapalı | `-shm` yokken | WAL görünür |
|---|---|---|---|
| `mode=ro` | çalışır | çalışır (`-shm`'yi kurar) | evet, 226 |
| `mode=ro&readonly_shm=1` | çalışır | `unable to open database file` | evet, 226 |
| `mode=ro&immutable=1` | çalışır | çalışır | hayır, 222 |

`readonly_shm=1` `-shm`'nin mtime'ına dokunmaz, ama dosya yoksa (UpNote hiç
açılmamışsa, ya da temiz kapanışta silinmişse) tamamen başarısız olur.

## Karar

**`mode=ro`** kullanılıyor. Gerekçe: her senaryoda çalışır, WAL'ı görür,
yazma kilidi almaz.

### `-shm` dokunuşu hakkında

UpNote kapalıyken WAL'ı okuyan ilk süreç paylaşımlı bellek indeksini kendisi
kurar; bu sırada `-shm` dosyasının mtime'ı tazelenir (ölçümde 11 Eyl 10:59 →
12 Eyl 20:46). Bu beklenen ve kabul edilen davranış:

- Bir okuma öncesi/sonrası **her üç dosyanın da MD5'i birebir aynı** kaldı
  (`upnote.sqlite3`, `-wal`, `-shm`). İçerik değişmiyor, sadece mtime.
- `-shm` veri değildir: `-wal`'dan yeniden üretilen bir indekstir ve SQLite
  son bağlantı kapanınca kendisi siler.
- Ana veritabanı ve `-wal` hiç değişmedi; checkpoint tetiklenmedi.

### Salt okunurluk doğrulaması

```
UPDATE notes SET title=title WHERE 0
→ sqlite3.OperationalError: attempt to write a readonly database
```

## Kırmızı çizgi (CLAUDE.md'deki nihai ifade)

> `upnote.sqlite3` ve `-wal` dosyalarına asla yazma, checkpoint yapma. `-shm`
> SQLite'ın yeniden üretilebilir paylaşımlı bellek indeksidir; salt okunur
> bağlantının ona dokunması (mtime tazelenmesi) beklenen ve kabul edilen
> davranıştır — içerik değişmez, MD5 ile doğrulandı 2026-09-12.
