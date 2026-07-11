from flask import Flask, jsonify, request, send_from_directory
from pytrends.request import TrendReq
import json, os, time, hashlib, math, pickle, threading
import requests
from urllib.parse import quote as _urlquote
from concurrent.futures import ThreadPoolExecutor

# When deployed to a cloud host (shared datacenter IP), Google Trends gets
# rate-limited hard — so default the UI to Wikipedia there. Set locally too
# via SOLECAST_DEFAULT_SOURCE if you want.
# Wikipedia by default: real data with no rate limit, so first-time visitors
# (e.g. a recruiter clicking through) never hit Google's 429 wall. Google
# remains one click away in the source picker.
DEFAULT_SOURCE = os.environ.get('SOLECAST_DEFAULT_SOURCE', 'wikipedia')
IS_HOSTED = bool(os.environ.get('PORT'))   # cloud hosts inject $PORT

# ── Aggregate region definitions ──────────────────────────────────────────
AGGREGATE_REGIONS = {
    "AGG:EMEA":  ["GB", "DE", "FR", "IT"],
    "AGG:CHINA": ["HK", "TW"],
    "AGG:APLA":  ["AU", "BR", "MX", "JP", "KR"],
    "AGG:JPKR":  ["JP", "KR"],
}

REGIONS = [
    {"group": None,              "label": "Global",                         "geo": ""},
    {"group": "North America",   "label": "North America",                  "geo": "US"},
    {"group": "EMEA",            "label": "EMEA — All (averaged)",          "geo": "AGG:EMEA"},
    {"group": "EMEA",            "label": "EMEA — UK",                      "geo": "GB"},
    {"group": "EMEA",            "label": "EMEA — Germany",                 "geo": "DE"},
    {"group": "EMEA",            "label": "EMEA — France",                  "geo": "FR"},
    {"group": "EMEA",            "label": "EMEA — Italy",                   "geo": "IT"},
    {"group": "Greater China",   "label": "Greater China — All (averaged)", "geo": "AGG:CHINA"},
    {"group": "Greater China",   "label": "Greater China — Hong Kong",      "geo": "HK"},
    {"group": "Greater China",   "label": "Greater China — Taiwan",         "geo": "TW"},
    {"group": "APLA",            "label": "APLA — All (averaged)",          "geo": "AGG:APLA"},
    {"group": "APLA",            "label": "APLA — Australia",               "geo": "AU"},
    {"group": "APLA",            "label": "APLA — Brazil",                  "geo": "BR"},
    {"group": "APLA",            "label": "APLA — Mexico",                  "geo": "MX"},
    {"group": "APLA",            "label": "APLA — Japan",                   "geo": "JP"},
    {"group": "APLA",            "label": "APLA — Korea",                   "geo": "KR"},
    {"group": "Japan / Korea",   "label": "Japan + Korea (averaged)",       "geo": "AGG:JPKR"},
    {"group": "Japan / Korea",   "label": "Japan",                          "geo": "JP"},
    {"group": "Japan / Korea",   "label": "Korea",                          "geo": "KR"},
]

# ── Curated autocomplete ──────────────────────────────────────────────────
SNEAKER_TERMS = [
    "Nike","Adidas","New Balance","Jordan","Puma","Reebok","Vans","Converse","ASICS","Brooks",
    "Saucony","Hoka","On Running","Salomon","Merrell","Timberland","UGG","Birkenstock",
    "Common Projects","Golden Goose","Maison Margiela","Bottega Veneta","Balenciaga",
    "Gucci","Prada","Dior","Louis Vuitton","Givenchy","Rick Owens","Yohji Yamamoto",
    "Comme des Garcons","Sacai","Stüssy","Palace","Supreme","Carhartt",
    "Salehe Bembury","Joe Freshgoods","Kith","Social Status","Bodega",
    "Air Force 1","Air Max 1","Air Max 90","Air Max 95","Air Max 97","Air Max 270",
    "Air Jordan 1","Air Jordan 3","Air Jordan 4","Air Jordan 11","Air Jordan 12",
    "Dunk Low","Dunk High","Dunk SB","Blazer","Cortez","Waffle","Free Run",
    "Ultraboost","NMD","Yeezy","Stan Smith","Gazelle","Samba","Campus","Forum",
    "New Balance 550","New Balance 990","New Balance 991","New Balance 992","New Balance 993",
    "New Balance 1906","New Balance 2002","New Balance 9060","New Balance 574","New Balance 327",
    "Chuck Taylor","Chuck 70","One Star","Run Star","Jack Purcell",
    "Old Skool","Era","Sk8-Hi","Authentic","Slip-On",
    "Classic Leather","Club C","Question","Answer","Freestyle",
    "Gel-Kayano","Gel-Nimbus","Gel-Lyte","Gel-1090","GT-2160",
    "Onitsuka Tiger","Mexico 66","Gel-Lyte III",
    "Cloudmonster","Cloudsurfer","Clifton","Bondi","Speedgoat",
    "XT-6","Speedcross","ACS Pro",
    "Diadora","Mizuno Wave","K-Swiss","Lacoste","Fila",
    "gorpcore sneakers","tenniscore shoes","ballet flat sneakers","dad shoes","chunky sneakers",
    "minimalist sneakers","trail sneakers","retro running","vintage sneakers","archival sneakers",
    "collab sneakers","sneaker drop","sneaker release","sneaker resale","heat sneakers",
    "luxury sneakers","designer sneakers","streetwear sneakers","running shoe trend",
    "performance sneaker","carbon plate shoe","super shoe","plated trainer",

    # ── Outdoor / gorpcore / technical apparel ──
    "And Wander","Gramicci","Snow Peak","Arc'teryx","Patagonia","ROA","Satisfy Running",
    "Nike ACG","Klättermusen","Norda","Ciele","District Vision","Post Archive Faction","PAF",
    "Goldwin","Montbell","The North Face","Purple Label","Veilance","Battenwear","Manastash",
    "Cayl","Amiacalva","Norse Projects","Salomon Advanced","Comfy Outdoor Garment","Nanga",

    # ── Avant-garde / designer ──
    "Comme des Garcons","CDG","Junya Watanabe","Undercover","Sacai","Kiko Kostadinov",
    "Our Legacy","Lemaire","The Row","Loewe","Jil Sander","Dries Van Noten",
    "Ann Demeulemeester","Raf Simons","Helmut Lang","Issey Miyake","Homme Plisse",
    "Auralee","Stone Island","CP Company","Acronym","Bottega Veneta","Margiela",

    # ── Streetwear / contemporary ──
    "Aimé Leon Dore","Kith","Corteiz","Sp5der","Denim Tears","Awake NY","Cav Empt",
    "Brain Dead","Online Ceramics","Noah","Bode","Kapital","Needles","Human Made",
    "Wtaps","Neighborhood","Carhartt WIP","Represent","Fear of God","Essentials",
    "Cactus Plant Flea Market","Rhude","Gallery Dept","Chrome Hearts","Amiri","Nahmias",

    # ── Emerging / niche labels ──
    "San San Gear","Story mfg","Nicholas Daley","Bstroy","Rayon Vert","GR10K","Hyein Seo",
    "Martine Rose","Wales Bonner","Bianca Saunders","Adish","Kartik Research","Cottweiler",
    "Reese Cooper","Song for the Mute","Camiel Fortgens","Rier","Séfr","Namacheko",
    "Winnie New York","Paloma Wool","Kartik","Diet Starts Monday",

    # ── Aesthetics / trends ──
    "gorpcore","blokecore","techwear","tenniscore","quiet luxury","y2k fashion",
    "opium fashion","indie sleaze","coquette","avant basic","normcore","workwear",
    "americana","cottagecore","balletcore","mob wife aesthetic","office siren","boho revival",

    # ── Apparel items ──
    "baggy cargo pants","parachute pants","balaclava","fleece jacket","shell jacket",
    "hiking pants","tabi boots","mary janes","carpenter pants","down jacket","technical vest",
    "jorts","mesh flats","leg warmers","selvedge denim","baggy jeans","hiking outfit",
]

# ── App setup ─────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder='static')

_cache = {}
CACHE_TTL = 6 * 3600            # serve as fresh for 6 hours
CACHE_STALE_MAX = 7 * 24 * 3600 # keep up to 7 days as a rate-limit fallback
CACHE_FILE = os.path.join(os.path.dirname(__file__), '.trends_cache.pkl')

def _cache_key(*args):
    return hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()

_cache_io_lock = threading.Lock()

def _cache_get(key, allow_stale=False):
    entry = _cache.get(key)
    if entry:
        ts, data = entry
        age = time.time() - ts
        if age < CACHE_TTL or (allow_stale and age < CACHE_STALE_MAX):
            return data
    return None

def _cache_set(key, data):
    with _cache_io_lock:
        _cache[key] = (time.time(), data)
        now = time.time()
        for k in [k for k, (ts, _) in _cache.items() if now - ts >= CACHE_STALE_MAX]:
            del _cache[k]
        try:
            with open(CACHE_FILE, 'wb') as f:
                pickle.dump(_cache, f)
        except Exception:
            pass

