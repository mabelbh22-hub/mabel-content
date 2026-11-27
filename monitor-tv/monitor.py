"""Monitor de precios Smart TV 40-43" en tiendas chilenas (Cyber/Black Friday 2026).

Marcas con respaldo y sistema de apps/navegación bien evaluado:
  Samsung (Tizen), LG (webOS), TCL / Xiaomi / Philips / Sony (Google TV), TCL / AOC (Roku TV), Hisense solo con Google TV.
  Se excluyen VIDAA (catálogo de apps más limitado) y marcas menores (Master-G, Caixun, Aiwa, Huus, etc.).

Fuentes:
  - Solotodo (publicapi.solotodo.com): precios actuales + historial por tienda
    (Falabella, Paris, Ripley, Lider, ABC, Hites, Mercado Libre, Samsung Shop, Tienda LG, PC Factory, etc.)
  - Falabella (búsqueda directa): agrega precio CMR y publicaciones de sellers oficiales.

Uso: python3 monitor-tv/monitor.py   -> escribe monitor-tv/REPORTE.md y monitor-tv/data/snapshot-*.json
"""
import datetime as dt
import glob
import json
import os
import re
import statistics
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
BUDGET = 200_000
HIST_FROM = "2026-05-01T00:00:00Z"  # incluye CyberDay junio y el Cyber de octubre
PRE_FROM = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
PRE_TO = dt.datetime(2026, 11, 10, tzinfo=dt.timezone.utc)  # "precio normal" antes de la previa del evento
UA = {"User-Agent": "curl/8.5"}
BRANDS = {"Samsung", "LG", "TCL", "Xiaomi", "Philips", "Sony", "Hisense", "AOC"}
GOOD_OS = {"Tizen", "webOS", "Google TV", "Roku TV"}
NOW = dt.datetime.now(dt.timezone.utc)


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=90))


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def solotodo():
    stores = get_json("https://publicapi.solotodo.com/stores/?page_size=500")
    stores = stores if isinstance(stores, list) else stores["results"]
    chile = {s["id"]: s["name"] for s in stores if s.get("country_id") == 1}

    prods = {}
    url = "https://publicapi.solotodo.com/categories/11/browse/?page_size=50&ordering=offer_price_usd"
    while url:
        d = get_json(url)
        page_prices = []
        for b in d["results"]:
            for e in b["product_entries"]:
                p, s = e["product"], e["product"]["specs"]
                offer = float(e["metadata"]["prices_per_currency"][0]["offer_price"])
                page_prices.append(offer)
                if s.get("brand_unicode") not in BRANDS or s.get("operating_system_name") not in GOOD_OS:
                    continue
                if s.get("size_family_value") not in (40, 43):
                    continue
                if 100_000 <= offer <= 330_000:
                    prods[p["id"]] = {"id": p["id"], "model": p["name"], "size": s.get("size_family_value"),
                                      "res": s.get("resolution_commercial_name"), "os": s.get("operating_system_name")}
        if page_prices and min(page_prices) > 330_000:
            break
        url = d.get("next")

    rows = []
    for p in prods.values():
        hist = get_json(f"https://publicapi.solotodo.com/products/{p['id']}/pricing_history/?timestamp_after={HIST_FROM}")
        for e in hist:
            store = chile.get(e["entity"]["store"])
            if not store:
                continue
            rec = [r for r in e["pricing_history"] if r["is_available"] and float(r["offer_price"]) >= 100_000]
            if not rec:
                continue
            last = e["pricing_history"][-1]
            available = last["is_available"] and (NOW - ts(last["timestamp"])).days <= 2
            offers = [float(r["offer_price"]) for r in rec]
            pre = [float(r["normal_price"]) for r in rec if PRE_FROM <= ts(r["timestamp"]) < PRE_TO]
            imin = offers.index(min(offers))
            rows.append({**p, "store": store, "url": e["entity"]["external_url"], "available": available,
                         "offer": float(last["offer_price"]), "normal": float(last["normal_price"]),
                         "min": min(offers), "min_date": ts(rec[imin]["timestamp"]).date().isoformat(),
                         "pre_median": statistics.median(pre) if pre else None, "source": "solotodo"})
    return rows


def falabella():
    rows, seen = [], set()
    for q in ("smart tv 43 samsung", "smart tv 40 samsung", "smart tv 43 lg", "samsung 40 f6000", "lg 43 lb65",
              "smart tv 43 tcl", "smart tv 40 tcl", "xiaomi tv 43", "smart tv 43 google tv"):
        for page in (1, 2):
            url = "https://www.falabella.com/falabella-cl/search?Ntt=" + urllib.parse.quote_plus(q) + f"&page={page}"
            try:
                html = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                              timeout=60).read().decode("utf-8", "ignore")
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
                results = json.loads(m.group(1))["props"]["pageProps"].get("results", [])
            except Exception as exc:  # la tienda puede bloquear o cambiar el HTML
                print("Falabella falló:", q, exc)
                continue
            for p in results:
                name, brand = p.get("displayName", ""), (p.get("brand") or "").upper()
                if brand not in ("SAMSUNG", "LG", "TCL", "XIAOMI", "PHILIPS", "SONY", "HISENSE", "AOC") or p.get("productId") in seen:
                    continue
                if brand not in ("SAMSUNG", "LG") and not re.search(r"google|roku", name, re.I):
                    continue
                if not re.search(r"\b(40|43)\s*(\"|”|''|\s|$)", name) or re.search(r"monitor|watch|marco", name, re.I):
                    continue
                seen.add(p.get("productId"))
                pr = {x["type"]: int(x["price"][0].replace(".", "")) for x in p.get("prices", [])}
                best = min(pr.values()) if pr else None
                rows.append({"model": name, "brand": brand, "store": f"Falabella (vende {p.get('sellerName')})",
                             "prices": pr, "best": best, "url": p.get("url"), "source": "falabella"})
    return rows


