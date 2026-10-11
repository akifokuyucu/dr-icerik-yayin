// Zamanlayıcıyı sahte GitHub API'siyle dener:  node zamanlayici/test/test.mjs
import { yaklasanlar, denetle } from "../src/index.js";

const kontrol = (ad, kosul) => { console.log((kosul ? "✅ " : "❌ ") + ad); if (!kosul) process.exitCode = 1; };
const SIMDI = Date.parse("2026-10-14T16:57:00Z"); // 19:57 İstanbul

const kuyruk = [
  { id: "yakin", durum: "bekliyor", zaman: "2026-10-14T20:00+03:00" }, // 3 dk sonra
  { id: "uzak", durum: "bekliyor", zaman: "2026-10-14T21:00+03:00" }, // 63 dk sonra
  { id: "yayinlandi", durum: "yayinlandi", zaman: "2026-10-14T20:00+03:00" },
  { id: "taslak", durum: "taslak", zaman: "2026-10-14T20:00+03:00" },
  { id: "saatsiz-utc", durum: "bekliyor", zaman: "2026-10-14T17:01" }, // UTC sayılır: 4 dk sonra
  { id: "kacmis", durum: "bekliyor", zaman: "2026-10-14T19:40+03:00" }, // 17 dk önce
  { id: "cok-eski", durum: "bekliyor", zaman: "2026-10-14T18:00+03:00" }, // 117 dk önce
  { id: "bozuk", durum: "bekliyor", zaman: "yarın" },
];
kontrol("Yalnızca pencere içindeki bekleyen postlar seçilir",
  yaklasanlar(kuyruk, SIMDI).map((k) => k.id).join() === "yakin,saatsiz-utc,kacmis");

let istekler, calisan, kuyrukDurumu;
globalThis.fetch = async (url, o = {}) => {
  url = String(url);
  istekler.push(`${o.method || "GET"} ${url.replace("https://api.github.com/repos/x/y", "")}`);
  if (o.headers?.Authorization !== "Bearer A") return new Response("yetkisiz", { status: 401 });
  if (url.includes("/contents/kuyruk.json")) {
    if (o.headers.Accept !== "application/vnd.github.raw+json") return new Response("yanlış biçim", { status: 415 });
    return new Response(JSON.stringify(kuyrukDurumu), { status: 200 });
  }
  if (url.includes("/runs?status=")) {
    const durum = new URL(url).searchParams.get("status");
    return Response.json({ total_count: durum === calisan ? 1 : 0 });
  }
  if (url.endsWith("/dispatches") && o.method === "POST") {
    return JSON.parse(o.body).ref === "main" ? new Response(null, { status: 204 }) : new Response("ref", { status: 422 });
  }
  return new Response("?", { status: 404 });
};
const env = { GITHUB_ANAHTARI: "A", DEPO: "x/y", DAL: "main", IS_AKISI: "yayinla.yml" };

istekler = []; calisan = null; kuyrukDurumu = kuyruk;
let sonuc = await denetle(env, SIMDI);
kontrol("Yaklaşan post varken iş akışı başlatılır", sonuc.startsWith("yayın başlatıldı") &&
  istekler.at(-1) === "POST /actions/workflows/yayinla.yml/dispatches");

istekler = []; calisan = "in_progress";
sonuc = await denetle(env, SIMDI);
kontrol("Çalışan yayın varsa ikinci kez başlatılmaz", sonuc.includes("zaten") && !istekler.some((i) => i.startsWith("POST")));

istekler = []; calisan = "queued";
sonuc = await denetle(env, SIMDI);
kontrol("Kuyrukta bekleyen yayın varsa da başlatılmaz", sonuc.includes("zaten") && !istekler.some((i) => i.startsWith("POST")));

istekler = []; calisan = null; kuyrukDurumu = [kuyruk[1], kuyruk[2]];
sonuc = await denetle(env, SIMDI);
kontrol("Yaklaşan post yoksa yalnızca kuyruk okunur", sonuc === "yaklaşan post yok" && istekler.length === 1);

istekler = [];
sonuc = await denetle({ ...env, GITHUB_ANAHTARI: "" }, SIMDI);
kontrol("Anahtar tanımlı değilse sessizce kapalı kalır", sonuc.includes("kapalı") && istekler.length === 0);

let hata = "";
try { await denetle({ ...env, GITHUB_ANAHTARI: "yanlis" }, SIMDI); } catch (e) { hata = e.message; }
kontrol("Anahtar geçersizse hata fırlatılır (Cloudflare günlüğünde görünür)", hata.includes("401"));