# Load persisted cache at startup — restarting the server no longer means
# re-hitting Google for everything you already fetched.
try:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f:
            _cache = pickle.load(f)
except Exception:
    _cache = {}

# Global spacing between LIVE Google requests. Rapid bursts (e.g. Breakout's
# per-keyword loop) are what trip the rate limit — enforce a minimum gap.
# Thread-safe slot reservation so background refreshes queue behind user
# requests instead of bursting alongside them.
_last_google_call = 0.0
_throttle_lock = threading.Lock()
GOOGLE_MIN_INTERVAL = 2.5

# ── Google usage tracking (visibility so users stay under the limit) ──────
from collections import deque
_google_hits = deque(maxlen=2000)   # timestamps of live Google requests
_last_429 = 0.0
# soft self-imposed ceiling; Google's real limit is unpublished, this keeps
# us comfortably beneath it and drives the UI meter.
GOOGLE_HOURLY_SOFT_CAP = 45

def _google_throttle():
    """Reserve a spaced slot for a live Google request AND record it for the meter."""
    global _last_google_call
    with _throttle_lock:
        slot = max(_last_google_call + GOOGLE_MIN_INTERVAL, time.time())
        _last_google_call = slot
        _google_hits.append(slot)
    wait = slot - time.time()
    if wait > 0:
        time.sleep(wait)

def _note_429():
    global _last_429
    _last_429 = time.time()

def _google_usage():
    now = time.time()
    m10 = sum(1 for t in _google_hits if now - t < 600)
    hr  = sum(1 for t in _google_hits if now - t < 3600)
    limited = (now - _last_429) < 120
    if limited:                       status = "limited"
    elif hr >= GOOGLE_HOURLY_SOFT_CAP: status = "limited"
    elif hr >= GOOGLE_HOURLY_SOFT_CAP * 0.6: status = "caution"
    else:                             status = "ok"
    return {
        "last_10min": m10, "last_hour": hr, "cap": GOOGLE_HOURLY_SOFT_CAP,
        "status": status, "recent_429": limited,
        "cache_entries": len(_cache),
        "cooldown_s": max(0, int(120 - (now - _last_429))) if limited else 0,
    }

def _get_pytrends():
    return TrendReq(hl='en-US', tz=360, timeout=(10, 20))

_refresh_inflight = set()
_refresh_lock = threading.Lock()

def _refresh_in_background(keywords, timeframe, geo, key):
    """Quietly re-fetch an expired cache entry without making the user wait."""
    def _job():
        try:
            _google_throttle()
            pt = _get_pytrends()
            pt.build_payload(keywords, timeframe=timeframe, geo=geo)
            df = pt.interest_over_time()
            if df is not None and not df.empty:
                _cache_set(key, df)
        except Exception:
            pass
        finally:
            with _refresh_lock:
                _refresh_inflight.discard(key)
    with _refresh_lock:
        if key in _refresh_inflight:
            return
        _refresh_inflight.add(key)
    threading.Thread(target=_job, daemon=True).start()

def _trends_request_with_retry(keywords, timeframe, geo, max_retries=2):
    key = _cache_key('trends', sorted(keywords), timeframe, geo)
    cached = _cache_get(key)
    if cached is not None:
        return cached, True
    # Stale-while-revalidate: anything fetched in the last 7 days returns
    # INSTANTLY while a background thread refreshes it. Repeat use never
    # waits on Google and never burns rate-limit budget in the foreground.
    stale = _cache_get(key, allow_stale=True)
    if stale is not None:
        _refresh_in_background(keywords, timeframe, geo, key)
        return stale, True
    last_err = None
    for attempt in range(max_retries):
        try:
            _google_throttle()
            pt = _get_pytrends()
            pt.build_payload(keywords, timeframe=timeframe, geo=geo)
            df = pt.interest_over_time()
            _cache_set(key, df)
            return df, False
        except Exception as e:
            last_err = e
            if '429' in str(e) or 'Too Many' in str(e):
                _note_429()
                time.sleep(2 ** attempt)  # 1s, 2s
            else:
                break
    raise last_err

# ── Sample-data fallback (used when Google Trends rate-limits the IP) ──────
import random as _random
from datetime import datetime as _dt, timedelta as _td

def _timeframe_points(timeframe):
    """Return (num_points, days_per_point) for a Google Trends timeframe."""
    return {
        "now 7-d":     (56, 0.125),   # ~3h buckets
        "today 1-m":   (30, 1),
        "today 3-m":   (90, 1),
        "today 12-m":  (52, 7),
        "today 5-y":   (60, 30),
    }.get(timeframe, (90, 1))

def _stable_seed(*parts):
    """Deterministic 32-bit seed from arbitrary strings (stable across restarts)."""
    h = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16)

def _generate_sample_data(keywords, timeframe, seed_extra=""):
    """Synthetic time series so the UI always renders. `seed_extra` (e.g. a
    region) makes the same keyword produce a *different* curve per region."""
    n, dpp = _timeframe_points(timeframe)
    end = _dt.now()
    dates = [str((end - _td(days=dpp * (n - 1 - i))).date()) for i in range(n)]

    raw_series = {}
    for kw in keywords:
        rng = _random.Random(_stable_seed(kw, seed_extra))
        base = rng.uniform(25, 55)
        # A pronounced directional trend (up/down/flat) so regions clearly
        # diverge, plus a gentle seasonal wave and light noise.
        total_swing = rng.uniform(-45, 55)          # net change across the window
        drift = total_swing / max(n - 1, 1)
        wave_amp = rng.uniform(3, 10)
        wave_period = rng.uniform(8, 22)
        phase = rng.uniform(0, 6.28)
        vals = []
        for i in range(n):
            v = base + drift * i \
                + wave_amp * math.sin(i / wave_period + phase) \
                + rng.uniform(-4, 4)
            vals.append(max(2, v))
        raw_series[kw] = vals

    # Normalize across all keywords so peak = 100 (like Google's relative index)
    global_max = max((max(v) for v in raw_series.values()), default=1)
    result = {}
    for kw, vals in raw_series.items():
        scaled = [round(v / global_max * 100) for v in vals]
        result[kw] = {
            "dates":   dates,
            "values":  scaled,
            "current": scaled[-1],
            "peak":    max(scaled),
            "avg":     round(sum(scaled) / len(scaled), 1),
            "trend":   _calc_trend(scaled),
            "cached":  False,
            "sample":  True,
        }
    return result

# Cultural adjacencies for trend discovery — the *other* brands, aesthetics,
# apparel, and collabs someone searching a given term also gravitates toward.
# Keyed on lowercase substrings; a keyword matches if it contains the key.
RELATED_ADJACENCY = {
    "salomon":        ["roa hiking", "arc'teryx", "hoka", "baggy cargo pants", "gorpcore", "and wander", "trail running shoes", "salomon xt-6", "techwear", "hiking outfit"],
    "xt-6":           ["salomon", "roa hiking", "gorpcore", "arc'teryx", "trail sneakers", "techwear"],
    "hoka":           ["salomon", "on running", "gorpcore", "trail running", "asics gel", "recovery slides", "running outfit"],
    "arc":            ["salomon", "gorpcore", "techwear", "and wander", "veilance", "goretex jacket", "patagonia", "hiking outfit"],
    "on running":     ["cloudmonster", "hoka", "salomon", "roger federer", "gorpcore", "cloudtilt", "running outfit"],
    "new balance 550":["aimé leon dore", "new balance 650", "prep style", "joe freshgoods", "grey sweatpants", "miu miu new balance"],
    "new balance 990":["dad shoes", "new balance 991", "made in usa", "grey new balance", "normcore", "miu miu collab"],
    "new balance":    ["aimé leon dore", "dad shoes", "grey new balance", "joe freshgoods", "miu miu collab", "1906r", "gorpcore", "prep style"],
    "samba":          ["adidas gazelle", "blokecore", "wales bonner", "sporty and rich", "terrace culture", "vintage adidas", "handball spezial", "tonal outfit"],
    "gazelle":        ["adidas samba", "blokecore", "handball spezial", "vintage adidas", "indie sleaze", "wales bonner"],
    "spezial":        ["adidas samba", "blokecore", "terrace culture", "wales bonner", "vintage adidas"],
    "adidas":         ["samba", "gazelle", "spezial", "wales bonner", "blokecore", "terrace culture", "yeezy slides", "sporty and rich"],
    "yeezy":          ["yeezy slides", "foam runner", "adidas samba", "resale", "350 v2", "onyx"],
    "jordan 1":       ["travis scott", "off white jordan", "chicago lost and found", "fragment", "jordan 1 outfit", "unc toe"],
    "jordan 4":       ["travis scott", "a ma maniere", "military black", "bred", "jordan 4 outfit", "retro jordans"],
    "jordan":         ["travis scott", "off white", "a ma maniere", "union la", "retro jordans", "sneaker resale", "nike sb"],
    "dunk":           ["panda dunk", "nike sb", "off white dunk", "skate shoes", "cacao wow", "dunk outfit"],
    "air force 1":    ["white sneakers", "nocta", "louis vuitton af1", "classic sneakers", "af1 outfit"],
    "air max":        ["air max plus", "tn", "y2k sneakers", "supreme air max", "corteiz", "running outfit"],
    "vomero":         ["nike vomero 5", "gorpcore", "y2k sneakers", "dad shoes", "p-6000", "chunky sneakers"],
    "converse":       ["chuck 70", "comme des garcons play", "vintage converse", "skate style", "indie sleaze"],
    "vans":           ["knu skool", "baggy jeans", "skate style", "old skool outfit", "checkerboard", "indie"],
    "asics":          ["gel kayano 14", "gorpcore", "cecilie bahnsen asics", "onitsuka tiger", "y2k sneakers", "metallic sneakers"],
    "onitsuka":       ["mexico 66", "kill bill", "y2k fashion", "asics", "tabi", "onitsuka outfit"],
    "puma":           ["puma speedcat", "low profile sneakers", "sleek sneakers", "f1 fashion", "rihanna fenty", "puma mostro"],
    "speedcat":       ["low profile sneakers", "sleek sneakers", "puma mostro", "y2k sneakers", "skinny sneakers", "ballet flats"],
    "margiela":       ["tabi", "german army trainer", "replica sneakers", "mm6", "quiet luxury", "gat"],
    "tabi":           ["margiela tabi", "split toe", "tabi ballet flats", "avant garde fashion", "mary janes"],
    "birkenstock":    ["boston clog", "clogs", "arizona", "socks and sandals", "gorpcore", "quiet luxury"],
    "crocs":          ["crocs platform", "jibbitz", "clogs", "salehe bembury crocs", "pollex"],
    "salehe":         ["new balance 2002r", "crocs pollex", "spunge", "gorpcore", "vibram", "yeezy foam runner"],
    "common projects":["quiet luxury", "minimalist sneakers", "achilles low", "leather sneakers", "the row", "margiela gat"],
    "golden goose":   ["distressed sneakers", "quiet luxury", "italian sneakers", "superstar", "designer sneakers"],
    "nike":           ["air force 1", "dunk low", "vomero 5", "travis scott nike", "nocta", "p-6000", "gorpcore", "y2k sneakers"],
}

