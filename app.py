"""Where to Eat — affordable lunch spots (mostly Concord and San Francisco), the cheap things worth ordering
at each, photos, and a map. Flask + SQLite, a sibling of Cookbooks / Dinner Log / the wish list / Roasted on CT 210.

Model:  place (a restaurant: where it is, cuisine, $-$$$)
          -> item (one dish or lunch deal with its price; "price checked" date so stale prices show)
          -> photo (of the place, a dish, or the menu; optionally tied to an item)

Public:  /            browse places, deals and the map (no private notes or who added what)
         /api/...     public JSON
Editors: /admin       same UI with editing; put this path behind Cloudflare Access
         /admin/api/  full JSON + writes; requires a verified Access JWT
                      (or a direct LAN request when LAN_EDIT=1)

Environment (see /etc/conf.d/lunch):
  DATA_DIR, CF_TEAM_DOMAIN, CF_AUD, ADMIN_EMAILS, LAN_EDIT, PUBLIC_VIEW, AREAS, CHEAP_UNDER,
  ANTHROPIC_API_KEY, ANTHROPIC_MODEL
"""
import base64, csv, datetime as dt, io, json, math, os, re, sqlite3, time, unicodedata
import urllib.error, urllib.parse, urllib.request, uuid
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, redirect, request, send_from_directory

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", APP_DIR / "data"))
PHOTO_DIR = DATA_DIR / "photos"
DB_PATH = DATA_DIR / "lunch.db"
CF_TEAM_DOMAIN = re.sub(r"^https?://", "", os.environ.get("CF_TEAM_DOMAIN", "").strip().strip("'\"")).split("/")[0]
CF_AUD = os.environ.get("CF_AUD", "").strip().strip("'\"")
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
LAN_EDIT = os.environ.get("LAN_EDIT", "1") == "1"
PUBLIC_VIEW = os.environ.get("PUBLIC_VIEW", "1") == "1"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5").strip()
UA = "where-to-eat/1.0 (personal lunch list; https://lunch.nickandrade.com)"


def parse_areas(s):
    """"Concord|37.978|-122.031;San Francisco|37.7749|-122.4194" -> [{name, lat, lng}]"""
    out = []
    for part in (s or "").split(";"):
        bits = [b.strip() for b in part.split("|")]
        if len(bits) == 3 and bits[0]:
            try:
                out.append({"name": bits[0], "lat": float(bits[1]), "lng": float(bits[2])})
            except ValueError:
                pass
    return out


AREAS = parse_areas(os.environ.get("AREAS", "Concord|37.9780|-122.0311;San Francisco|37.7749|-122.4194"))
try:
    CHEAP_UNDER = float(os.environ.get("CHEAP_UNDER", "15"))
except ValueError:
    CHEAP_UNDER = 15.0

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024  # several full-size phone photos in one request

# =========================================================================== db
SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL, area TEXT, neighborhood TEXT, address TEXT, cuisine TEXT,
  website TEXT, phone TEXT, hours TEXT, price_level INTEGER, rating REAL,
  notes TEXT, private_notes TEXT, closed INTEGER NOT NULL DEFAULT 0,
  lat REAL, lng REAL, geo_tried INTEGER NOT NULL DEFAULT 0,
  added_by TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
  name TEXT NOT NULL, price REAL, kind TEXT NOT NULL DEFAULT 'item', description TEXT, available TEXT,
  favorite INTEGER NOT NULL DEFAULT 0, price_checked TEXT,
  added_by TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS items_place ON items(place_id, price);
CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY,
  place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
  item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
  file TEXT NOT NULL, caption TEXT, pos INTEGER NOT NULL DEFAULT 0,
  added_by TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS photos_place ON photos(place_id, pos);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
ITEM_KINDS = ("item", "meal", "special")


