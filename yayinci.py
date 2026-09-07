#!/usr/bin/env python3
"""
Instagram yayin motoru.

kuyruk.json icindeki zamani gelmis icerikleri Instagram'a yayinlar.
GitHub Actions tarafindan saatte bir calistirilir.

Gerekli ortam degiskenleri:
  IG_ACCESS_TOKEN  - Instagram uzun omurlu erisim token'i (GitHub Secret)
  RAW_BASE         - medya dosyalarinin herkese acik kok URL'i
                     ornek: https://raw.githubusercontent.com/KULLANICI/DEPO/main
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://graph.instagram.com/v23.0"
KUYRUK = "kuyruk.json"
GUNLUK = "gunluk.md"

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
RAW_BASE = os.environ.get("RAW_BASE", "").strip().rstrip("/")

log_satirlari = []


def log(mesaj):
    print(mesaj, flush=True)
    log_satirlari.append(mesaj)


def istek(yol, veri=None, sorgu=None):
    """Graph API cagrisi. veri verilirse POST, yoksa GET."""
    url = f"{API}/{yol.lstrip('/')}"
    params = dict(sorgu or {})
    params["access_token"] = TOKEN

    if veri is None:
        url = f"{url}?{urllib.parse.urlencode(params)}"
        gonderi = None
    else:
        gonderi = urllib.parse.urlencode({**veri, **params}).encode()

    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=gonderi), timeout=90) as cevap:
            return json.loads(cevap.read().decode())
    except urllib.error.HTTPError as hata:
        govde = hata.read().decode(errors="replace")
        raise RuntimeError(f"API hatasi {hata.code}: {govde}") from None


def hesap_id():
    return str(istek("me", sorgu={"fields": "user_id,username"})["user_id"])


def medya_url(yol):
    return f"{RAW_BASE}/{urllib.parse.quote(yol.lstrip('/'))}"


def konteyner_bekle(kimlik, azami=300):
    """Video konteynerinin islenmesini bekler."""
    basladi = time.time()
    while time.time() - basladi < azami:
        durum = istek(kimlik, sorgu={"fields": "status_code,status"})
        kod = durum.get("status_code")
        if kod == "FINISHED":
            return
        if kod == "ERROR":
            raise RuntimeError(f"Konteyner islenemedi: {durum.get('status')}")
        time.sleep(10)
    raise RuntimeError("Konteyner zaman asimina ugradi")


def konteyner_olustur(ig_id, kayit):
    tip = kayit.get("tip", "resim")
    caption = kayit.get("caption", "")
    dosyalar = kayit.get("dosyalar") or []
    if not dosyalar:
        raise RuntimeError("dosyalar bos")

    if tip == "resim":
        alanlar = {"image_url": medya_url(dosyalar[0]), "caption": caption}
        return istek(f"{ig_id}/media", veri=alanlar)["id"]

    if tip == "reels":
        alanlar = {
            "media_type": "REELS",
            "video_url": medya_url(dosyalar[0]),
            "caption": caption,
            "share_to_feed": "true",
        }
        kimlik = istek(f"{ig_id}/media", veri=alanlar)["id"]
        konteyner_bekle(kimlik)
        return kimlik

    if tip == "carousel":
        cocuklar = []
        for dosya in dosyalar[:10]:
            video = dosya.lower().endswith((".mp4", ".mov"))
            alanlar = {"is_carousel_item": "true"}
            if video:
                alanlar["media_type"] = "VIDEO"
                alanlar["video_url"] = medya_url(dosya)
            else:
                alanlar["image_url"] = medya_url(dosya)
            cocuk = istek(f"{ig_id}/media", veri=alanlar)["id"]
            if video:
                konteyner_bekle(cocuk)
            cocuklar.append(cocuk)
        alanlar = {
            "media_type": "CAROUSEL",
            "children": ",".join(cocuklar),
            "caption": caption,
        }
        return istek(f"{ig_id}/media", veri=alanlar)["id"]

    raise RuntimeError(f"Bilinmeyen tip: {tip}")


def zamani_geldi(kayit):
    zaman = kayit.get("zaman")
    if not zaman:
        return True
    try:
        hedef = datetime.fromisoformat(zaman)
    except ValueError:
        log(f"  ! gecersiz zaman bicimi: {zaman} - atlaniyor")
        return False
    if hedef.tzinfo is None:
        hedef = hedef.replace(tzinfo=timezone.utc)
    return hedef <= datetime.now(timezone.utc)


def token_omru_kontrol():
    """Token'i tazeler ve kalan sureyi bildirir."""
    try:
        cevap = istek("refresh_access_token", sorgu={"grant_type": "ig_refresh_token"})
        gun = int(cevap.get("expires_in", 0)) // 86400
        log(f"Token tazelendi, kalan sure ~{gun} gun.")
        yeni = cevap.get("access_token")
        if yeni and yeni != TOKEN:
            with open("yeni_token.txt", "w", encoding="utf-8") as dosya:
                dosya.write(yeni)
            log("  yeni token yeni_token.txt dosyasina yazildi (is akisi Secret'a tasiyacak)")
        if gun < 10:
            log("  !! DIKKAT: token 10 gunden az omurlu. Yenilemeyi kontrol et.")
    except Exception as hata:  # noqa: BLE001
        log(f"Token tazelenemedi: {hata}")


def main():
    if not TOKEN:
        sys.exit("IG_ACCESS_TOKEN tanimli degil.")
    if not RAW_BASE:
        sys.exit("RAW_BASE tanimli degil.")

    if not os.path.exists(KUYRUK):
        log("kuyruk.json yok, yapacak is yok.")
        return

    with open(KUYRUK, encoding="utf-8") as dosya:
        kuyruk = json.load(dosya)

    token_omru_kontrol()

    bekleyen = [k for k in kuyruk if k.get("durum") == "bekliyor" and zamani_geldi(k)]
    if not bekleyen:
        log("Zamani gelmis icerik yok.")
        gunluge_yaz()
        return

    ig_id = hesap_id()
    log(f"Instagram hesap ID: {ig_id}")

    degisti = False
    for kayit in bekleyen:
        etiket = kayit.get("id", "isimsiz")
        log(f"-> {etiket} ({kayit.get('tip')}) yayinlaniyor")
        try:
            konteyner = konteyner_olustur(ig_id, kayit)
            sonuc = istek(f"{ig_id}/media_publish", veri={"creation_id": konteyner})
            kayit["durum"] = "yayinlandi"
            kayit["sonuc"] = {
                "media_id": sonuc.get("id"),
                "tarih": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            log(f"   tamam - media_id {sonuc.get('id')}")
        except Exception as hata:  # noqa: BLE001
            kayit["durum"] = "hata"
            kayit["sonuc"] = {"hata": str(hata)[:500]}
            log(f"   HATA: {hata}")
        degisti = True
        time.sleep(5)

    if degisti:
        with open(KUYRUK, "w", encoding="utf-8") as dosya:
            json.dump(kuyruk, dosya, ensure_ascii=False, indent=2)
            dosya.write("\n")

    gunluge_yaz()

    if any(k.get("durum") == "hata" for k in bekleyen):
        sys.exit("En az bir icerik yayinlanamadi - gunluge bak.")


def gunluge_yaz():
    damga = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(GUNLUK, "a", encoding="utf-8") as dosya:
        dosya.write(f"\n## {damga}\n\n")
        for satir in log_satirlari:
            dosya.write(f"- {satir}\n")


if __name__ == "__main__":
    main()