# Broad trend/aesthetic terms used for discovery breadth and as a fallback
GENERAL_TREND_POOL = ["gorpcore", "blokecore", "quiet luxury", "y2k sneakers", "baggy cargo pants",
                      "dad shoes", "ballet flats", "sneaker resale", "vintage sneakers",
                      "sporty and rich", "aimé leon dore", "trending outfits 2026"]

# Aesthetic clusters — if the keyword *is* a trend rather than a shoe
AESTHETIC_CLUSTERS = {
    "gorpcore":   ["salomon", "arc'teryx", "hoka", "baggy cargo pants", "roa hiking", "and wander", "trail sneakers", "hiking outfit"],
    "blokecore":  ["adidas samba", "football jersey", "terrace culture", "vintage adidas", "gazelle", "wales bonner"],
    "tenniscore": ["sporty and rich", "tennis skirt", "adidas stan smith", "pleated skirt", "polo ralph lauren", "wimbledon style"],
    "techwear":   ["acronym", "arc'teryx veilance", "salomon", "cargo pants", "goretex", "stone island"],
    "dad shoe":   ["new balance 990", "asics gel", "vomero 5", "normcore", "chunky sneakers"],
    "ballet flat":["puma speedcat", "mary janes", "sandy liang", "alaia", "coquette", "mesh flats"],
}

def _related_pool(keyword):
    kwl = keyword.strip().lower()
    pool = []
    for key, terms in {**RELATED_ADJACENCY, **AESTHETIC_CLUSTERS}.items():
        if key in kwl:
            pool.extend(terms)
    if not pool:
        pool = list(GENERAL_TREND_POOL)
    pool.extend(GENERAL_TREND_POOL[:3])   # sprinkle discovery breadth
    seen, out = set(), []
    for t in pool:
        tl = t.lower()
        if tl in seen or tl == kwl:
            continue
        seen.add(tl)
        out.append(t)
    return out

def _generate_sample_related(keyword):
    """Trend-discovery related queries: culturally adjacent brands, aesthetics,
    and items — not '{keyword} + modifier' noise. Used when Google returns nothing."""
    pool = _related_pool(keyword)

    rng = _random.Random(_stable_seed(keyword, 'related-rising'))
    rising_order = pool[:]
    rng.shuffle(rising_order)
    rising = []
    for i, q in enumerate(rising_order[:8]):
        val = "Breakout" if i < 3 else rng.choice([320, 250, 190, 140, 110, 80])
        rising.append({"query": q, "value": val})

    rng2 = _random.Random(_stable_seed(keyword, 'related-top'))
    top_order = pool[:]
    rng2.shuffle(top_order)
    top, base = [], 100
    for q in top_order[:8]:
        top.append({"query": q, "value": base})
        base = max(6, base - rng2.randint(8, 19))

    return {"rising": rising, "top": top}

# ══════════════════════════════════════════════════════════════════════════
# ALTERNATIVE DATA SOURCES — Wikipedia Pageviews & Reddit
# Both return the SAME shape as Google Trends: {kw: {dates, values(0-100),
# current, peak, avg, trend, ...}} so all existing rendering/analysis works.
# ══════════════════════════════════════════════════════════════════════════
WIKI_UA = {"User-Agent": "SolecastTrends/1.0 (contact: joshuasee00@gmail.com)"}
REDDIT_UA = "SolecastTrends/1.0 (trend research app)"

# Region geo code → Wikipedia language project (imperfect: language ≠ country)
WIKI_PROJECT_BY_GEO = {
    "": "en.wikipedia", "US": "en.wikipedia", "GB": "en.wikipedia", "AU": "en.wikipedia",
    "DE": "de.wikipedia", "FR": "fr.wikipedia", "IT": "it.wikipedia",
    "JP": "ja.wikipedia", "KR": "ko.wikipedia", "BR": "pt.wikipedia", "MX": "es.wikipedia",
    "HK": "zh.wikipedia", "TW": "zh.wikipedia",
}

def _timeframe_days(timeframe):
    return {"now 7-d": 7, "today 1-m": 30, "today 3-m": 90,
            "today 12-m": 365, "today 5-y": 1825}.get(timeframe, 90)

def _date_axis(timeframe, monthly=False):
    """Continuous date labels covering the timeframe (daily or monthly)."""
    n = _timeframe_days(timeframe)
    end = _dt.now().date()
    if monthly:
        # first-of-month labels back far enough to cover n days
        months = max(2, n // 30)
        labels = []
        y, m = end.year, end.month
        for _ in range(months):
            labels.append(f"{y:04d}-{m:02d}-01")
            m -= 1
            if m == 0: m = 12; y -= 1
        return list(reversed(labels))
    return [str(end - _td(days=i)) for i in range(n - 1, -1, -1)]

# ── Wikipedia ─────────────────────────────────────────────────────────────
def _wiki_article(keyword, project="en.wikipedia"):
    lang = project.split(".")[0]
    try:
        r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", params={
            "action": "query", "list": "search", "srsearch": keyword,
            "format": "json", "srlimit": 1
        }, headers=WIKI_UA, timeout=10)
        hits = r.json().get("query", {}).get("search", [])
        return (hits[0]["title"].replace(" ", "_"), hits[0]["title"]) if hits else None
    except Exception:
        return None

def _wiki_series(keyword, timeframe, project="en.wikipedia"):
    ck = _cache_key('wiki', keyword.lower(), timeframe, project)
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    art = _wiki_article(keyword, project)
    if not art:
        return None
    article, title = art
    n = _timeframe_days(timeframe)
    monthly = n > 200
    gran = "monthly" if monthly else "daily"
    end = _dt.now()
    start = end - _td(days=n)
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"{project}/all-access/user/{_urlquote(article, safe='')}/{gran}/"
           f"{start.strftime('%Y%m%d')}/{end.strftime('%Y%m%d')}")
    try:
        r = requests.get(url, headers=WIKI_UA, timeout=12)
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
    except Exception:
        return None
    if not items:
        return None
    # keep the ACTUAL dates Wikipedia has data for (it lags ~1–2 days, so we
    # don't want to pad up to "today" with fake zeros → misleading current=0)
    by_date = {}
    for it in items:
        ts = it["timestamp"]
        d = f"{ts[:4]}-{ts[4:6]}-01" if monthly else f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        by_date[d] = it["views"]
    result = {"title": title, "by_date": by_date}
    _cache_set(ck, result)
    return result