def fold(s):
    """Lowercase without accents, so "pho" finds "Phở" and "jalapeno" finds "jalapeño"."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower().strip()


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.create_function("fold", 1, fold, deterministic=True)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def _close(_exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    con = connect()
    con.executescript(SCHEMA)
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema', '1')")
    con.commit()
    con.close()
    # staged uploads that never became part of a place
    cutoff = time.time() - 2 * 86400
    for p in PHOTO_DIR.glob("*tmp-*"):
        if p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)


# =========================================================================== helpers
def clean(s):
    if s is None:
        return None
    s = unicodedata.normalize("NFC", str(s)).strip()
    return s or None


def make_err(code, msg, **extra):
    r = jsonify(error=msg, **extra)
    r.status_code = code
    return r


def num(v, lo=None, hi=None, what="value"):
    if v in (None, ""):
        return None
    if isinstance(v, bool):
        abort(make_err(400, f"{what} must be a number"))
    try:
        x = float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        abort(make_err(400, f"{what} must be a number"))
    if not math.isfinite(x) or (lo is not None and x < lo) or (hi is not None and x > hi):
        abort(make_err(400, f"{what} must be between {lo:g} and {hi:g}"))
    return x


def today():
    return dt.date.today().isoformat()


def km_between(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def nearest_area(lat, lng, within_km=30):
    best = min(((km_between(lat, lng, a["lat"], a["lng"]), a["name"]) for a in AREAS), default=None)
    return best[1] if best and best[0] <= within_km else None


def normalize_url(u):
    u = clean(u)
    if u and not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u


def http_json(url, timeout=8, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json",
                                                          "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(4 * 1024 * 1024))


# ============================================================================== auth
_jwks = None


def access_identity():
    """Return the editor's email (or 'lan'), or None with the reason in g.auth_reason."""
    g.auth_reason = None
    token = request.headers.get("Cf-Access-Jwt-Assertion")
    via_cloudflare = request.headers.get("Cf-Ray") or request.headers.get("Cf-Connecting-Ip")
    if token:
        if not (CF_TEAM_DOMAIN and CF_AUD):
            g.auth_reason = ("Cloudflare Access signed you in, but the server isn't set up to check it yet: "
                             "set CF_TEAM_DOMAIN and CF_AUD in /etc/conf.d/lunch, then rc-service lunch restart.")
            return None
        global _jwks
        import jwt
        try:
            if _jwks is None:
                _jwks = jwt.PyJWKClient(f"https://{CF_TEAM_DOMAIN}/cdn-cgi/access/certs", cache_keys=True)
            key = _jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=CF_AUD,
                                issuer=f"https://{CF_TEAM_DOMAIN}")
        except Exception as e:  # noqa: BLE001 — any failure means "not an editor"
            g.auth_reason = f"Cloudflare Access sign-in rejected: {e}. Check CF_TEAM_DOMAIN and CF_AUD."
            app.logger.warning("Access: %s", g.auth_reason)
            return None
        email = (claims.get("email") or "").lower()
        if ADMIN_EMAILS and email not in ADMIN_EMAILS:
            g.auth_reason = f"Signed in as {email or 'an unknown user'}, which isn't in ADMIN_EMAILS."
            return None
        return email or "access-user"
    if LAN_EDIT and not via_cloudflare:
        return "lan"
    g.auth_reason = ("No Cloudflare Access sign-in reached the app. Check that the Access application for "
                     "this site covers the path 'admin'." if via_cloudflare else
                     "Editing from the LAN is turned off (LAN_EDIT=0).")
    return None


def editor_required(fn):
    @wraps(fn)
    def inner(*a, **kw):
        who = access_identity()
        if not who:
            return jsonify(error="Sign in to edit", reason=g.auth_reason), 401
        g.editor = who
        return fn(*a, **kw)
    return inner


def viewer_required(fn):
    """Public reads, unless PUBLIC_VIEW=0 makes everything editor-only."""
    @wraps(fn)
    def inner(*a, **kw):
        if not PUBLIC_VIEW and not access_identity():
            return jsonify(error="Sign in to view", reason=g.auth_reason), 401
        return fn(*a, **kw)
    return inner


def who():
    e = getattr(g, "editor", None)
    return None if e in (None, "lan", "access-user") else e


def two_ways(rule, fn, **opts):
    """Register a read route twice: /api/... (public fields) and /admin/api/... (everything, editors only)."""
    name = fn.__name__
    app.add_url_rule("/api/" + rule, name + "_public", viewer_required(lambda **kw: fn(private=False, **kw)), **opts)
    app.add_url_rule("/admin/api/" + rule, name + "_private", editor_required(lambda **kw: fn(private=True, **kw)), **opts)


# ============================================================================= pages
@app.get("/")
def index():
    if not PUBLIC_VIEW:
        return redirect("/admin")
    return send_from_directory(APP_DIR / "static", "index.html", max_age=0)


@app.get("/admin")
@app.get("/admin/")
def admin_index():
    return send_from_directory(APP_DIR / "static", "index.html", max_age=0)


@app.get("/static/<path:p>")
def static_files(p):
    return send_from_directory(APP_DIR / "static", p, max_age=300)


@app.get("/sw.js")
def service_worker():
    """Served from the root so its scope covers both / and /admin."""
    return send_from_directory(APP_DIR / "static", "sw.js", max_age=0, mimetype="text/javascript")


@app.get("/photos/<path:p>")
def photo_files(p):
    if "tmp-" in p and not access_identity():
        abort(404)
    if not PUBLIC_VIEW and not access_identity():
        abort(404)
    return send_from_directory(PHOTO_DIR, p, max_age=7 * 86400)


@app.get("/healthz")
def healthz():
    con = connect()
    n = con.execute("SELECT count(*) FROM places").fetchone()[0]
    con.close()
    return {"ok": True, "places": n}


@app.get("/api/me")
def me_public():
    return jsonify(editor=bool(access_identity()), public_view=PUBLIC_VIEW)


@app.get("/admin/api/me")
@editor_required
def me():
    return jsonify(editor=True, email=who())


@app.get("/api/config")
@viewer_required
def config():
    return jsonify(areas=AREAS, cheap_under=CHEAP_UNDER, menu_reading=bool(ANTHROPIC_API_KEY), public_view=PUBLIC_VIEW)


# ======================================================================= serializers
PRIVATE_PLACE = ("private_notes", "added_by", "geo_tried")
PRIVATE_ITEM = ("added_by",)


