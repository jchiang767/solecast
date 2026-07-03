from flask import Flask, jsonify, request, send_from_directory
from pytrends.request import TrendReq
import json, os, time, hashlib, math

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
]

# ── App setup ─────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder='static')

_cache = {}
CACHE_TTL = 600

def _cache_key(*args):
    return hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()

def _cache_get(key):
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
        del _cache[key]
    return None

def _cache_set(key, data):
    _cache[key] = (time.time(), data)

def _get_pytrends():
    return TrendReq(hl='en-US', tz=360, timeout=(10, 20))

def _trends_request_with_retry(keywords, timeframe, geo, max_retries=2):
    key = _cache_key('trends', sorted(keywords), timeframe, geo)
    cached = _cache_get(key)
    if cached is not None:
        return cached, True
    last_err = None
    for attempt in range(max_retries):
        try:
            pt = _get_pytrends()
            pt.build_payload(keywords, timeframe=timeframe, geo=geo)
            df = pt.interest_over_time()
            _cache_set(key, df)
            return df, False
        except Exception as e:
            last_err = e
            if '429' in str(e) or 'Too Many' in str(e):
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
    }
}

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
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

@app.route('/api/suggest')
def suggest():
    q = request.args.get('q', '').strip().lower()
    if not q or len(q) < 2:
        return jsonify([])
    curated = sorted(
        [t for t in SNEAKER_TERMS if q in t.lower()],
        key=lambda t: (not t.lower().startswith(q), t.lower())
    )[:6]
    key = _cache_key('suggest', q)
    gt = _cache_get(key)
    if gt is None:
        try:
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

@app.route('/api/trends', methods=['POST'])
def get_trends():
    body = request.json
    keywords = [k.strip() for k in body.get('keywords', []) if k.strip()][:5]
    timeframe = body.get('timeframe', 'today 3-m')
    geo = body.get('geo', '')
    if not keywords:
        return jsonify({"error": "No keywords provided"}), 400
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
    if not keywords or not geos:
        return jsonify({"error": "Provide keywords and at least one region"}), 400

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
            time.sleep(0.6)
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
    if not keyword:
        return jsonify({"error": "No keyword provided"}), 400
    key = _cache_key('related', keyword, timeframe)
    cached = _cache_get(key)
    if cached:
        return jsonify(cached)
    try:
        pt = _get_pytrends()
        pt.build_payload([keyword], timeframe=timeframe)
        rel = pt.related_queries()
        rising, top = [], []
        if keyword in rel:
            if rel[keyword]['rising'] is not None:
                rising = rel[keyword]['rising'].head(10).to_dict('records')
            if rel[keyword]['top'] is not None:
                top = rel[keyword]['top'].head(10).to_dict('records')
        result = {"rising": rising, "top": top}
        _cache_set(key, result)
        return jsonify(result)
    except Exception as e:
        msg = str(e)
        if '429' in msg or 'Too Many' in msg:
            return jsonify({"error": "Rate limited. Wait 30–60s.", "rate_limited": True}), 429
        return jsonify({"error": msg}), 500

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
    results = []
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
            if not from_cache:
                time.sleep(0.7)   # be gentle between live requests
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
            time.sleep(0.5)
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

if __name__ == '__main__':
    app.run(debug=True, port=5050)