def _fetch_wikipedia(keywords, timeframe, geo=""):
    project = WIKI_PROJECT_BY_GEO.get(geo, "en.wikipedia")
    raw = {}
    # fetch keywords in parallel — Wikipedia has no meaningful rate limit
    with ThreadPoolExecutor(max_workers=min(5, max(len(keywords), 1))) as ex:
        for kw, s in zip(keywords, ex.map(lambda k: _wiki_series(k, timeframe, project), keywords)):
            if s:
                raw[kw] = s
    if not raw:
        return None
    # common date axis = union of all dates any keyword actually has data for
    all_dates = sorted({d for s in raw.values() for d in s["by_date"]})
    gmax = max((max(s["by_date"].values()) for s in raw.values()), default=1) or 1
    result = {}
    for kw, s in raw.items():
        vals   = [s["by_date"].get(d, 0) for d in all_dates]
        scaled = [round(v / gmax * 100) for v in vals]
        result[kw] = {
            "dates": all_dates, "values": scaled,
            "current": scaled[-1] if scaled else 0,
            "peak": max(scaled) if scaled else 0,
            "avg": round(sum(scaled) / len(scaled), 1) if scaled else 0,
            "trend": _calc_trend(scaled),
            "raw_peak": max(vals) if vals else 0,
            "wiki_title": s["title"], "cached": False,
        }
    return result

# ── Reddit (requires user's own app credentials) ──────────────────────────
_reddit_token_cache = {"token": None, "exp": 0}

def _reddit_token():
    creds = load_config().get("reddit_credentials", {})
    # env vars take precedence when hosted (so secrets aren't committed to git)
    cid = os.environ.get("REDDIT_CLIENT_ID") or creds.get("client_id", "")
    secret = os.environ.get("REDDIT_CLIENT_SECRET") or creds.get("client_secret", "")
    if not cid or not secret:
        return None
    if _reddit_token_cache["token"] and _reddit_token_cache["exp"] > time.time():
        return _reddit_token_cache["token"]
    try:
        r = requests.post("https://www.reddit.com/api/v1/access_token",
                          auth=(cid, secret), data={"grant_type": "client_credentials"},
                          headers={"User-Agent": REDDIT_UA}, timeout=10)
        if r.status_code != 200:
            return None
        j = r.json()
        tok = j.get("access_token")
        _reddit_token_cache["token"] = tok
        _reddit_token_cache["exp"] = time.time() + j.get("expires_in", 3600) - 60
        return tok
    except Exception:
        return None

def _reddit_search_posts(keyword, timeframe, token):
    t = {"now 7-d": "week", "today 1-m": "month", "today 3-m": "month",
         "today 12-m": "year", "today 5-y": "all"}.get(timeframe, "month")
    headers = {"Authorization": f"bearer {token}", "User-Agent": REDDIT_UA}
    posts, after = [], None
    for _ in range(4):   # up to ~400 posts
        params = {"q": keyword, "sort": "new", "limit": 100, "t": t, "type": "link"}
        if after:
            params["after"] = after
        try:
            r = requests.get("https://oauth.reddit.com/search", params=params,
                             headers=headers, timeout=12)
            if r.status_code != 200:
                break
            data = r.json().get("data", {})
        except Exception:
            break
        posts += [c["data"] for c in data.get("children", [])]
        after = data.get("after")
        if not after:
            break
    return posts

def _fetch_reddit(keywords, timeframe, geo=""):
    token = _reddit_token()
    if not token:
        return {"_error": "reddit_setup"}
    monthly = _timeframe_days(timeframe) > 200
    axis = _date_axis(timeframe, monthly=monthly)
    raw = {}
    for kw in keywords:
        ck = _cache_key('reddit', kw.lower(), timeframe)
        posts = _cache_get(ck)
        if posts is None:
            posts = _reddit_search_posts(kw, timeframe, token)
            _cache_set(ck, posts)
        buckets = {d: 0 for d in axis}
        for p in posts:
            d = _dt.utcfromtimestamp(p.get("created_utc", 0)).date()
            key = f"{d.year:04d}-{d.month:02d}-01" if monthly else str(d)
            if key in buckets:
                # weight by engagement so a viral post counts more than a dead one
                buckets[key] += 1 + math.log1p(max(0, p.get("score", 0)) + max(0, p.get("num_comments", 0)))
        raw[kw] = [buckets[d] for d in axis]
    if all(sum(v) == 0 for v in raw.values()):
        return None
    gmax = max((max(v) for v in raw.values() if v), default=1) or 1
    result = {}
    for kw, vals in raw.items():
        scaled = [round(v / gmax * 100) for v in vals]
        result[kw] = {
            "dates": axis, "values": scaled,
            "current": scaled[-1] if scaled else 0,
            "peak": max(scaled) if scaled else 0,
            "avg": round(sum(scaled) / len(scaled), 1) if scaled else 0,
            "trend": _calc_trend(scaled), "cached": False,
        }
    return result

# ── Unified dispatcher ────────────────────────────────────────────────────
def _fetch_by_source(keywords, timeframe, geo, source):
    """Returns (result_dict, meta_dict). Google keeps its sample fallback;
    Wikipedia/Reddit are real-only with clear unavailable/setup states."""
    if source == "wikipedia":
        data = _fetch_wikipedia(keywords, timeframe, geo)
        if not data:
            return None, {"unavailable": True, "reason": "empty", "source": "wikipedia"}
        return data, {"source": "wikipedia"}
    if source == "reddit":
        data = _fetch_reddit(keywords, timeframe, geo)
        if isinstance(data, dict) and data.get("_error") == "reddit_setup":
            return None, {"unavailable": True, "reason": "reddit_setup", "source": "reddit"}
        if not data:
            return None, {"unavailable": True, "reason": "empty", "source": "reddit"}
        return data, {"source": "reddit"}
    # google (default) — with sample fallback handled by caller
    return "google", {"source": "google"}

DEFAULT_CONFIG = {
    "keyword_groups": {
        "Classic Silhouettes": ["Air Force 1", "Chuck Taylor", "Stan Smith", "New Balance 990", "Gazelle"],
        "Performance Running": ["Brooks Ghost", "ASICS Gel-Kayano", "Nike Pegasus", "Adidas Ultraboost", "Saucony Kinvara"],
        "Retro/Vintage": ["New Balance 550", "Samba", "Onitsuka Tiger", "Reebok Classic", "Diadora"],
        "Luxury/Designer": ["Balenciaga sneakers", "Common Projects", "Golden Goose", "Maison Margiela sneakers", "Salehe Bembury"],
        "Hype/Collabs": ["Travis Scott Jordan", "Off White Nike", "Yeezy", "Dunk SB", "New Balance collabs"],
    },
    "micro_trends": ["gorpcore sneakers", "tenniscore shoes", "ballet flat sneakers", "chunky dad shoes", "minimalist sneakers"],
    "timeframes": {
        "1W": "now 7-d",
        "1M": "today 1-m",
        "3M": "today 3-m",
        "12M": "today 12-m",
        "5Y": "today 5-y"
    },
    "reddit_credentials": {"client_id": "", "client_secret": ""},
    "report_password": "solecast"
}

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        # backfill any keys added after this config was first saved
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return DEFAULT_CONFIG

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

# ── Routes ────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/regions')
def get_regions():
    return jsonify(REGIONS)

@app.route('/api/meta')
def get_meta():
    """Environment info the frontend needs at load (e.g. default data source)."""
    return jsonify({"default_source": DEFAULT_SOURCE, "hosted": IS_HOSTED})

@app.route('/api/usage')
def get_usage():
    """Live Google Trends usage so the UI can keep users under the limit."""
    return jsonify(_google_usage())

# ── Image proxy ───────────────────────────────────────────────────────────
# Serve report imagery through our own origin so it never depends on the
# browser successfully hotlinking a third party (which fails intermittently).
# Restricted to an allowlist so this can't be used as an open proxy.
from urllib.parse import urlparse as _urlparse
from flask import Response as _Response
_img_cache = {}
ALLOWED_IMG_HOSTS = {"upload.wikimedia.org", "commons.wikimedia.org"}

@app.route('/api/img')
def img_proxy():
    u = request.args.get('u', '')
    if not u:
        return "missing url", 400
    if _urlparse(u).netloc.lower() not in ALLOWED_IMG_HOSTS:
        return "host not allowed", 403
    hit = _img_cache.get(u)
    if hit is None:
        try:
            r = requests.get(u, headers=WIKI_UA, timeout=15)
            if r.status_code != 200:
                return "upstream error", 502
            hit = (r.headers.get('Content-Type', 'image/jpeg'), r.content)
            if len(_img_cache) < 300:   # cap memory use
                _img_cache[u] = hit
        except Exception:
            return "fetch failed", 502
    resp = _Response(hit[1], mimetype=hit[0])
    resp.headers['Cache-Control'] = 'public, max-age=604800'   # 7 days
    return resp