def place_out(r, private):
    d = dict(r)
    if not private:
        for k in PRIVATE_PLACE:
            d.pop(k, None)
    d["closed"] = bool(d.get("closed"))
    return d


def item_out(r, private):
    d = dict(r)
    if not private:
        for k in PRIVATE_ITEM:
            d.pop(k, None)
    d["favorite"] = bool(d.get("favorite"))
    return d


def photo_out(r, private):
    d = {k: r[k] for k in ("id", "place_id", "item_id", "file", "caption")}
    if private:
        d["added_by"] = r["added_by"]
    return d


# ========================================================================= read API
def place_filters(args, private):
    where, params = ["1=1"], []
    if not (private and args.get("closed") == "1"):
        where.append("p.closed=0")
    if args.get("area"):
        where.append("fold(p.area)=fold(?)")
        params.append(args["area"])
    if args.get("cuisine"):
        where.append("fold(p.cuisine)=fold(?)")
        params.append(args["cuisine"])
    for word in fold(args.get("q", "")).split():
        like = f"%{word}%"
        where.append("(fold(p.name) LIKE ? OR fold(p.cuisine) LIKE ? OR fold(p.neighborhood) LIKE ? OR fold(p.address) LIKE ?"
                     " OR EXISTS (SELECT 1 FROM items i WHERE i.place_id=p.id AND (fold(i.name) LIKE ? OR fold(i.description) LIKE ?)))")
        params += [like] * 6
    return where, params


def list_places(private):
    args = request.args
    max_price = num(args.get("max_price"), 0, 10000, "Max price")
    near = (num(args.get("lat"), -90, 90, "Latitude"), num(args.get("lng"), -180, 180, "Longitude"))
    where, params = place_filters(args, private)
    deal_limit = max_price if max_price is not None else CHEAP_UNDER
    if max_price is not None:
        where.append("EXISTS (SELECT 1 FROM items i WHERE i.place_id=p.id AND i.price<=?)")
        params.append(max_price)
    rows = db().execute(f"""
        SELECT p.*,
          (SELECT min(price) FROM items WHERE place_id=p.id) AS cheapest,
          (SELECT count(*) FROM items WHERE place_id=p.id AND price<=?) AS deals,
          (SELECT count(*) FROM items WHERE place_id=p.id) AS n_items,
          (SELECT file FROM photos WHERE place_id=p.id ORDER BY pos, id LIMIT 1) AS photo
        FROM places p WHERE {" AND ".join(where)}""", [deal_limit] + params).fetchall()
    places = [place_out(r, private) for r in rows]
    if None not in near:
        for p in places:
            p["km"] = round(km_between(near[0], near[1], p["lat"], p["lng"]), 2) if p["lat"] is not None else None
    sort = args.get("sort") or ("near" if None not in near else "cheapest")
    big = float("inf")
    keys = {
        "cheapest": lambda p: (p["cheapest"] is None, p["cheapest"] or 0, fold(p["name"])),
        "name": lambda p: fold(p["name"]),
        "new": lambda p: p["created_at"] or "",
        "rating": lambda p: (-(p["rating"] or -1), fold(p["name"])),
        "near": lambda p: (p.get("km") if p.get("km") is not None else big, fold(p["name"])),
    }
    places.sort(key=keys.get(sort, keys["cheapest"]), reverse=sort == "new")
    # the three cheapest items per place, for the card
    ids = [p["id"] for p in places]
    top = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in db().execute(f"""SELECT place_id, name, price, kind, favorite FROM items
                WHERE place_id IN ({",".join("?" * len(chunk))}) AND price IS NOT NULL
                ORDER BY place_id, favorite DESC, price, name""", chunk):
            lst = top.setdefault(r["place_id"], [])
            if len(lst) < 3:
                lst.append({"name": r["name"], "price": r["price"], "kind": r["kind"], "favorite": bool(r["favorite"])})
    for p in places:
        p["top_items"] = top.get(p["id"], [])
    return jsonify(places=places, cheap_under=CHEAP_UNDER)


def list_deals(private):
    """Every priced item, cheapest first: the "what can I get for under $X" view."""
    args = request.args
    max_price = num(args.get("max_price"), 0, 10000, "Max price")
    where, params = place_filters(args, private)
    where.append("i.price IS NOT NULL")
    if max_price is not None:
        where.append("i.price<=?")
        params.append(max_price)
    if args.get("kind") in ITEM_KINDS:
        where.append("i.kind=?")
        params.append(args["kind"])
    if args.get("favorites") == "1":
        where.append("i.favorite=1")
    rows = db().execute(f"""
        SELECT i.*, p.name AS place_name, p.area, p.neighborhood, p.cuisine, p.lat, p.lng,
          coalesce((SELECT file FROM photos WHERE item_id=i.id ORDER BY pos, id LIMIT 1),
                   (SELECT file FROM photos WHERE place_id=p.id ORDER BY pos, id LIMIT 1)) AS photo
        FROM items i JOIN places p ON p.id=i.place_id
        WHERE {" AND ".join(where)} ORDER BY i.price, fold(i.name) LIMIT 500""", params).fetchall()
    return jsonify(items=[item_out(r, private) for r in rows], cheap_under=CHEAP_UNDER)