def fmt(v):
    return "–" if v is None else "$" + f"{v:,.0f}".replace(",", ".")


def verdict(r, model_min):
    notes = []
    if r["offer"] <= model_min:
        notes.append("🟢 mínimo histórico (desde mayo)")
    elif r["offer"] <= model_min * 1.05:
        notes.append("🟢 a ≤5% del mínimo histórico")
    elif r["offer"] <= model_min * 1.12:
        notes.append("🟡 aceptable")
    else:
        notes.append("🔴 caro vs. su historial")
    if r["pre_median"] and r["normal"] > r["pre_median"] * 1.15:
        notes.append("⚠️ 'precio normal' inflado vs. ago-nov")
    return " · ".join(notes)


def main():
    os.makedirs(DATA, exist_ok=True)
    prev_files = sorted(glob.glob(os.path.join(DATA, "snapshot-*.json")))
    prev = json.load(open(prev_files[-1])) if prev_files else None
    st, fb = solotodo(), falabella()
    stamp = NOW.astimezone(dt.timezone(dt.timedelta(hours=-3))).strftime("%Y-%m-%d_%H%M")
    json.dump({"taken": NOW.isoformat(), "solotodo": st, "falabella": fb},
              open(os.path.join(DATA, f"snapshot-{stamp}.json"), "w"), ensure_ascii=False, indent=1)

    prev_best = {}
    if prev:
        for r in prev["solotodo"]:
            if r["available"]:
                prev_best[r["model"]] = min(prev_best.get(r["model"], 1e12), r["offer"])

    by_model = {}
    for r in st:
        by_model.setdefault(r["model"], []).append(r)

    lines = [f"# Monitor Smart TV 40–43\" (Samsung, LG, TCL, Xiaomi, Philips, Sony con buen sistema) — presupuesto {fmt(BUDGET)}",
             f"Actualizado: {stamp.replace('_', ' ')} (hora Chile). Fuente: Solotodo (historial por tienda) + Falabella directo.",
             "", "## Resumen por modelo (mejor precio actual en Chile)", "",
             "| Modelo | Tamaño/Res/Sistema | Mejor precio hoy | Tienda | Mín. histórico (desde mayo) | Precio normal ago–nov | vs. revisión anterior | Veredicto |",
             "|---|---|---|---|---|---|---|---|"]
    alerts = []
    summary = []
    for model, rs in by_model.items():
        live = [r for r in rs if r["available"]]
        if not live:
            continue
        best = min(live, key=lambda r: r["offer"])
        mmin = min(r["min"] for r in rs)
        mmin_r = min(rs, key=lambda r: r["min"])
        meds = [r["pre_median"] for r in rs if r["pre_median"]]
        med = statistics.median(meds) if meds else None
        delta = ""
        if model in prev_best:
            d = best["offer"] - prev_best[model]
            delta = "=" if d == 0 else ("▼ " if d < 0 else "▲ ") + fmt(abs(d))
        summary.append((best["offer"], f"| {model} | {best['size']}\" {best['res']} · {best.get('os', '')} | **{fmt(best['offer'])}** | "
                        f"[{best['store']}]({best['url']}) | {fmt(mmin)} ({mmin_r['store']}, {mmin_r['min_date']}) | "
                        f"{fmt(med)} | {delta} | {verdict(best, mmin)} |"))
        if best["offer"] < BUDGET:
            alerts.append(f"{model} ({best['size']}\" {best['res']}, {best.get('os', '')}) {fmt(best['offer'])} en {best['store']}")
    lines += [s for _, s in sorted(summary)]

    lines += ["", f"## Todas las ofertas bajo {fmt(BUDGET)} (por tienda)", "",
              "| Precio | Normal tachado | Modelo | Tienda | Mín. histórico tienda | Veredicto |", "|---|---|---|---|---|---|"]
    for r in sorted([r for r in st if r["available"] and r["offer"] < BUDGET], key=lambda r: r["offer"]):
        mmin = min(x["min"] for x in by_model[r["model"]])
        lines.append(f"| **{fmt(r['offer'])}** | {fmt(r['normal'])} | {r['model']} {r['size']}\" {r['res']} | "
                     f"[{r['store']}]({r['url']}) | {fmt(r['min'])} ({r['min_date']}) | {verdict(r, mmin)} |")

    lines += ["", "## Falabella directo (incluye precio CMR)", "", "| Mejor precio | Precios | Modelo | Vendedor |", "|---|---|---|---|"]
    for r in sorted([r for r in fb if r["best"]], key=lambda r: r["best"])[:20]:
        pr = ", ".join(f"{k.replace('Price', '')}: {fmt(v)}" for k, v in r["prices"].items())
        lines.append(f"| **{fmt(r['best'])}** | {pr} | [{r['model']}]({r['url']}) | {r['store']} |")
        if r["best"] < BUDGET:
            alerts.append(f"{r['model']} {fmt(r['best'])} en {r['store']} ({pr})")

    lines += ["", "_Criterio: 'mínimo histórico' = precio más bajo registrado en cualquier tienda chilena desde mayo 2026 "
              "(incluye CyberDay de junio y el Cyber de octubre). 'Precio normal inflado' = el precio tachado subió >15% "
              "sobre su mediana ago–nov, típico truco para mostrar un descuento mayor._"]
    open(os.path.join(BASE, "REPORTE.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines[:4 + len(summary) + 3]))
    print("\nBAJO PRESUPUESTO:", *alerts, sep="\n - ")


if __name__ == "__main__":
    main()