@app.route('/api/suggest')
def suggest():
    q = request.args.get('q', '').strip().lower()
    if not q or len(q) < 2:
        return jsonify([])
    # Case-insensitive dedupe of curated matches (the term list has some overlaps)
    _seen_lc, _matches = set(), []
    for t in SNEAKER_TERMS:
        if q in t.lower() and t.lower() not in _seen_lc:
            _seen_lc.add(t.lower())
            _matches.append(t)
    curated = sorted(
        _matches,
        key=lambda t: (not t.lower().startswith(q), t.lower())
    )[:6]
    # Autocomplete used to fire a Google request on every keystroke, quietly
    # burning the rate-limit budget. Only ask Google when the curated list
    # can't answer (few matches) and the query is specific enough.
    if len(curated) >= 3 or len(q) < 4:
        return jsonify(curated[:8])
    key = _cache_key('suggest', q)
    gt = _cache_get(key)
    if gt is None:
        try:
            _google_throttle()
            pt = _get_pytrends()
            raw = pt.suggestions(q)
            gt = [s['title'] for s in raw][:5]
            _cache_set(key, gt)
        except Exception:
            gt = []
    seen = {t.lower() for t in curated}
    merged = curated[:]
    for s in gt:
        if s.lower() not in seen:
            merged.append(s)
            seen.add(s.lower())
    return jsonify(merged[:8])

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(load_config())

@app.route('/api/config', methods=['POST'])
def update_config():
    save_config(request.json)
    return jsonify({"status": "ok"})

@app.route('/api/config/reset', methods=['POST'])
def reset_config():
    save_config(DEFAULT_CONFIG)
    return jsonify(DEFAULT_CONFIG)

# ── The Report (weekly editorial, in-page editable) ────────────────────────
REPORT_FILE = os.path.join(os.path.dirname(__file__), 'report.json')

def _report_password():
    # env var wins (for hosted deployments), then config.json, then default
    return os.environ.get('REPORT_PASSWORD') or load_config().get('report_password') or 'solecast'

@app.route('/api/report', methods=['GET'])
def get_report():
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE) as f:
            return jsonify(json.load(f))
    return jsonify({"edition_label": "Edition 001", "regions": []})

@app.route('/api/report/auth', methods=['POST'])
def report_auth():
    ok = (request.json or {}).get('password', '') == _report_password()
    return jsonify({"ok": ok})

@app.route('/api/report', methods=['POST'])
def save_report_route():
    body = request.json or {}
    if body.get('password', '') != _report_password():
        return jsonify({"ok": False, "error": "Wrong password"}), 403
    report = body.get('report')
    if not isinstance(report, dict) or 'regions' not in report:
        return jsonify({"ok": False, "error": "Bad payload"}), 400
    with open(REPORT_FILE, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return jsonify({"ok": True})

@app.route('/api/trends', methods=['POST'])
def get_trends():
    body = request.json
    keywords = [k.strip() for k in body.get('keywords', []) if k.strip()][:5]
    timeframe = body.get('timeframe', 'today 3-m')
    geo = body.get('geo', '')
    source = body.get('source', 'google')
    if not keywords:
        return jsonify({"error": "No keywords provided"}), 400
    # Alternative sources (Wikipedia / Reddit) — real data only
    if source in ('wikipedia', 'reddit'):
        data, meta = _fetch_by_source(keywords, timeframe, geo, source)
        if data is None:
            return jsonify({"_meta": meta})
        return jsonify({**data, "_meta": meta})
    if geo in AGGREGATE_REGIONS:
        return _get_trends_aggregate(keywords, timeframe, geo)
    try:
        df, from_cache = _trends_request_with_retry(keywords, timeframe, geo)
        if df is None or (hasattr(df, 'empty') and df.empty):
            # Empty result — fall back to sample so the UI still renders
            result = _generate_sample_data(keywords, timeframe)
            return jsonify({**result, "_meta": {"sample": True}})
        return jsonify(_build_result(keywords, df, from_cache))
    except Exception as e:
        msg = str(e)
        # Google is throttling or unreachable — serve sample data so charts render
        result = _generate_sample_data(keywords, timeframe)
        reason = "rate_limit" if ('429' in msg or 'Too Many' in msg) else "network"
        return jsonify({**result, "_meta": {"sample": True, "reason": reason}})

@app.route('/api/region-compare', methods=['POST'])
def region_compare():
    """Compare the same keywords across multiple regions."""
    body = request.json
    keywords = [k.strip() for k in body.get('keywords', []) if k.strip()][:5]
    timeframe = body.get('timeframe', 'today 3-m')
    geos = body.get('geos', [])   # list of {label, geo}
    source = body.get('source', 'google')
    if not keywords or not geos:
        return jsonify({"error": "Provide keywords and at least one region"}), 400

    # Reddit has no geography → not supported for regional comparison
    if source == 'reddit':
        return jsonify({"_meta": {"unavailable": True, "reason": "reddit_no_regions", "source": "reddit"}})

    # Wikipedia: each "region" maps to a language edition (imperfect but real)
    if source == 'wikipedia':
        results = {}
        for region in geos[:6]:
            label = region.get('label', region.get('geo', ''))
            geo   = region.get('geo', '')
            data = _fetch_wikipedia(keywords, timeframe, geo)
            if data:
                results[label] = data
        if not results:
            return jsonify({"_meta": {"unavailable": True, "reason": "empty", "source": "wikipedia"}})
        results["_meta"] = {"source": "wikipedia"}
        return jsonify(results)

    results = {}
    used_sample = False
    for region in geos[:6]:
        label = region.get('label', region.get('geo', ''))
        geo   = region.get('geo', '')
        try:
            if geo in AGGREGATE_REGIONS:
                resp = _fetch_aggregate_data(keywords, timeframe, geo)
                if 'error' in resp:
                    raise Exception(resp.get('error', 'no data'))
            else:
                df, _ = _trends_request_with_retry(keywords, timeframe, geo)
                if df is None or (hasattr(df, 'empty') and df.empty):
                    raise Exception('empty')
                resp = _build_result(keywords, df, False)
            results[label] = resp
        except Exception:
            # Fall back to sample data for this region so the chart still renders.
            # Seed with the region label so each region gets a DISTINCT curve.
            results[label] = _generate_sample_data(keywords, timeframe, seed_extra=label)
            used_sample = True

    if not results:
        return jsonify({"error": "No data returned for selected regions"}), 404
    if used_sample:
        results["_meta"] = {"sample": True, "reason": "rate_limit"}
    return jsonify(results)

@app.route('/api/analyze', methods=['POST'])
def analyze():
    body = request.json
    trends_data      = body.get('data', {})
    timeframe_label  = body.get('timeframe_label', '3 months')
    group_name       = body.get('group_name', '')
    if not trends_data:
        return jsonify({"error": "No data"}), 400
    return jsonify(_generate_analysis(trends_data, timeframe_label, group_name))

@app.route('/api/analyze-regions', methods=['POST'])
def analyze_regions():
    body = request.json
    region_data     = body.get('data', {})
    keyword         = body.get('keyword', '')
    timeframe_label = body.get('timeframe_label', '3 months')
    if not region_data:
        return jsonify({"error": "No data"}), 400
    return jsonify(_generate_region_analysis(region_data, keyword, timeframe_label))

@app.route('/api/analyze-breakout', methods=['POST'])
def analyze_breakout():
    body = request.json
    items = body.get('items', [])
    if not items:
        return jsonify({"error": "No data"}), 400
    return jsonify(_generate_breakout_analysis(items))

@app.route('/api/related', methods=['POST'])
def get_related():
    body = request.json
    keyword  = body.get('keyword', '').strip()
    timeframe = body.get('timeframe', 'today 3-m')
    source = body.get('source', 'google')
    if not keyword:
        return jsonify({"error": "No keyword provided"}), 400
    # "Related queries" is a Google-search concept; other sources don't have it
    if source in ('wikipedia', 'reddit'):
        return jsonify({"rising": [], "top": [], "_meta": {"unavailable": True, "reason": "related_google_only", "source": source}})
    key = _cache_key('related', keyword, timeframe)
    cached = _cache_get(key)
    if cached:
        return jsonify(cached)
    try:
        _google_throttle()
        pt = _get_pytrends()
        pt.build_payload([keyword], timeframe=timeframe)
        rel = pt.related_queries()
        rising, top = [], []
        if keyword in rel:
            if rel[keyword]['rising'] is not None:
                rising = rel[keyword]['rising'].head(10).to_dict('records')
            if rel[keyword]['top'] is not None:
                top = rel[keyword]['top'].head(10).to_dict('records')
        # Related is REAL-DATA-ONLY (no sample fallback). Google frequently
        # returns an empty related_queries payload (they broke that endpoint);
        # when that happens we report it as unavailable rather than faking it.
        if not rising and not top:
            return jsonify({"rising": [], "top": [], "_meta": {"unavailable": True, "reason": "empty"}})
        result = {"rising": rising, "top": top}
        _cache_set(key, result)
        return jsonify(result)
    except Exception as e:
        msg = str(e)
        # Older cached related data is still real data — prefer it over nothing
        stale = _cache_get(key, allow_stale=True)
        if stale:
            return jsonify(stale)
        reason = "rate_limit" if ('429' in msg or 'Too Many' in msg) else "network"
        return jsonify({"rising": [], "top": [], "_meta": {"unavailable": True, "reason": reason}})

def _momentum_of(series):
    """Second-half average minus first-half average. `+ 0.0` kills negative zero."""
    if not series:
        return 0.0
    mid = len(series) // 2
    first_avg  = sum(series[:mid]) / max(mid, 1)
    second_avg = sum(series[mid:]) / max(len(series) - mid, 1)
    return round(second_avg - first_avg, 1) + 0.0

@app.route('/api/breakout', methods=['POST'])
def get_breakout():
    body = request.json
    keywords = [k.strip() for k in (body.get('keywords') or load_config().get('micro_trends', [])) if k.strip()]
    source = body.get('source', 'google')
    results = []

    # Alternative sources: fetch each keyword on its own scale, compute momentum
    if source in ('wikipedia', 'reddit'):
        fetch = _fetch_wikipedia if source == 'wikipedia' else _fetch_reddit
        if source == 'wikipedia':
            # Wikipedia has no rate limit — scan all keywords in parallel
            with ThreadPoolExecutor(max_workers=4) as ex:
                pairs = list(zip(keywords, ex.map(lambda k: fetch([k], 'today 3-m', ''), keywords)))
        else:
            pairs = [(kw, fetch([kw], 'today 3-m', '')) for kw in keywords]
        for kw, data in pairs:
            if isinstance(data, dict) and data.get('_error') == 'reddit_setup':
                return jsonify({"_meta": {"unavailable": True, "reason": "reddit_setup", "source": source}})
            if not data or kw not in data:
                continue
            d = data[kw]
            results.append({
                "keyword": kw, "current": d['current'],
                "momentum": _momentum_of(d['values']), "values": d['values'],
                "dates": d['dates'], "sample": False,
            })
        if not results:
            return jsonify({"_meta": {"unavailable": True, "reason": "empty", "source": source}})
        results.sort(key=lambda x: x['momentum'], reverse=True)
        return jsonify(results)

    # Query EACH keyword on its own 0–100 scale so a high-volume term can't
    # crush a low-volume one to zero. This makes momentum a true, comparable
    # measure of each keyword's own trajectory (real breakout detection).
    for kw in keywords:
        try:
            df, from_cache = _trends_request_with_retry([kw], 'today 3-m', '')
            if df is None or (hasattr(df, 'empty') and df.empty) or kw not in df.columns:
                raise Exception('no data')
            series = [int(v) for v in df[kw].values.tolist()]
            results.append({
                "keyword": kw, "current": series[-1],
                "momentum": _momentum_of(series), "values": series,
                "dates": [str(d.date()) for d in df.index], "sample": False,
            })
            # spacing between live requests is handled by _google_throttle()
        except Exception:
            # Fall back to sample for just this keyword so its card still renders
            sample = _generate_sample_data([kw], 'today 3-m', seed_extra='breakout')
            d = sample.get(kw)
            if d:
                results.append({
                    "keyword": kw, "current": d['current'],
                    "momentum": _momentum_of(d['values']), "values": d['values'],
                    "dates": d['dates'], "sample": True,
                })
    results.sort(key=lambda x: x['momentum'], reverse=True)
    return jsonify(results)

# ── Helpers ───────────────────────────────────────────────────────────────

def _get_trends_aggregate(keywords, timeframe, agg_geo):
    data = _fetch_aggregate_data(keywords, timeframe, agg_geo)
    if 'error' in data:
        return jsonify(data), data.get('status', 500)
    return jsonify(data)

def _fetch_aggregate_data(keywords, timeframe, agg_geo):
    countries = AGGREGATE_REGIONS[agg_geo]
    country_dfs = {}
    for country in countries:
        try:
            df, _ = _trends_request_with_retry(keywords, timeframe, country)
            if df is not None and not (hasattr(df, 'empty') and df.empty):
                country_dfs[country] = df
        except Exception as e:
            if '429' in str(e) or 'Too Many' in str(e):
                return {"error": "Rate limited. Wait 60s.", "rate_limited": True, "status": 429}
    if not country_dfs:
        return {"error": "No data for this region"}
    ref_df    = next(iter(country_dfs.values()))
    ref_index = ref_df.index
    result = {}
    for kw in keywords:
        series_list = []
        for df in country_dfs.values():
            if kw in df.columns:
                series_list.append(df[kw].reindex(ref_index, fill_value=0).values.tolist())
        if not series_list:
            continue
        avg_vals = [round(sum(col) / len(col)) for col in zip(*series_list)]
        result[kw] = {
            "dates":        [str(d.date()) for d in ref_index],
            "values":       avg_vals,
            "current":      avg_vals[-1] if avg_vals else 0,
            "peak":         max(avg_vals) if avg_vals else 0,
            "avg":          round(sum(avg_vals) / len(avg_vals), 1) if avg_vals else 0,
            "trend":        _calc_trend(avg_vals),
            "cached":       False,
            "agg_countries": list(country_dfs.keys()),
        }
    return result if result else {"error": "No keyword data in this region"}

def _build_result(keywords, df, from_cache):
    result = {}
    for kw in keywords:
        if kw in df.columns:
            series = df[kw]
            vals   = series.values.tolist()
            result[kw] = {
                "dates":   [str(d.date()) for d in series.index],
                "values":  [int(v) for v in vals],
                "current": int(series.iloc[-1]),
                "peak":    int(series.max()),
                "avg":     round(float(series.mean()), 1),
                "trend":   _calc_trend(vals),
                "cached":  from_cache,
            }
    return result

# ── Analysis engine ───────────────────────────────────────────────────────

def _slope(values):
    n = len(values)
    if n < 2: return 0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den else 0

def _volatility(values):
    if len(values) < 2: return 0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))