def get_place(place_id, private):
    con = db()
    r = con.execute("SELECT * FROM places WHERE id=?", (place_id,)).fetchone()
    if not r or (r["closed"] and not private):
        abort(404)
    place = place_out(r, private)
    photos = [photo_out(p, private) for p in con.execute(
        "SELECT * FROM photos WHERE place_id=? ORDER BY pos, id", (place_id,))]
    items = [item_out(i, private) for i in con.execute(
        "SELECT * FROM items WHERE place_id=? ORDER BY price IS NULL, price, fold(name)", (place_id,))]
    for it in items:
        it["photos"] = [p for p in photos if p["item_id"] == it["id"]]
    place.update(items=items, photos=photos)
    return jsonify(place)


def facets(private):
    con = db()
    closed = "" if private else "WHERE closed=0"
    used = {r[0]: r[1] for r in con.execute(f"SELECT area, count(*) FROM places {closed} GROUP BY area") if r[0]}
    areas = [{"name": a["name"], "lat": a["lat"], "lng": a["lng"], "n": used.pop(a["name"], 0)} for a in AREAS]
    areas += [{"name": k, "lat": None, "lng": None, "n": v} for k, v in sorted(used.items())]
    cuisines = [{"name": r[0], "n": r[1]} for r in con.execute(
        f"SELECT cuisine, count(*) FROM places {closed} {'AND' if closed else 'WHERE'} cuisine IS NOT NULL "
        "GROUP BY fold(cuisine) ORDER BY fold(cuisine)")]
    n_items = con.execute("SELECT count(*) FROM items i JOIN places p ON p.id=i.place_id "
                          + ("" if private else "WHERE p.closed=0")).fetchone()[0]
    return jsonify(areas=areas, cuisines=cuisines, items=n_items)


def map_points(private):
    con = db()
    if private:
        backfill_locations(con)
    rows = con.execute(f"""SELECT p.id, p.name, p.area, p.neighborhood, p.cuisine, p.lat, p.lng, p.price_level, p.closed,
              (SELECT min(price) FROM items WHERE place_id=p.id) AS cheapest,
              (SELECT count(*) FROM items WHERE place_id=p.id AND price<=?) AS deals,
              (SELECT file FROM photos WHERE place_id=p.id ORDER BY pos, id LIMIT 1) AS photo
            FROM places p WHERE {"1=1" if private else "p.closed=0"}""", (CHEAP_UNDER,)).fetchall()
    points = [dict(r, closed=bool(r["closed"])) for r in rows if r["lat"] is not None and r["lng"] is not None]
    return jsonify(points=points, unplaced=len(rows) - len(points), cheap_under=CHEAP_UNDER)


two_ways("places", list_places, methods=["GET"])
two_ways("places/<int:place_id>", get_place, methods=["GET"])
two_ways("deals", list_deals, methods=["GET"])
two_ways("facets", facets, methods=["GET"])
two_ways("map", map_points, methods=["GET"])


# ========================================================================= places: write
PLACE_FIELDS = ("name", "area", "neighborhood", "address", "cuisine", "website", "phone", "hours", "price_level",
                "rating", "notes", "private_notes", "closed", "lat", "lng")


def place_values(data):
    vals = {}
    for k in PLACE_FIELDS:
        if k not in data:
            continue
        v = data[k]
        if k == "price_level":
            v = num(v, 1, 4, "Price level")
            v = int(v) if v is not None else None
        elif k == "rating":
            v = num(v, 0, 5, "Rating")
            v = round(v * 2) / 2 if v is not None else None
        elif k == "lat":
            v = num(v, -90, 90, "Latitude")
        elif k == "lng":
            v = num(v, -180, 180, "Longitude")
        elif k == "closed":
            v = 1 if v in (True, 1, "1", "true", "on") else 0
        elif k == "website":
            v = normalize_url(v)
        else:
            v = clean(v)
        vals[k] = v
    if "name" in vals and not vals["name"]:
        abort(make_err(400, "Name is required"))
    return vals


