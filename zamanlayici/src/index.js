/**
 * Dr. Reader yayın zamanlayıcısı — Cloudflare Worker (Cron Trigger, 5 dakikada bir)
 *
 * GitHub'ın saatlik cron'u pratikte 2-8 saatte bir çalışıyor; bu yüzden yayın iş akışı
 * saatlerce bekliyordu. Bu Worker kuyruğa bakar ve zamanı PENCERE içinde gelecek
 * (ya da en fazla GECIKME önce gelmiş) "bekliyor" durumunda bir post varsa
 * yayinla.yml'i hemen başlatır; yayinci.py postun saatine kadar bekleyip yayınlar.
 *
 * Ayarlar (Cloudflare panelinde "Variables and Secrets"):
 *   GITHUB_ANAHTARI  (gizli) İnce ayarlı GitHub token'ı — yalnızca dr-icerik-yayin deposu,
 *                    "Actions: Read and write" + "Contents: Read-only"
 *   DEPO, DAL, IS_AKISI  wrangler.jsonc'de
 */

const PENCERE_DK = 6; // cron aralığından (5 dk) biraz uzun: hiçbir post arada kalmasın
const GECIKME_DK = 30; // GitHub kesintisinde kaçan postlar için

const gh = (env, yol, secenek = {}) =>
  fetch(`https://api.github.com/repos/${env.DEPO}${yol}`, {
    ...secenek,
    headers: {
      Authorization: `Bearer ${env.GITHUB_ANAHTARI}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "dr-reader-zamanlayici",
      ...(secenek.headers || {}),
    },
  });

// Kuyruk API'den okunur: raw.githubusercontent.com 5 dakikaya kadar eski kopya verebiliyor
async function kuyrukOku(env) {
  const r = await gh(env, `/contents/kuyruk.json?ref=${encodeURIComponent(env.DAL)}`, {
    headers: { Accept: "application/vnd.github.raw+json" },
  });
  if (!r.ok) throw new Error(`kuyruk.json okunamadı: ${r.status} ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

/** Zamanı pencere içinde olan bekleyen postlar (yayinci.py ile aynı kural: saat dilimi yoksa UTC). */
export function yaklasanlar(kuyruk, simdi = Date.now()) {
  return kuyruk.filter((k) => {
    if (k.durum !== "bekliyor" || !k.zaman) return false;
    const zaman = /([zZ]|[+-]\d\d:?\d\d)$/.test(k.zaman) ? k.zaman : `${k.zaman}Z`;
    const fark = (Date.parse(zaman) - simdi) / 60000;
    return Number.isFinite(fark) && fark <= PENCERE_DK && fark >= -GECIKME_DK;
  });
}

// Zaten kuyrukta bekleyen ya da çalışan bir yayın varsa yenisi başlatılmaz:
// o çalışma uyandığında kuyruğu yeniden okuyup zamanı gelen her postu yayınlar.
async function calisanVar(env) {
  for (const durum of ["queued", "in_progress", "waiting", "pending"]) {
    const r = await gh(env, `/actions/workflows/${env.IS_AKISI}/runs?status=${durum}&per_page=1`);
    if (!r.ok) throw new Error(`çalışmalar okunamadı: ${r.status}`);
    if ((await r.json()).total_count > 0) return true;
  }
  return false;
}

export async function denetle(env, simdi = Date.now()) {
  if (!env.GITHUB_ANAHTARI) return "GITHUB_ANAHTARI tanımlı değil — zamanlayıcı kapalı";
  const postlar = yaklasanlar(await kuyrukOku(env), simdi);
  if (!postlar.length) return "yaklaşan post yok";
  const adlar = postlar.map((k) => k.id).join(", ");
  if (await calisanVar(env)) return `yaklaşan: ${adlar} — zaten çalışan/bekleyen yayın var`;
  const r = await gh(env, `/actions/workflows/${env.IS_AKISI}/dispatches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ref: env.DAL }),
  });
  if (r.status !== 204) throw new Error(`iş akışı başlatılamadı: ${r.status} ${(await r.text()).slice(0, 200)}`);
  return `yayın başlatıldı: ${adlar}`;
}

export default {
  async scheduled(olay, env, ctx) {
    // Hata fırlatılırsa Cloudflare bu çalışmayı "hata" olarak günlüğe yazar (Observability)
    const sonuc = await denetle(env, olay.scheduledTime);
    console.log(sonuc);
  },
  async fetch() {
    return new Response("Dr. Reader yayın zamanlayıcısı çalışıyor (5 dakikada bir).");
  },
};
