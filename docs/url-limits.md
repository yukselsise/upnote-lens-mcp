# URL uzunluk sınırı ölçümü

Tarih: 2026-09-12. macOS, UpNote açık. `writer.create_note` doğrudan çağrıldı,
her boyuttan sonra 3–8 saniye beklendi, sonuç **veritabanından** doğrulandı
(sadece `open`'ın hatasız dönmesine güvenilmedi).

İçerik her boyutta `BASLANGIC-<n>` ile başlayıp `BITIS-<n>` ile bitiyor;
gövdede numaralı satırlar var, böylece kesilme gözle görünür olurdu.

## Sonuçlar

| içerik | URL uzunluğu | `open` | DB'deki gövde | `BITIS` işareti |
|---|---|---|---|---|
| 1 KB | 1.241 | OK | 1.041 | var |
| 8 KB | 9.219 | OK | 8.209 | var |
| 32 KB | 36.580 | OK | 32.786 | var |
| 64 KB | 73.056 | OK | 65.557 | var |
| 128 KB | 146.011 | OK | 131.091 | var |
| 256 KB | 291.921 | OK | 262.163 | var |
| 512 KB | 583.743 | OK | 524.307 | var |
| 1 MB | — | **hata** | not oluşmadı | — |

1 MB'de çıkan hata:

```
OSError: [Errno 7] Argument list too long: 'open'
```

**Hiçbir boyutta sessiz kesilme olmadı.** Not ya tam oluşuyor ya da hiç
oluşmuyor. Bu iyi haber: kısmi/bozuk not riski yok.

## Sınır nereden geliyor

UpNote'un URL şemasından değil, işletim sisteminden. `open` komutu `execve()`
ile çalışır ve argv+env toplamı `ARG_MAX` içine sığmak zorunda:

```
getconf ARG_MAX = 1048576   (1 MiB)
```

1 MB'lik içerik yüzde kodlamasından sonra ~1,16 M karakter URL üretti, sınırı
aştı.

## Yüzde kodlaması şişmesi

- Saf ASCII: ~1,11x
- Türkçe metin: **3,00x** ölçüldü (`ışğüöçİĞÜÖÇ` tekrarı, 2.200 bayt → 6.605
  karakter). Her UTF-8 baytı `%XX` olduğu için teorik en kötü durum da 3x.

## Eşik kararı

`writer.MAX_NOTE_BYTES = 256 * 1024`

Gerekçe: en kötü 3x şişmede bile ~768 KB URL demek, ARG_MAX'a 256 KB pay
kalıyor. Kanıtlanmış 512 KB'in yarısı. İçerik UTF-8 bayt cinsinden ölçülüyor
(karakter değil), çünkü sınırı belirleyen bayt sayısı.

Eşik aşılırsa `create_note` **hiçbir URL açmadan** `ValueError` fırlatır,
mesaj Türkçe ve İngilizce iki satır.

## Yan bulgu: art arda URL'lerde başlık bozulması

Testte 3 saniye aralıkla gönderilen URL'lerden birinde başlık
`STE[TEST] url-length-65536` olarak oluştu — bir önceki URL'nin kuyruğundan
sızan karakterler. UpNote büyük bir URL'yi işlerken yenisi gelirse yarışma
oluyor.

Tek tek kullanımda sorun değil, ama toplu not oluşturmada çağrılar arasına
birkaç saniye koymak gerekir. `create_note` kendi başına bekleme yapmaz.

`supersede_note` bu yarışı kapatıyor: iki URL'yi (`note/new` ve `openNote`)
peş peşe göndermek yerine, arada `_wait_for_note` ile yeni notun veritabanında
göründüğünü doğruluyor — 0,5 saniye aralıkla, en fazla 15 saniye. Doğrulama
başarısızsa eski not hiç açılmıyor ve sonuç `status: "created_unverified"`
dönüyor. Ölçüm: normal durumda bekleme 0,6 saniye; hiç oluşmayan bir başlıkta
15,3 saniyede `None`.