def geocode_address(address, area):
    """Address -> (lat, lng). OpenStreetMap Nominatim first, then Photon (same data, tolerates typos)."""
    if not address:
        return None
    q = address if not area or fold(area) in fold(address) else f"{address}, {area}"
    try:
        res = http_json("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "us"}), timeout=6)
        if res:
            return float(res[0]["lat"]), float(res[0]["lon"])
    except Exception as e:  # noqa: BLE001
        app.logger.info("Nominatim lookup failed for %s: %s", q, e)
    try:
        params = {"q": q, "limit": 1, "lang": "en"}
        a = next((x for x in AREAS if x["name"] == area), None)
        if a:
            params.update(lat=a["lat"], lon=a["lng"])
        res = http_json("https://photon.komoot.io/api/?" + urllib.parse.urlencode(params), timeout=6)
        feats = res.get("features") or []
        if feats:
            lng, lat = feats[0]["geometry"]["coordinates"][:2]
            return float(lat), float(lng)
    except Exception as e:  # noqa: BLE001
        app.logger.info("Photon lookup failed for %s: %s", q, e)
    app.logger.warning("No map location found for %s", q)
    return None


def locate(con, place_id):
    r = con.execute("SELECT address, area FROM places WHERE id=?", (place_id,)).fetchone()
    ll = geocode_address(r["address"], r["area"]) if r and r["address"] else None
    con.execute("UPDATE places SET lat=?, lng=?, geo_tried=1 WHERE id=?", (*(ll or (None, None)), place_id))
    if ll and not r["area"]:
        con.execute("UPDATE places SET area=? WHERE id=?", (nearest_area(*ll), place_id))


def backfill_locations(con, budget=3):
    """Addresses never looked up (e.g. a lookup service was down): a few each time the editor map opens."""
    pending = [r[0] for r in con.execute(
        "SELECT id FROM places WHERE lat IS NULL AND address IS NOT NULL AND geo_tried=0 LIMIT ?", (budget,))]
    for i, pid in enumerate(pending):
        if i:
            time.sleep(1.1)  # OpenStreetMap's usage policy: at most one request a second
        locate(con, pid)
    if pending:
        con.commit()


def after_place_write(con, pid, vals, before=None):
    """Fill in what the editor left out: map point from the address, area from the map point."""
    has_point = vals.get("lat") is not None and vals.get("lng") is not None
    moved = before is not None and "address" in vals and vals["address"] != before["address"]
    if not has_point and vals.get("address") and (before is None or moved or before["lat"] is None):
        locate(con, pid)
    row = con.execute("SELECT area, lat, lng FROM places WHERE id=?", (pid,)).fetchone()
    if not row["area"] and row["lat"] is not None:
        con.execute("UPDATE places SET area=? WHERE id=?", (nearest_area(row["lat"], row["lng"]), pid))


@app.post("/admin/api/places")
@editor_required
def create_place():
    """Body: place fields, plus optional uploads: [staged photo tokens] and items: [{name, price, ...}]."""
    data = request.get_json(force=True) or {}
    vals = place_values(data)
    if not vals.get("name"):
        return make_err(400, "Name is required")
    con = db()
    if vals.get("lat") is not None and vals.get("lng") is not None:
        vals["geo_tried"] = 1
    vals["added_by"] = who()
    cols = ", ".join(vals)
    pid = con.execute(f"INSERT INTO places({cols}) VALUES ({','.join('?' * len(vals))})", list(vals.values())).lastrowid
    after_place_write(con, pid, vals)
    for it in data.get("items") or []:
        insert_item(con, pid, it)
    attach_uploads(con, pid, data.get("uploads"))
    con.commit()
    r = get_place(pid, private=True)
    r.status_code = 201
    return r


@app.put("/admin/api/places/<int:place_id>")
@editor_required
def update_place(place_id):
    con = db()
    before = con.execute("SELECT * FROM places WHERE id=?", (place_id,)).fetchone()
    if not before:
        abort(404)
    vals = place_values(request.get_json(force=True) or {})
    if vals:
        if "lat" in vals or "lng" in vals:
            vals["geo_tried"] = 1
        sets = ", ".join(f"{k}=?" for k in vals)
        con.execute(f"UPDATE places SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?", [*vals.values(), place_id])
        after_place_write(con, place_id, vals, before)
    con.commit()
    return get_place(place_id, private=True)


@app.delete("/admin/api/places/<int:place_id>")
@editor_required
def delete_place(place_id):
    con = db()
    files = [r[0] for r in con.execute("SELECT file FROM photos WHERE place_id=?", (place_id,))]
    if not con.execute("DELETE FROM places WHERE id=?", (place_id,)).rowcount:
        abort(404)
    con.commit()
    for f in files:
        remove_image(f)
    return jsonify(ok=True)


# ========================================================================== items: write
def item_values(data, partial=False):
    vals = {}
    if "name" in data or not partial:
        vals["name"] = clean(data.get("name"))
        if not vals["name"]:
            abort(make_err(400, "Item name is required"))
    if "price" in data or not partial:
        vals["price"] = num(data.get("price"), 0, 10000, "Price")
        if vals["price"] is not None:
            vals["price"] = round(vals["price"], 2)
    if "kind" in data or not partial:
        vals["kind"] = data.get("kind") if data.get("kind") in ITEM_KINDS else "item"
    for k in ("description", "available"):
        if k in data:
            vals[k] = clean(data[k])
    if "favorite" in data:
        vals["favorite"] = 1 if data["favorite"] in (True, 1, "1", "true", "on") else 0
    if "price_checked" in data:
        d = clean(data["price_checked"])
        if d:
            try:
                d = dt.date.fromisoformat(d[:10]).isoformat()
            except ValueError:
                abort(make_err(400, "Price checked must be a date (YYYY-MM-DD)"))
        vals["price_checked"] = d
    return vals


def insert_item(con, place_id, data):
    vals = item_values(data)
    if vals.get("price") is not None:
        vals.setdefault("price_checked", today())
    vals.update(place_id=place_id, added_by=who())
    return con.execute(f"INSERT INTO items({', '.join(vals)}) VALUES ({','.join('?' * len(vals))})",
                       list(vals.values())).lastrowid


@app.post("/admin/api/places/<int:place_id>/items")
@editor_required
def add_items(place_id):
    """Body: one item {name, price, ...} or {items: [...]} (e.g. the rows picked after reading a menu photo)."""
    con = db()
    if not con.execute("SELECT 1 FROM places WHERE id=?", (place_id,)).fetchone():
        abort(404)
    data = request.get_json(force=True) or {}
    rows = data["items"] if isinstance(data.get("items"), list) else [data]
    for it in rows:
        insert_item(con, place_id, it)
    con.execute("UPDATE places SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (place_id,))
    con.commit()
    r = get_place(place_id, private=True)
    r.status_code = 201
    return r


@app.put("/admin/api/items/<int:item_id>")
@editor_required
def update_item(item_id):
    con = db()
    before = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not before:
        abort(404)
    vals = item_values(request.get_json(force=True) or {}, partial=True)
    # a new price is a fresh check, unless the editor dated it themselves
    if "price" in vals and vals["price"] != before["price"] and "price_checked" not in vals:
        vals["price_checked"] = today() if vals["price"] is not None else None
    if vals:
        sets = ", ".join(f"{k}=?" for k in vals)
        con.execute(f"UPDATE items SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?", [*vals.values(), item_id])
        con.commit()
    return get_place(before["place_id"], private=True)


@app.post("/admin/api/items/<int:item_id>/checked")
@editor_required
def confirm_price(item_id):
    """"Still this price": bump the price-checked date to today without changing anything else."""
    con = db()
    r = con.execute("SELECT place_id FROM items WHERE id=?", (item_id,)).fetchone()
    if not r:
        abort(404)
    con.execute("UPDATE items SET price_checked=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (today(), item_id))
    con.commit()
    return get_place(r["place_id"], private=True)


@app.delete("/admin/api/items/<int:item_id>")
@editor_required
def delete_item(item_id):
    con = db()
    r = con.execute("SELECT place_id FROM items WHERE id=?", (item_id,)).fetchone()
    if not r:
        abort(404)
    con.execute("DELETE FROM items WHERE id=?", (item_id,))
    con.commit()
    return get_place(r["place_id"], private=True)


# ========================================================================= photos
PHOTO_TOKEN = re.compile(r"(tmp|\d+)-[0-9a-f]{10}\.jpg")


def store_image(raw, prefix):
    """Re-encode as JPEG: turned upright, at most 1600px, plus a 520px thumbnail. Re-encoding also drops
    the phone's EXIF data, GPS included."""
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if img.width < 60 or img.height < 60:
        raise ValueError("image too small")
    name = f"{prefix}-{uuid.uuid4().hex[:10]}.jpg"
    big = img.copy()
    big.thumbnail((1600, 1600))
    big.save(PHOTO_DIR / name, "JPEG", quality=84, optimize=True)
    small = img.copy()
    small.thumbnail((520, 520))
    small.save(PHOTO_DIR / ("t-" + name), "JPEG", quality=80, optimize=True)
    return name


def remove_image(name):
    (PHOTO_DIR / name).unlink(missing_ok=True)
    (PHOTO_DIR / ("t-" + name)).unlink(missing_ok=True)


def next_pos(con, place_id):
    return con.execute("SELECT coalesce(max(pos)+1, 0) FROM photos WHERE place_id=?", (place_id,)).fetchone()[0]


@app.post("/admin/api/uploads")
@editor_required
def upload_staged():
    """Photos taken before the place exists (add flow). Returns tokens to attach on save or read with Claude."""
    files = request.files.getlist("file")
    if not files:
        return make_err(400, "No image")
    out = []
    for f in files:
        try:
            out.append(store_image(f.read(), "tmp"))
        except Exception as e:  # noqa: BLE001
            return make_err(400, f"Couldn't read that image: {e}")
    return jsonify(uploads=out)


def attach_uploads(con, place_id, tokens):
    pos = next_pos(con, place_id)
    for t in tokens or []:
        if not (isinstance(t, str) and t.startswith("tmp-") and PHOTO_TOKEN.fullmatch(t) and (PHOTO_DIR / t).exists()):
            continue
        name = f"{place_id}-{t[4:]}"
        (PHOTO_DIR / t).rename(PHOTO_DIR / name)
        if (PHOTO_DIR / ("t-" + t)).exists():
            (PHOTO_DIR / ("t-" + t)).rename(PHOTO_DIR / ("t-" + name))
        con.execute("INSERT INTO photos(place_id, file, pos, added_by) VALUES (?,?,?,?)", (place_id, name, pos, who()))
        pos += 1


def item_of_place(con, place_id, item_id):
    if item_id in (None, "", "null"):
        return None
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        abort(make_err(400, "Unknown item"))
    if not con.execute("SELECT 1 FROM items WHERE id=? AND place_id=?", (item_id, place_id)).fetchone():
        abort(make_err(400, "That item belongs to another place"))
    return item_id


@app.post("/admin/api/places/<int:place_id>/photos")
@editor_required
def upload_place_photos(place_id):
    """multipart: file (one or more), optional item_id and caption."""
    con = db()
    if not con.execute("SELECT 1 FROM places WHERE id=?", (place_id,)).fetchone():
        abort(404)
    item_id = item_of_place(con, place_id, request.form.get("item_id"))
    caption = clean(request.form.get("caption"))
    files = request.files.getlist("file")
    if not files:
        return make_err(400, "No image")
    pos = next_pos(con, place_id)
    for f in files:
        try:
            name = store_image(f.read(), str(place_id))
        except Exception as e:  # noqa: BLE001
            con.rollback()
            return make_err(400, f"Couldn't read that image: {e}")
        con.execute("INSERT INTO photos(place_id, item_id, file, caption, pos, added_by) VALUES (?,?,?,?,?,?)",
                    (place_id, item_id, name, caption, pos, who()))
        pos += 1
    con.commit()
    return get_place(place_id, private=True)


@app.put("/admin/api/photos/<int:pid>")
@editor_required
def update_photo(pid):
    con = db()
    r = con.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
    if not r:
        abort(404)
    data = request.get_json(force=True) or {}
    if "item_id" in data:
        con.execute("UPDATE photos SET item_id=? WHERE id=?", (item_of_place(con, r["place_id"], data["item_id"]), pid))
    if "caption" in data:
        con.execute("UPDATE photos SET caption=? WHERE id=?", (clean(data["caption"]), pid))
    if data.get("cover"):
        con.execute("UPDATE photos SET pos=pos+1 WHERE place_id=?", (r["place_id"],))
        con.execute("UPDATE photos SET pos=0 WHERE id=?", (pid,))
    con.commit()
    return get_place(r["place_id"], private=True)


@app.delete("/admin/api/photos/<int:pid>")
@editor_required
def delete_photo(pid):
    con = db()
    r = con.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
    if not r:
        abort(404)
    con.execute("DELETE FROM photos WHERE id=?", (pid,))
    con.commit()
    remove_image(r["file"])
    return get_place(r["place_id"], private=True)


# ===================================================================== places nearby (OSM)
FOOD = "restaurant|fast_food|cafe|food_court|bar|pub|ice_cream|biergarten"


def osm_place(el, lat, lng):
    t = el.get("tags") or {}
    plat = el.get("lat") or (el.get("center") or {}).get("lat")
    plng = el.get("lon") or (el.get("center") or {}).get("lon")
    street = " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street")) if x)
    address = ", ".join(x for x in (street, t.get("addr:city")) if x) or None
    cuisine = (t.get("cuisine") or "").split(";")[0].replace("_", " ").strip().title() or None
    return {"name": t.get("name"), "address": address, "cuisine": cuisine, "website": t.get("website") or t.get("contact:website"),
            "phone": t.get("phone") or t.get("contact:phone"), "hours": t.get("opening_hours"),
            "lat": plat, "lng": plng, "m": round(km_between(lat, lng, plat, plng) * 1000) if plat and plng else None}