def _recent_acceleration(values):
    n = len(values)
    if n < 6: return 0
    cut = n * 2 // 3
    return _slope(values[cut:]) - _slope(values[:cut])

def _peak_recency(values):
    if not values: return 0.5
    return values.index(max(values)) / max(len(values) - 1, 1)

def _linear_forecast(values, steps=4):
    """Extrapolate n steps ahead using linear regression."""
    n = len(values)
    sl = _slope(values)
    base = values[-1]
    return [max(0, min(100, round(base + sl * (i + 1)))) for i in range(steps)]

def _velocity(values, window=7):
    """Average week-over-week point change over recent window."""
    if len(values) < window * 2: return 0
    recent = values[-window:]
    prior  = values[-window*2:-window]
    return round(sum(recent) / len(recent) - sum(prior) / len(prior), 1)

def _generate_analysis(trends_data, timeframe_label, group_name):
    items = []
    for kw, d in trends_data.items():
        vals = d.get('values', [])
        if not vals: continue
        sl        = _slope(vals)
        vol       = _volatility(vals)
        accel     = _recent_acceleration(vals)
        peak_rec  = _peak_recency(vals)
        pct_peak  = round(d['current'] / d['peak'] * 100 if d['peak'] > 0 else 0, 1)
        vel       = _velocity(vals)
        forecast  = _linear_forecast(vals, steps=4)
        items.append({
            "kw": kw,
            "current": d['current'], "peak": d['peak'], "avg": d['avg'],
            "trend": d['trend'],
            "slope": round(sl, 4),
            "velocity": vel,
            "volatility": round(vol, 1),
            "acceleration": round(accel, 4),
            "peak_recency": round(peak_rec, 2),
            "pct_from_peak": pct_peak,
            "forecast": forecast,
            "dates": d.get('dates', []),
        })

    if not items:
        return {"summary": "", "signals": [], "prediction": "", "forecasts": {}}

    items.sort(key=lambda x: x['current'], reverse=True)
    leader   = items[0]
    risers   = [x for x in items if x['trend'] == 'rising']
    fallers  = [x for x in items if x['trend'] == 'falling']
    stable   = [x for x in items if x['trend'] == 'stable']
    accel_pos = [x for x in items if x['acceleration'] > 0.05]
    top_by_slope = sorted(items, key=lambda x: x['slope'], reverse=True)

    # ── Summary ──
    if len(items) == 1:
        x = items[0]
        if x['trend'] == 'rising':
            summary = f"{x['kw']} is building search momentum over the past {timeframe_label}. Currently at index {x['current']}, it's averaging {x['avg']} with a consistent upward slope."
        elif x['trend'] == 'falling':
            summary = f"{x['kw']} has been losing search interest over {timeframe_label}, currently at {x['current']} — {x['pct_from_peak']}% of its period peak of {x['peak']}."
        else:
            summary = f"{x['kw']} is holding steady at {x['current']} over the past {timeframe_label}. Low volatility ({x['volatility']:.0f} pts) signals consistent, stable demand."
    else:
        if risers:
            rnames = " and ".join(x['kw'] for x in risers[:2])
            summary = f"{leader['kw']} leads search interest at {leader['current']} (index 0–100) over the past {timeframe_label}. {rnames} {'are' if len(risers)>1 else 'is'} gaining ground, while {', '.join(x['kw'] for x in fallers[:2]) or 'no keywords'} show{'s' if len(fallers)==1 else ''} declining momentum."
        elif fallers and len(fallers) > len(items) // 2:
            summary = f"{leader['kw']} leads at {leader['current']}, but the majority of this group is declining over the past {timeframe_label}. This may reflect category saturation or a shift in consumer attention."
        else:
            summary = f"{leader['kw']} leads the group at {leader['current']} over {timeframe_label}, with the field broadly stable. Differentiation between keywords is low — watch for an external catalyst to break the pattern."

    # ── Signals ──
    signals = []

    for x in accel_pos:
        if x['acceleration'] > 0.1:
            signals.append({
                "type": "accelerating", "kw": x['kw'],
                "text": f"{x['kw']} is accelerating — the rate of search growth in the latter half of the period is significantly higher than the first half. Early momentum signal."
            })

    for x in items:
        if x['peak_recency'] > 0.85 and x['current'] >= x['peak'] * 0.85:
            signals.append({
                "type": "peak", "kw": x['kw'],
                "text": f"{x['kw']} is at or near its period high (current {x['current']} vs peak {x['peak']}). Strong present-day relevance; watch for a pullback or sustained breakout."
            })

    for x in items:
        if x['velocity'] > 5:
            signals.append({
                "type": "velocity", "kw": x['kw'],
                "text": f"{x['kw']} is gaining +{x['velocity']} points week-over-week on average recently — short-term momentum is accelerating beyond the longer trend."
            })
        elif x['velocity'] < -5:
            signals.append({
                "type": "velocity_down", "kw": x['kw'],
                "text": f"{x['kw']} is shedding {abs(x['velocity'])} points week-over-week on average — short-term momentum is deteriorating faster than the longer trend suggests."
            })

    for x in fallers:
        if x['pct_from_peak'] < 40:
            signals.append({
                "type": "declining", "kw": x['kw'],
                "text": f"{x['kw']} has dropped to {x['pct_from_peak']}% of its period peak ({x['peak']}). Sustained decline — may require a major catalyst (drop, collab, editorial) to reverse."
            })

    for x in items:
        if x['volatility'] > 18:
            signals.append({
                "type": "volatile", "kw": x['kw'],
                "text": f"{x['kw']} shows high search volatility ({x['volatility']:.0f} pts std dev). Interest is driven by spikes — likely drop-dependent rather than organically growing."
            })

    for x in stable:
        if x['volatility'] < 8 and x['avg'] > 30:
            signals.append({
                "type": "steady", "kw": x['kw'],
                "text": f"{x['kw']} demonstrates category durability — consistent demand (avg {x['avg']}) with low volatility. Less hype-driven, more structurally embedded in consumer search."
            })

    # Convergence detection
    if len(items) >= 2:
        for i, a in enumerate(items):
            for b in items[i+1:]:
                gap_now = abs(a['current'] - b['current'])
                gap_slope = abs(a['slope'] - b['slope'])
                # converging if close in value and moving toward each other
                if gap_now < 12 and gap_slope > 0.08:
                    signals.append({
                        "type": "convergence", "kw": a['kw'],
                        "text": f"{a['kw']} and {b['kw']} are converging (current gap: {gap_now} pts). A crossover in search leadership is plausible in the near term."
                    })

    signals = signals[:6]

    # ── Prediction ──
    parts = []
    top_riser  = max(items, key=lambda x: x['slope'])
    top_faller = min(items, key=lambda x: x['slope'])

    if top_riser['slope'] > 0.05:
        fc = top_riser['forecast']
        parts.append(f"{top_riser['kw']} has the strongest upward slope and is projected to reach approximately {fc[-1]} (index) over the next 4 data periods if momentum holds.")

    if top_faller['slope'] < -0.05:
        fc = top_faller['forecast']
        parts.append(f"{top_faller['kw']} is on a downward trajectory, with a projected index of around {fc[-1]} if the current rate of decline continues.")

    if accel_pos:
        names = " and ".join(x['kw'] for x in accel_pos[:2])
        parts.append(f"Late-period acceleration in {names} is a meaningful leading indicator — this pattern often precedes a broader surge in organic search. Worth monitoring closely.")

    # Convergence outlook
    close_pairs = [(a['kw'], b['kw']) for i, a in enumerate(items) for b in items[i+1:] if abs(a['current']-b['current']) < 10 and abs(a['slope']-b['slope']) > 0.05]
    if close_pairs:
        a, b = close_pairs[0]
        parts.append(f"The gap between {a} and {b} is narrow — a leadership change in search interest is possible within the forecast window.")

    if not parts:
        parts.append("No strong directional signal detected across the group. The market appears to be in a holding pattern. External catalysts — new colorways, collaborations, editorial coverage — are likely what will move the needle.")

    prediction = " ".join(parts)

    # ── Forecasts (for chart) ──
    forecasts = {}
    for x in items:
        forecasts[x['kw']] = {
            "values": x['forecast'],
            "slope":  x['slope'],
            "velocity": x['velocity'],
        }

    return {
        "summary": summary,
        "signals": signals,
        "prediction": prediction,
        "forecasts": forecasts,
        "leaders": [{"kw": x["kw"], "current": x["current"], "trend": x["trend"]} for x in items[:3]]
    }

