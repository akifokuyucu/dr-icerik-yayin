#!/usr/bin/env python3
"""
Yayin botunun commit'i uzak depoyla catisinca (git pull --rebase basarisiz) calisir.

Botun son commit'indeki yayin sonuclarini (durum + sonuc) id'ye gore uzak depodaki
kuyruk.json'a, gunluge eklenen satirlari da uzak gunluk.md'nin sonuna tasir;
ardindan dali uzak dalin ucuna alip tek commit olarak yeniden kaydeder.
Boylece "yayinlandi" bilgisi kaybolmaz ve ayni post ikinci kez yayinlanmaz.

Kullanim (is akisi icinde, bot commit'i HEAD'deyken):
  python kuyruk_birlestir.py <uzak-dal>
"""

import json
import subprocess
import sys

KUYRUK = "kuyruk.json"
GUNLUK = "gunluk.md"
TAZELEME = "token_tazeleme.txt"


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def dosya(rev, yol):
    try:
        return git("show", f"{rev}:{yol}")
    except subprocess.CalledProcessError:
        return ""


def main():
    uzak = f"origin/{sys.argv[1]}"
    bizim_kuyruk = json.loads(dosya("HEAD", KUYRUK) or "[]")
    bizim_gunluk = dosya("HEAD", GUNLUK)
    eski_gunluk = dosya("HEAD~1", GUNLUK)
    uzak_kuyruk = json.loads(dosya(uzak, KUYRUK) or "[]")
    uzak_gunluk = dosya(uzak, GUNLUK)
    tazeleme = dosya("HEAD", TAZELEME)

    sonuclar = {
        k["id"]: k for k in bizim_kuyruk
        if k.get("id") and k.get("durum") in ("yayinlandi", "hata")
    }
    tasinan = []
    for kayit in uzak_kuyruk:
        bizim = sonuclar.get(kayit.get("id"))
        if bizim and kayit.get("durum") != bizim["durum"]:
            kayit["durum"] = bizim["durum"]
            kayit["sonuc"] = bizim.get("sonuc")
            tasinan.append(kayit["id"])

    # Gunluk yalnizca sona ekleniyor: botun ekledigi kisim = yeni metin - eski metin
    ek = bizim_gunluk[len(eski_gunluk):] if bizim_gunluk.startswith(eski_gunluk) else ""

    git("reset", "--hard", uzak)
    with open(KUYRUK, "w", encoding="utf-8") as f:
        json.dump(uzak_kuyruk, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(GUNLUK, "w", encoding="utf-8") as f:
        f.write(uzak_gunluk + ek)

    dosyalar = [KUYRUK, GUNLUK]
    if tazeleme:
        with open(TAZELEME, "w", encoding="utf-8") as f:
            f.write(tazeleme)
        dosyalar.append(TAZELEME)

    git("add", *dosyalar)
    if git("status", "--porcelain", *dosyalar).strip():
        git("commit", "-m", "yayin: kuyruk guncellendi (catisma birlestirildi)")
    print(f"Catisma birlestirildi, tasinan sonuclar: {', '.join(tasinan) or 'yok'}")


if __name__ == "__main__":
    main()
