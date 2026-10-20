#!/usr/bin/env python3
"""
Instagram performans olcumu.

kuyruk.json'daki yayinlanmis her postun Instagram istatistiklerini (erisim, goruntulenme, kaydetme,
paylasma, begeni, yorum, profil ziyareti, takip) ceker ve olcum.json'a yazar. Panel (Dr. Reader
sayfasi) bu dosyayi okur. GitHub Actions gunde bir calistirir (olcum.yml).

Her post icin:
  son   - en son olcum (yayindan sonraki ilk 30 gun her gun tazelenir)
  g3    - yayindan >= 3 gun sonraki ilk olcum (ilk tepki)
  g14   - yayindan >= 14 gun sonraki ilk olcum (kalici sonuc; postlar bununla karsilastirilir)
Ayrica hesap ozeti (takipci, post sayisi) ve postun Instagram baglantisi (permalink).

Gerekli: IG_ACCESS_TOKEN (instagram_business_basic + instagram_business_manage_insights).
Token'i tazelemez; tazeleme yayinci.py'de.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://graph.instagram.com/v23.0"
KUYRUK = "kuyruk.json"
OLCUM = "olcum.json"
TAKIP_SURESI = timedelta(days=30)
# Carousel/fotograf postlari icin desteklenen olcutler. Biri reddedilirse digerleri tek tek denenir.
OLCUTLER = ["reach", "views", "saved", "shares", "likes", "comments", "total_interactions",
            "profile_visits", "follows"]

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()


def istek(yol, sorgu=None):
    params = dict(sorgu or {})
    params["access_token"] = TOKEN
    url = f"{API}/{yol.lstrip('/')}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as cevap:
            return json.loads(cevap.read().decode())
    except urllib.error.HTTPError as hata:
        govde = hata.read().decode(errors="replace")
        raise RuntimeError(f"API hatasi {hata.code}: {govde[:300]}") from None


def zaman_coz(deger):
    try:
        zaman = datetime.fromisoformat(str(deger).replace("Z", "+00:00"))
    except ValueError:
        return None
    return zaman if zaman.tzinfo else zaman.replace(tzinfo=timezone.utc)


def degerler(cevap):
    sonuc = {}
    for olcut in cevap.get("data", []):
        v = olcut.get("values") or [{}]
        deger = v[0].get("value") if v else None
        if deger is None:
            deger = (olcut.get("total_value") or {}).get("value")
        if isinstance(deger, (int, float)):
            sonuc[olcut["name"]] = deger
    return sonuc


def istatistik(media_id):
    try:
        return degerler(istek(f"{media_id}/insights", {"metric": ",".join(OLCUTLER)}))
    except RuntimeError:
        sonuc = {}
        for olcut in OLCUTLER:
            try:
                sonuc.update(degerler(istek(f"{media_id}/insights", {"metric": olcut})))
            except RuntimeError:
                pass
        if not sonuc:
            raise
        return sonuc


def baslik(kayit):
    """Panelde gorunecek ad: caption'in ilk satiri (kisaltilmis), yoksa kaydin kimligi."""
    ilk = (kayit.get("caption") or "").strip().split("\n")[0].strip()
    if not ilk:
        return kayit["id"]
    return ilk if len(ilk) <= 90 else ilk[:87].rstrip() + "…"


def main():
    if not TOKEN:
        sys.exit("IG_ACCESS_TOKEN yok.")
    simdi = datetime.now(timezone.utc)
    with open(KUYRUK, encoding="utf-8") as f:
        kuyruk = json.load(f)
    try:
        with open(OLCUM, encoding="utf-8") as f:
            eski = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        eski = {}
    postlar = eski.get("postlar", {})

    hesap = eski.get("hesap", {})
    try:
        h = istek("me", {"fields": "username,followers_count,media_count"})
        hesap = {"kullanici": h.get("username"), "takipci": h.get("followers_count"),
                 "post": h.get("media_count"), "tarih": simdi.isoformat(timespec="seconds")}
    except RuntimeError as hata:
        print(f"! hesap bilgisi alinamadi: {hata}")

    hata_sayisi = 0
    for kayit in kuyruk:
        sonuc = kayit.get("sonuc") or {}
        media_id = sonuc.get("media_id")
        if kayit.get("durum") != "yayinlandi" or not media_id:
            continue
        yayin = zaman_coz(sonuc.get("tarih") or kayit.get("zaman"))
        p = postlar.get(kayit["id"], {})
        p.update({"media_id": media_id, "baslik": baslik(kayit),
                  "yayin": yayin.isoformat(timespec="seconds") if yayin else None})
        if kayit.get("notion_id"):
            p["notion_id"] = kayit["notion_id"]
        if p.get("silindi") or (yayin and simdi - yayin > TAKIP_SURESI and p.get("g14")):
            postlar[kayit["id"]] = p
            continue
        try:
            if not p.get("baglanti"):
                p["baglanti"] = istek(media_id, {"fields": "permalink"}).get("permalink")
            olcum = istatistik(media_id)
        except RuntimeError as hata:
            # Silinmis post: medya bulunamaz (kod 100). Bir daha denenmez.
            if '"code":100' in str(hata).replace(" ", ""):
                p["silindi"] = True
                print(f"- {kayit['id']}: post bulunamadi (silinmis), atlandi")
            else:
                hata_sayisi += 1
                print(f"! {kayit['id']}: {hata}")
            postlar[kayit["id"]] = p
            continue
        olcum["tarih"] = simdi.isoformat(timespec="seconds")
        p["son"] = olcum
        if yayin:
            yas = simdi - yayin
            if yas >= timedelta(days=3) and not p.get("g3"):
                p["g3"] = olcum
            if yas >= timedelta(days=14) and not p.get("g14"):
                p["g14"] = olcum
        postlar[kayit["id"]] = p
        print(f"+ {kayit['id']}: erisim {olcum.get('reach')}, kaydetme {olcum.get('saved')}, "
              f"paylasma {olcum.get('shares')}")

    with open(OLCUM, "w", encoding="utf-8") as f:
        json.dump({"guncelleme": simdi.isoformat(timespec="seconds"), "hesap": hesap, "postlar": postlar},
                  f, ensure_ascii=False, indent=2)
        f.write("\n")
    if hata_sayisi:
        sys.exit(f"{hata_sayisi} post olculemedi (izin eksik olabilir: instagram_business_manage_insights).")


if __name__ == "__main__":
    main()