def _generate_region_analysis(region_data, keyword, timeframe_label):
    """Analyze one keyword's performance ACROSS regions: who leads, who's
    emerging, where it's fading, and how divergent the markets are."""
    items = []
    for region, kwmap in region_data.items():
        if region == '_meta':
            continue
        # Each region maps keyword -> series dict; take the requested kw or first
        d = kwmap.get(keyword) or (next(iter(kwmap.values())) if kwmap else None)
        if not d:
            continue
        vals = d.get('values', [])
        if not vals:
            continue
        sl    = _slope(vals)
        accel = _recent_acceleration(vals)
        vel   = _velocity(vals)
        items.append({
            "region": region,
            "current": d.get('current', vals[-1]),
            "peak":    d.get('peak', max(vals)),
            "avg":     d.get('avg', round(sum(vals)/len(vals), 1)),
            "trend":   d.get('trend', 'stable'),
            "slope":   round(sl, 4),
            "accel":   round(accel, 4),
            "velocity": vel,
            "pct_from_peak": round(d.get('current', vals[-1]) / d.get('peak', max(vals)) * 100
                                   if d.get('peak', max(vals)) > 0 else 0, 1),
        })

    if not items:
        return {"summary": "", "signals": [], "prediction": "", "forecasts": {}}

    by_current = sorted(items, key=lambda x: x['current'], reverse=True)
    by_slope   = sorted(items, key=lambda x: x['slope'], reverse=True)
    by_avg     = sorted(items, key=lambda x: x['avg'], reverse=True)
    leader   = by_current[0]
    laggard  = by_current[-1]
    hottest  = by_slope[0]
    coldest  = by_slope[-1]

    risers  = [x for x in items if x['slope'] > 0.05]
    fallers = [x for x in items if x['slope'] < -0.05]

    kw_label = keyword or "this keyword"

    # ── Summary ──
    spread = leader['current'] - laggard['current']
    if len(items) == 1:
        x = items[0]
        summary = (f"{kw_label} in {x['region']} sits at index {x['current']} "
                   f"(avg {x['avg']}) over the past {timeframe_label}, trending {x['trend']}.")
    else:
        lead_txt = f"{leader['region']} shows the strongest current interest in {kw_label} (index {leader['current']})"
        if spread > 40:
            div_txt = (f", while {laggard['region']} trails well behind at {laggard['current']} — "
                       f"a wide {spread}-point gap signals this is a highly region-specific trend.")
        elif spread > 15:
            div_txt = f", with {laggard['region']} the quietest market at {laggard['current']}."
        else:
            div_txt = (f". Interest is fairly even across all {len(items)} markets "
                       f"(only a {spread}-point spread), suggesting a globally synchronized trend.")
        summary = lead_txt + div_txt

    # ── Signals ──
    signals = []

    # Emerging market: low current but rising fast
    for x in risers:
        if x['current'] < leader['current'] * 0.6 and x['slope'] > 0.1:
            signals.append({
                "type": "accelerating", "kw": x['region'],
                "text": f"{x['region']} is an emerging market for {kw_label} — still below the leaders "
                        f"(index {x['current']}) but climbing fast. Trends often surface here before going global."
            })

    # Dominant + rising leader
    if leader['slope'] > 0.05:
        signals.append({
            "type": "peak", "kw": leader['region'],
            "text": f"{leader['region']} both leads and is still rising (index {leader['current']}, "
                    f"trending up). {kw_label} has strong, sustained demand in this market."
        })

    # Fading market: was high on average but now falling
    for x in fallers:
        if x['pct_from_peak'] < 55:
            signals.append({
                "type": "declining", "kw": x['region'],
                "text": f"{x['region']} is cooling — {kw_label} has fallen to {x['pct_from_peak']}% of its "
                        f"regional peak. Early interest here may be rotating to other silhouettes."
            })

    # Momentum standout
    if hottest['velocity'] > 5 and hottest['region'] != leader['region']:
        signals.append({
            "type": "velocity", "kw": hottest['region'],
            "text": f"{hottest['region']} has the fastest recent momentum (+{hottest['velocity']} pts "
                    f"week-over-week), outpacing every other market in rate of growth."
        })

    # Divergence signal
    if risers and fallers:
        signals.append({
            "type": "convergence", "kw": "Divergence",
            "text": f"Markets are splitting: {', '.join(r['region'] for r in risers[:2])} rising while "
                    f"{', '.join(f['region'] for f in fallers[:2])} decline. {kw_label} is regionalizing rather "
                    f"than moving as one global trend."
        })

    signals = signals[:6]

    # ── Outlook ──
    parts = []
    if hottest['slope'] > 0.05:
        parts.append(f"If current trajectories hold, {hottest['region']} is the market to watch for {kw_label} — "
                     f"it has the steepest upward slope and is likely to keep gaining.")
    if coldest['slope'] < -0.05:
        parts.append(f"{coldest['region']} is on the clearest downward path and may continue to soften.")
    if len(risers) >= max(2, len(items) // 2):
        parts.append(f"With {len(risers)} of {len(items)} markets rising, {kw_label} has broad-based "
                     f"regional momentum — a healthy sign for a durable trend rather than a one-market spike.")
    elif len(fallers) >= max(2, len(items) // 2):
        parts.append(f"With {len(fallers)} of {len(items)} markets declining, {kw_label} appears to be "
                     f"past its peak in most regions.")
    if not parts:
        parts.append(f"No dominant directional signal across regions — {kw_label} is holding a stable "
                     f"geographic pattern. A drop, collab, or editorial moment would be needed to shift it.")
    prediction = " ".join(parts)

    return {
        "summary": summary,
        "signals": signals,
        "prediction": prediction,
        "forecasts": {},
        "ranking": [{"region": x['region'], "current": x['current'], "trend": x['trend']} for x in by_current],
    }

def _generate_breakout_analysis(items):
    """Analyze a momentum-ranked micro-trend scan: which terms are breaking
    out, which are cooling, and what the overall micro-trend climate looks like."""
    enriched = []
    for it in items:
        vals = it.get('values', [])
        if not vals:
            continue
        forecast = _linear_forecast(vals, steps=4)
        enriched.append({
            "kw":       it.get('keyword', '?'),
            "current":  it.get('current', vals[-1]),
            "momentum": it.get('momentum', 0),
            "slope":    round(_slope(vals), 4),
            "velocity": _velocity(vals),
            "accel":    round(_recent_acceleration(vals), 4),
            "forecast": forecast,
        })
    if not enriched:
        return {"summary": "", "signals": [], "prediction": "", "forecasts": {}}

    enriched.sort(key=lambda x: x['momentum'], reverse=True)
    rising  = [x for x in enriched if x['momentum'] > 3]
    falling = [x for x in enriched if x['momentum'] < -3]
    flat    = [x for x in enriched if -3 <= x['momentum'] <= 3]
    top     = enriched[0]
    bottom  = enriched[-1]

    # ── Summary ──
    if rising:
        lead = ", ".join(f"{x['kw']} (+{x['momentum']})" for x in rising[:2])
        summary = (f"{len(rising)} of {len(enriched)} tracked micro-trends are breaking out this period. "
                   f"{top['kw']} leads with the strongest momentum (+{top['momentum']}), followed by {lead.split(', ',1)[-1] if len(rising)>1 else 'no others'}. "
                   f"{'A handful are cooling — ' + ', '.join(x['kw'] for x in falling[:2]) + '.' if falling else 'Nothing in the set is declining sharply.'}")
    elif falling:
        summary = (f"The micro-trend climate is cooling — {len(falling)} of {len(enriched)} terms are losing momentum, "
                   f"led downward by {bottom['kw']} ({bottom['momentum']}). No strong breakouts detected this scan.")
    else:
        summary = (f"Micro-trends are flat this period — momentum across all {len(enriched)} terms is muted. "
                   f"No clear breakout or collapse; the category is in a holding pattern.")

    # ── Signals ──
    signals = []
    for x in rising[:3]:
        if x['momentum'] > 12:
            signals.append({"type": "accelerating", "kw": x['kw'],
                "text": f"{x['kw']} is a strong breakout — second-half search interest is +{x['momentum']} above the first half. "
                        f"This is the kind of early acceleration that precedes a mainstream moment."})
        elif x['momentum'] > 3:
            signals.append({"type": "velocity", "kw": x['kw'],
                "text": f"{x['kw']} is gaining steadily (+{x['momentum']} momentum). Worth watching for a follow-through spike."})

    for x in falling[:2]:
        signals.append({"type": "declining", "kw": x['kw'],
            "text": f"{x['kw']} is fading ({x['momentum']} momentum) — interest is rotating away. "
                    f"Likely past its micro-trend peak unless a catalyst revives it."})

    # Accelerating standout that isn't already #1
    accel_star = max(enriched, key=lambda x: x['accel'])
    if accel_star['accel'] > 0.1 and accel_star['kw'] != top['kw']:
        signals.append({"type": "accelerating", "kw": accel_star['kw'],
            "text": f"{accel_star['kw']} is accelerating late in the window — its growth rate is speeding up, "
                    f"a leading signal even though it isn't the top mover yet."})

    if flat and len(flat) == len(enriched):
        signals.append({"type": "steady", "kw": "Category",
            "text": "No term shows decisive momentum — the micro-trend field is stable. "
                    "Breakouts usually need an external trigger (collab, celebrity, editorial) to ignite."})

    signals = signals[:6]

    # ── Outlook ──
    parts = []
    if top['momentum'] > 3:
        proj = top['forecast'][-1]
        parts.append(f"{top['kw']} is the clearest one to watch — if momentum holds, it projects toward index "
                     f"~{proj} over the next few periods.")
    if len(rising) >= 2:
        parts.append(f"With {len(rising)} terms rising together, there's broad micro-trend energy right now — "
                     f"a good moment to scout adjacent products and colorways.")
    if falling:
        parts.append(f"Conversely, {', '.join(x['kw'] for x in falling[:2])} look past-peak and may keep sliding.")
    if not parts:
        parts.append("No breakout candidate stands out. Re-scan in a week — micro-trends can flip quickly on a "
                     "single drop or viral moment.")
    prediction = " ".join(parts)

    # ── Forecast chips (top movers) ──
    forecasts = {}
    for x in enriched[:5]:
        forecasts[x['kw']] = {"values": x['forecast'], "slope": x['slope'], "velocity": x['velocity']}

    return {"summary": summary, "signals": signals, "prediction": prediction, "forecasts": forecasts}

def _calc_trend(values):
    if len(values) < 2: return "flat"
    recent = values[-min(8, len(values)):]
    first  = recent[:len(recent)//2]
    second = recent[len(recent)//2:]
    avg_first  = sum(first)/len(first)   if first  else 0
    avg_second = sum(second)/len(second) if second else 0
    diff = avg_second - avg_first
    if diff > 10:  return "rising"
    if diff < -10: return "falling"
    return "stable"

# ── Background cache warmer ───────────────────────────────────────────────
# Slowly pre-fetches every configured keyword group + micro-trend so normal
# use is served instantly from cache instead of live Google requests. Paces
# itself well below the rate limit and backs off hard on 429.
_prefetch_started = False
_prefetch_lock = threading.Lock()

def _prefetch_worker():
    time.sleep(5)   # let the server settle first
    cfg = load_config()
    # Wikipedia first: free, unlimited, makes the Wikipedia source instant
    for kws in cfg.get('keyword_groups', {}).values():
        try:
            _fetch_wikipedia(kws[:5], 'today 3-m', '')
        except Exception:
            pass
    # Then Google, very gently: one group/term at a time, extra spacing
    jobs = [(kws[:5], 'today 3-m', '') for kws in cfg.get('keyword_groups', {}).values()]
    jobs += [([kw], 'today 3-m', '') for kw in cfg.get('micro_trends', [])]
    for keywords, tf, geo in jobs:
        key = _cache_key('trends', sorted(keywords), tf, geo)
        if _cache_get(key) is not None:
            continue   # already fresh — costs nothing
        try:
            _google_throttle()
            time.sleep(3)   # background work must never crowd out the user
            pt = _get_pytrends()
            pt.build_payload(keywords, timeframe=tf, geo=geo)
            df = pt.interest_over_time()
            if df is not None and not df.empty:
                _cache_set(key, df)
        except Exception as e:
            if '429' in str(e) or 'Too Many' in str(e):
                _note_429()
                time.sleep(180)   # limited: back off, resume warming later

@app.before_request
def _start_prefetch():
    global _prefetch_started
    with _prefetch_lock:
        if _prefetch_started:
            return
        _prefetch_started = True
    threading.Thread(target=_prefetch_worker, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=True, port=5050)
