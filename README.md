# Yayin motoru

Instagram'a otomatik icerik yayinlayan kucuk bir sistem. GitHub Actions saat basi calisir,
`kuyruk.json` icinde zamani gelmis kayitlari Instagram Graph API uzerinden yayinlar.

## Nasil isler

1. Medya dosyalari `medya/` klasorunde durur. Depo herkese acik oldugu icin bu dosyalarin
   `raw.githubusercontent.com` adresleri Instagram tarafindan okunabilir — API'nin sarti bu.
2. `kuyruk.json` ne zaman ne yayinlanacagini soyler.
3. `yayinci.py` her saat kuyruga bakar, zamani gelenleri yayinlar, sonucu kuyruga isler ve
   `gunluk.md` dosyasina not duser.

## Kuyruk kaydi

```json
{
  "id": "2026-09-10-tus-kaynak",
  "tip": "resim",
  "dosyalar": ["medya/tus-kaynak-1.jpg"],
  "caption": "Metin buraya. Hashtagler de burada.",
  "zaman": "2026-09-10T19:00:00+03:00",
  "durum": "bekliyor",
  "sonuc": null
}
```

| Alan | Aciklama |
|---|---|
| `tip` | `resim`, `reels` veya `carousel` |
| `dosyalar` | `medya/` altindaki dosya yollari. Carousel icin en fazla 10 tane, sirali |
| `zaman` | ISO 8601, saat dilimiyle. Gecmis bir zaman = ilk calismada yayinlanir |
| `durum` | `bekliyor` yayinlanir · `taslak` beklemede kalir · `yayinlandi` / `hata` motor tarafindan yazilir |

## Medya kurallari (Instagram'in sarti)

- Feed gorseli: **yalnizca JPEG**. PNG ve WebP reddedilir.
- En-boy orani 4:5 ile 1.91:1 arasi.
- Video: MP4, H.264. Reels icin 15 dakikaya kadar.
- Gunluk sinir: 24 saatte 100 gonderi. Carousel tek gonderi sayilir.

## Gerekli Secret'lar

| Ad | Zorunlu | Ne ise yarar |
|---|---|---|
| `IG_ACCESS_TOKEN` | evet | Instagram uzun omurlu erisim token'i |
| `GH_PAT` | hayir | Tazelenen token'i otomatik olarak Secret'a yazar. Yoksa 60 gunde bir elle yenilenir |

## Elle calistirma

Actions sekmesi → **Instagram yayin** → **Run workflow**. Kuyrukta zamani gelmis bir sey
yoksa hicbir sey yapmaz, guvenlidir.