@app.get("/admin/api/nearby")
@editor_required
def nearby():
    """Phone GPS -> restaurants around it on OpenStreetMap (to pre-fill the add form), the street address,
    and places already in the list within ~150 m (so the same place isn't added twice)."""
    lat = num(request.args.get("lat"), -90, 90, "Latitude")
    lng = num(request.args.get("lng"), -180, 180, "Longitude")
    if lat is None or lng is None:
        return make_err(400, "lat and lng are required")
    out = {"lat": round(lat, 6), "lng": round(lng, 6), "area": nearest_area(lat, lng), "osm": [], "warnings": []}
    try:
        q = f'[out:json][timeout:10];nwr(around:90,{lat},{lng})["amenity"~"^({FOOD})$"]["name"];out center tags 25;'
        res = http_json("https://overpass-api.de/api/interpreter", timeout=12,
                        data=urllib.parse.urlencode({"data": q}).encode())
        found = [osm_place(el, lat, lng) for el in res.get("elements", [])]
        out["osm"] = sorted((f for f in found if f["name"] and f["m"] is not None), key=lambda f: f["m"])[:12]
    except Exception as e:  # noqa: BLE001
        app.logger.info("Overpass lookup failed: %s", e)
        out["warnings"].append("OpenStreetMap's restaurant list didn't answer, so type the name.")
    try:
        d = http_json("https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
            {"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 18, "addressdetails": 1}))
        a = d.get("address") or {}
        street = " ".join(x for x in (a.get("house_number"), a.get("road")) if x)
        city = a.get("city") or a.get("town") or a.get("village")
        out["address"] = ", ".join(x for x in (street, city) if x) or None
        out["neighborhood"] = a.get("neighbourhood") or a.get("suburb") or a.get("quarter")
        if not out["area"]:
            out["area"] = city
    except Exception as e:  # noqa: BLE001
        app.logger.info("Nominatim reverse lookup failed: %s", e)
        out["warnings"].append("Couldn't look up the street address; the map pin is still set.")
    known = []
    for r in db().execute("SELECT id, name, address, lat, lng FROM places WHERE lat IS NOT NULL"):
        m = km_between(lat, lng, r["lat"], r["lng"]) * 1000
        if m < 150:
            known.append({"id": r["id"], "name": r["name"], "address": r["address"], "m": round(m)})
    out["known"] = sorted(known, key=lambda k: k["m"])[:5]
    return jsonify(out)


@app.get("/admin/api/geocode")
@editor_required
def geocode_route():
    """Preview where an address lands before saving."""
    ll = geocode_address(clean(request.args.get("address")), clean(request.args.get("area")))
    if not ll:
        return make_err(404, "Couldn't find that address on the map")
    return jsonify(lat=ll[0], lng=ll[1], area=nearest_area(*ll))


# ===================================================================== menu reading (Claude)
MENU_PROMPT = """These are photos of a restaurant's menu, menu board, or specials sign. List what's on it with prices.

Rules:
- Only use what's printed. Don't invent dishes or prices. Use null for a price that isn't shown.
- name: the dish as printed (fix ALL CAPS to normal capitalization). description: a short description if one is printed.
- price: a number in dollars, the lowest price if there are sizes (put the sizes in "description", e.g. "small $9 / large $12").
- kind: "meal" for a combo or lunch special that comes with sides or a drink, "special" for a daily or time-limited deal, otherwise "item".
- available: when it's offered if the menu says so (e.g. "Mon–Fri 11–3", "Tuesdays"), otherwise null.
- Skip drinks, sides and add-ons unless they are the only things on the photo.

Reply with only JSON: {"items": [{"name", "price", "description", "kind", "available"}], "uncertain": [string]}"""


def menu_jpeg(path):
    from PIL import Image
    img = Image.open(path).convert("RGB")
    img.thumbnail((1568, 1568))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=86)
    return out.getvalue()


def call_claude(images, prompt):
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(im).decode()}} for im in images]
    content.append({"type": "text", "text": prompt})
    body = {"model": ANTHROPIC_MODEL, "max_tokens": 4000, "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), headers={
        "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Claude API error {e.code}: {e.read().decode(errors='replace')[:300]}")
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def parse_menu(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON in the response")
    data = json.loads(m.group())
    items = []
    for it in data.get("items") or []:
        name = clean(it.get("name")) if isinstance(it, dict) else None
        if not name:
            continue
        try:
            price = round(float(str(it.get("price")).replace("$", "")), 2) if it.get("price") not in (None, "") else None
        except ValueError:
            price = None
        items.append({"name": name[:120], "price": price, "description": clean(it.get("description")),
                      "kind": it.get("kind") if it.get("kind") in ITEM_KINDS else "item",
                      "available": clean(it.get("available"))})
    items.sort(key=lambda i: (i["price"] is None, i["price"] or 0))
    return {"items": items[:80], "uncertain": [str(x) for x in data.get("uncertain") or []][:10]}


@app.post("/admin/api/menu/read")
@editor_required
def read_menu():
    """Body: {photos: [file names of staged or saved photos]} -> candidate items, cheapest first, for review."""
    if not ANTHROPIC_API_KEY:
        return make_err(503, "Menu reading needs ANTHROPIC_API_KEY in /etc/conf.d/lunch")
    files = [f for f in ((request.get_json(force=True) or {}).get("photos") or [])
             if isinstance(f, str) and PHOTO_TOKEN.fullmatch(f) and (PHOTO_DIR / f).exists()][:4]
    if not files:
        return make_err(400, "Pick a photo of the menu first")
    try:
        out = parse_menu(call_claude([menu_jpeg(PHOTO_DIR / f) for f in files], MENU_PROMPT))
    except Exception as e:  # noqa: BLE001
        return make_err(502, f"Couldn't read the menu: {e}")
    return jsonify(out)


# ========================================================================== export
@app.get("/admin/api/export.json")
@editor_required
def export_json():
    con = db()
    data = {"exported": dt.datetime.now().isoformat(timespec="seconds"),
            "places": [dict(r) for r in con.execute("SELECT * FROM places ORDER BY id")],
            "items": [dict(r) for r in con.execute("SELECT * FROM items ORDER BY id")],
            "photos": [dict(r) for r in con.execute("SELECT * FROM photos ORDER BY id")]}
    return Response(json.dumps(data, indent=1, ensure_ascii=False), mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename=lunch-{today()}.json"})


@app.get("/admin/api/export.csv")
@editor_required
def export_csv():
    """One row per menu item (places without items get one row with the item columns blank)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["place", "area", "neighborhood", "address", "cuisine", "item", "price", "kind", "available",
                "favorite", "price_checked", "lat", "lng"])
    for r in db().execute("""SELECT p.name, p.area, p.neighborhood, p.address, p.cuisine, i.name, i.price, i.kind,
            i.available, i.favorite, i.price_checked, p.lat, p.lng
            FROM places p LEFT JOIN items i ON i.place_id=p.id ORDER BY fold(p.name), i.price"""):
        w.writerow(list(r))
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=lunch-{today()}.csv"})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8769)), debug=True)
