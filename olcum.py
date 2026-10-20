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
  oran  - kaydetme / paylasma / etkilesim orani (erisime bolunur; g14 varsa ondan, yoksa son'dan)
Ayrica hesap ozeti (takipci, post sayisi), postun Instagram baglantisi (permalink), gunluk takipci
gecmisi (takipci_gecmis) ve son 7 gunun ozeti (haftalik). Haftalik ozeti Pazartesi brifing rutini okur
(brifing/rutin-talimati.md, Adim 1c).

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
GECMIS_GUN = 120  # takipci_gecmis'te tutulan gun sayisi
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


def oranlar(olcum):
    """Erisime gore oranlar (0-1 arasi, 4 basamak). Erisim yoksa bos."""
    erisim = olcum.get("reach")
    if not erisim:
        return {}
    sonuc = {}
    for ad, olcut in (("kaydetme", "saved"), ("paylasma", "shares"), ("etkilesim", "total_interactions")):
        if isinstance(olcum.get(olcut), (int, float)):
            sonuc[ad] = round(olcum[olcut] / erisim, 4)
    return sonuc


def haftalik_ozet(postlar, gecmis, simdi):
    """Son 7 gun: yeni yayinlar, 14. gun olcumu kesinlesen postlar, takipci degisimi."""
    bas = simdi - timedelta(days=7)
    yeni, kesinlesen = [], []
    for kimlik, p in postlar.items():
        if p.get("silindi"):
            continue
        yayin = zaman_coz(p.get("yayin")) if p.get("yayin") else None
        if yayin and yayin >= bas:
            yeni.append(kimlik)
        g14 = zaman_coz((p.get("g14") or {}).get("tarih", "")) if p.get("g14") else None
        if g14 and g14 >= bas:
            kesinlesen.append(kimlik)
    bugun = simdi.date().isoformat()
    once = (simdi - timedelta(days=7)).date().isoformat()
    # 7 gun onceki kayit yoksa ondan sonraki ilk kayit (gecmis yeni basladiysa)
    eski_gunler = sorted(g for g in gecmis if g >= once)
    takipci = {"simdi": gecmis.get(bugun)}
    if eski_gunler and eski_gunler[0] != bugun:
        takipci.update({"once": gecmis[eski_gunler[0]], "once_tarih": eski_gunler[0]})
        if takipci["simdi"] is not None:
            takipci["degisim"] = takipci["simdi"] - takipci["once"]
    return {"baslangic": once, "bitis": bugun, "yeni_postlar": yeni, "kesinlesen": kesinlesen,
            "takipci": takipci}


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
        p["oran"] = oranlar(p.get("g14") or olcum)
        postlar[kayit["id"]] = p
        print(f"+ {kayit['id']}: erisim {olcum.get('reach')}, kaydetme {olcum.get('saved')}, "
              f"paylasma {olcum.get('shares')}")

    # Olcumu biten (30 gunu gecmis) postlarda da oran dursun
    for p in postlar.values():
        if not p.get("oran") and (p.get("g14") or p.get("son")):
            p["oran"] = oranlar(p.get("g14") or p["son"])

    gecmis = dict(eski.get("takipci_gecmis", {}))
    if isinstance(hesap.get("takipci"), int):
        gecmis[simdi.date().isoformat()] = hesap["takipci"]
    sinir = (simdi - timedelta(days=GECMIS_GUN)).date().isoformat()
    gecmis = {g: v for g, v in sorted(gecmis.items()) if g >= sinir}

    with open(OLCUM, "w", encoding="utf-8") as f:
        json.dump({"guncelleme": simdi.isoformat(timespec="seconds"), "hesap": hesap,
                   "takipci_gecmis": gecmis, "haftalik": haftalik_ozet(postlar, gecmis, simdi),
                   "postlar": postlar},
                  f, ensure_ascii=False, indent=2)
        f.write("\n")
    if hata_sayisi:
        sys.exit(f"{hata_sayisi} post olculemedi (izin eksik olabilir: instagram_business_manage_insights).")


if __name__ == "__main__":
    main()
