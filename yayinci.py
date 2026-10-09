#!/usr/bin/env python3
"""
Instagram yayin motoru.

kuyruk.json icindeki zamani gelmis icerikleri Instagram'a yayinlar.
GitHub Actions tarafindan saatte bir calistirilir (pratikte 2-8 saatte bir;
zamani yakin bir post varsa calisma o saate kadar bekler, bkz. BEKLEME_UFKU).

Gerekli ortam degiskenleri:
  IG_ACCESS_TOKEN  - Instagram uzun omurlu erisim token'i (GitHub Secret)
  RAW_BASE         - medya dosyalarinin herkese acik kok URL'i
                     ornek: https://raw.githubusercontent.com/KULLANICI/DEPO/main
Istege bagli:
  NOTION_TOKEN     - Notion entegrasyon token'i (GitHub Secret). Tanimliysa ve kayitta
                     notion_id varsa, yayindan sonra Icerik Havuzu kaydi guncellenir
                     (Durum: yayinlandi, Yayin tarihi, Post baglantisi). Notion hatasi
                     yayini ve kuyrugu etkilemez; yalnizca gunluge yazilir.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://graph.instagram.com/v23.0"
KUYRUK = "kuyruk.json"
GUNLUK = "gunluk.md"

# GitHub'in saatlik cron'u saat basinda calismiyor; calismalar 2-8 saat arayla geliyor.
# Bu yuzden zamani bu sure icinde gelecek bir post varsa calisma o saate kadar bekler.
# Is akisindaki timeout-minutes bu sureden buyuk olmali.
BEKLEME_UFKU = timedelta(minutes=int(os.environ.get("BEKLEME_DAKIKA", "330")))

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
RAW_BASE = os.environ.get("RAW_BASE", "").strip().rstrip("/")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "").strip()
NOTION_API = "https://api.notion.com/v1"
NOTION_SURUM = "2022-06-28"

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


def konteyner_bekle(kimlik, azami=300, aralik=10):
    """Konteynerin (gorsel, video veya carousel) islenmesini bekler.
    Instagram medyayi indirip islemeden media_publish cagrilirsa 9007 hatasi doner."""
    basladi = time.time()
    while time.time() - basladi < azami:
        durum = istek(kimlik, sorgu={"fields": "status_code,status"})
        kod = durum.get("status_code")
        if kod == "FINISHED":
            return
        if kod == "ERROR":
            raise RuntimeError(f"Konteyner islenemedi: {durum.get('status')}")
        time.sleep(aralik)
    raise RuntimeError("Konteyner zaman asimina ugradi")


def alt_metin(kayit, sira):
    """Karta ait erisilebilirlik metni (Instagram alt_text; yalnizca gorsel, en fazla 1000 karakter)."""
    liste = kayit.get("alt_metinler") or []
    metin = liste[sira].strip() if sira < len(liste) and liste[sira] else ""
    return metin[:1000]


def konteyner_olustur(ig_id, kayit):
    tip = kayit.get("tip", "resim")
    caption = kayit.get("caption", "")
    dosyalar = kayit.get("dosyalar") or []
    if not dosyalar:
        raise RuntimeError("dosyalar bos")

    if tip == "resim":
        alanlar = {"image_url": medya_url(dosyalar[0]), "caption": caption}
        if alt_metin(kayit, 0):
            alanlar["alt_text"] = alt_metin(kayit, 0)
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
        for sira, dosya in enumerate(dosyalar[:10]):
            video = dosya.lower().endswith((".mp4", ".mov"))
            alanlar = {"is_carousel_item": "true"}
            if video:
                alanlar["media_type"] = "VIDEO"
                alanlar["video_url"] = medya_url(dosya)
            else:
                alanlar["image_url"] = medya_url(dosya)
                if alt_metin(kayit, sira):
                    alanlar["alt_text"] = alt_metin(kayit, sira)
            cocuk = istek(f"{ig_id}/media", veri=alanlar)["id"]
            konteyner_bekle(cocuk, aralik=10 if video else 3)
            cocuklar.append(cocuk)
        alanlar = {
            "media_type": "CAROUSEL",
            "children": ",".join(cocuklar),
            "caption": caption,
        }
        return istek(f"{ig_id}/media", veri=alanlar)["id"]

    raise RuntimeError(f"Bilinmeyen tip: {tip}")


def hedef_zaman(kayit):
    """Kaydin yayin zamani (UTC). Zaman yoksa simdi; bicim gecersizse None."""
    zaman = kayit.get("zaman")
    if not zaman:
        return datetime.now(timezone.utc)
    try:
        hedef = datetime.fromisoformat(zaman)
    except ValueError:
        log(f"  ! gecersiz zaman bicimi: {zaman} - atlaniyor")
        return None
    if hedef.tzinfo is None:
        hedef = hedef.replace(tzinfo=timezone.utc)
    return hedef


def zamani_geldi(kayit):
    hedef = hedef_zaman(kayit)
    return hedef is not None and hedef <= datetime.now(timezone.utc)


def kuyrugu_oku():
    if not os.path.exists(KUYRUK):
        return None
    with open(KUYRUK, encoding="utf-8") as dosya:
        return json.load(dosya)


def siradaki_bekle(kuyruk):
    """Zamani BEKLEME_UFKU icinde gelecek ilk post icin uyur, sonra depoyu tazeler.
    Bekleme sirasinda kuyruk degismis olabilir (post iptal, saat degisti), o yuzden
    uyandiktan sonra kuyruk depodan yeniden okunur. Bekleme olduysa True doner."""
    simdi = datetime.now(timezone.utc)
    gelecek = [
        h for k in kuyruk
        if k.get("durum") == "bekliyor" and (h := hedef_zaman(k)) is not None and h > simdi
    ]
    if not gelecek:
        return False
    hedef = min(gelecek)
    if hedef - simdi > BEKLEME_UFKU:
        print(f"Siradaki post {hedef.isoformat(timespec='minutes')} - bekleme ufkunun disinda.")
        return False

    saniye = (hedef - simdi).total_seconds() + 5
    log(f"Siradaki post {hedef.isoformat(timespec='minutes')}: {int(saniye // 60)} dakika beklendi.")
    time.sleep(saniye)

    cekim = subprocess.run(["git", "pull", "--ff-only", "--quiet"], capture_output=True, text=True)
    if cekim.returncode != 0:
        log(f"  ! bekleme sonrasi git pull basarisiz, eldeki kuyrukla devam: {cekim.stderr.strip()[:300]}")
    return True


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
        return True
    except Exception as hata:  # noqa: BLE001
        log(f"Token tazelenemedi: {hata}")
        return False


def main():
    if not TOKEN:
        sys.exit("IG_ACCESS_TOKEN tanimli degil.")
    if not RAW_BASE:
        sys.exit("RAW_BASE tanimli degil.")

    kuyruk = kuyrugu_oku()
    if kuyruk is None:
        log("kuyruk.json yok, yapacak is yok.")
        return

    # API erisimi yoksa is akisi basarisiz sayilir; GitHub e-postayla haber verir.
    # (Eskiden hata yutuluyordu ve hat haftalarca sessizce kapali kaldi.)
    if not token_omru_kontrol():
        gunluge_yaz()
        sys.exit("Instagram API'ye erisilemiyor - gunluge bak.")

    bekleyen = [k for k in kuyruk if k.get("durum") == "bekliyor" and zamani_geldi(k)]
    if not bekleyen and siradaki_bekle(kuyruk):
        kuyruk = kuyrugu_oku() or []
        bekleyen = [k for k in kuyruk if k.get("durum") == "bekliyor" and zamani_geldi(k)]
    if not bekleyen:
        # Gunluge yazilmaz: bos calismalar depoya saatte bir commit uretiyordu.
        print("Zamani gelmis icerik yok.")
        return

    ig_id = hesap_id()
    log(f"Instagram hesap ID: {ig_id}")

    degisti = False
    for kayit in bekleyen:
        etiket = kayit.get("id", "isimsiz")
        log(f"-> {etiket} ({kayit.get('tip')}) yayinlaniyor")
        try:
            konteyner = konteyner_olustur(ig_id, kayit)
            konteyner_bekle(konteyner, aralik=3)
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

    # Kuyruk dosyaya yazildiktan sonra: Notion basarisiz olsa da post "yayinlandi" kalir,
    # bir sonraki calisma ikinci kez yayinlamaz.
    for kayit in bekleyen:
        if kayit.get("durum") == "yayinlandi":
            notiona_yaz(kayit)

    gunluge_yaz()

    if any(k.get("durum") == "hata" for k in bekleyen):
        sys.exit("En az bir icerik yayinlanamadi - gunluge bak.")


def notion_istek(yol, govde):
    istek_ = urllib.request.Request(
        f"{NOTION_API}/{yol}", data=json.dumps(govde).encode(), method="PATCH",
        headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": NOTION_SURUM,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(istek_, timeout=30) as cevap:
            return json.loads(cevap.read().decode())
    except urllib.error.HTTPError as hata:
        raise RuntimeError(f"Notion hatasi {hata.code}: {hata.read().decode(errors='replace')[:300]}") from None


def notiona_yaz(kayit):
    """Yayinlanan postun Icerik Havuzu kaydini gunceller. Hicbir hatasi yayini durdurmaz."""
    etiket = kayit.get("id", "isimsiz")
    sayfa = (kayit.get("notion_id") or "").strip()
    if not sayfa:
        log(f"   Notion: {etiket} kaydinda notion_id yok, elle guncellenmeli")
        return
    if not NOTION_TOKEN:
        log(f"   Notion: NOTION_TOKEN tanimli degil, {etiket} elle guncellenmeli")
        return
    try:
        sonuc = kayit.get("sonuc") or {}
        alanlar = {
            "Durum": {"select": {"name": "yayınlandı"}},
            "Yayın tarihi": {"date": {"start": sonuc.get("tarih")}},
        }
        try:
            baglanti = istek(str(sonuc.get("media_id")), sorgu={"fields": "permalink"}).get("permalink")
        except Exception as hata:  # noqa: BLE001
            baglanti = None
            log(f"   Notion: post baglantisi alinamadi ({hata})")
        if baglanti:
            alanlar["Post bağlantısı"] = {"url": baglanti}
        notion_istek(f"pages/{sayfa}", {"properties": alanlar})
        log(f"   Notion: {etiket} -> yayinlandi{' + baglanti' if baglanti else ''}")
    except Exception as hata:  # noqa: BLE001
        log(f"   ! Notion guncellenemedi ({etiket}), elle guncellenmeli: {hata}")


def gunluge_yaz():
    damga = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(GUNLUK, "a", encoding="utf-8") as dosya:
        dosya.write(f"\n## {damga}\n\n")
        for satir in log_satirlari:
            dosya.write(f"- {satir}\n")


if __name__ == "__main__":
    main()
