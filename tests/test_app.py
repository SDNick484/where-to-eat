"""Run: python3 -m pytest -q tests   (DATA_DIR is a temp folder; no network)"""
import io, os, sys, tempfile, time
from pathlib import Path

import pytest

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="lunch-test-"), CF_TEAM_DOMAIN="team.example.com", CF_AUD="aud123",
                  ADMIN_EMAILS="nick@example.com,friend@example.com", LAN_EDIT="1", CHEAP_UNDER="15")
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A  # noqa: E402

GEO = {"1950 Grant St, Concord": (37.9779, -122.0325)}
A.geocode_address = lambda address, area: GEO.get(address)  # no network in tests
CF = {"Cf-Ray": "abc", "Cf-Connecting-Ip": "203.0.113.9"}


@pytest.fixture()
def c():
    return A.app.test_client()


def jpeg(size=(300, 400)):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(b, "JPEG")
    b.seek(0)
    return b


def add_place(c, **over):
    body = {"name": "Taqueria Los Gallos", "address": "1950 Grant St, Concord", "cuisine": "Mexican", "price_level": 1,
            "private_notes": "cash only", "items": [
                {"name": "Super burrito", "price": "$11.50", "kind": "item"},
                {"name": "Lunch plate", "price": 13, "kind": "meal", "available": "Mon–Fri 11–3"},
                {"name": "Shrimp cocktail", "price": 18.99}]}
    body.update(over)
    r = c.post("/admin/api/places", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


# ------------------------------------------------------------------ places + items
def test_create_place_geocodes_and_sorts_items(c):
    p = add_place(c)
    assert (p["lat"], p["lng"]) == GEO["1950 Grant St, Concord"]
    assert p["area"] == "Concord"  # nearest configured area to the geocoded point
    assert [i["price"] for i in p["items"]] == [11.5, 13, 18.99]
    assert p["items"][0]["price_checked"] == A.today()


def test_public_hides_private_fields(c):
    p = add_place(c, name="Private Bits")
    pub = c.get(f"/api/places/{p['id']}").get_json()
    assert "private_notes" not in pub and "added_by" not in pub
    assert c.get(f"/admin/api/places/{p['id']}").get_json()["private_notes"] == "cash only"


def test_area_from_gps_when_no_address(c):
    p = add_place(c, name="Mission Pho", address=None, lat=37.7599, lng=-122.4148, items=[])
    assert p["area"] == "San Francisco"
    far = add_place(c, name="Tahoe Grill", address=None, lat=39.09, lng=-120.03, items=[])
    assert far["area"] is None


def test_places_list_cheapest_and_filters(c):
    add_place(c, name="Cheap Eats SF", address=None, lat=37.78, lng=-122.41, items=[{"name": "Banh mi", "price": 7}])
    add_place(c, name="Fancy SF", address=None, lat=37.79, lng=-122.40, items=[{"name": "Omakase", "price": 95}])
    d = c.get("/api/places?area=San Francisco").get_json()
    names = [p["name"] for p in d["places"]]
    assert names.index("Cheap Eats SF") < names.index("Fancy SF")
    cheap = next(p for p in d["places"] if p["name"] == "Cheap Eats SF")
    assert cheap["cheapest"] == 7 and cheap["deals"] == 1 and cheap["top_items"][0]["name"] == "Banh mi"
    under = [p["name"] for p in c.get("/api/places?max_price=10").get_json()["places"]]
    assert "Cheap Eats SF" in under and "Fancy SF" not in under
    assert [p["name"] for p in c.get("/api/places?q=banh").get_json()["places"]] == ["Cheap Eats SF"]
    near = c.get("/api/places?lat=37.781&lng=-122.411").get_json()["places"]
    assert near[0]["name"] == "Cheap Eats SF" and near[0]["km"] < 1


def test_deals_cheapest_first_with_cap(c):
    add_place(c, name="Deal Town")
    items = c.get("/api/deals?max_price=15").get_json()["items"]
    prices = [i["price"] for i in items]
    assert prices == sorted(prices) and all(p <= 15 for p in prices)
    assert any(i["place_name"] == "Deal Town" for i in items)
    meals = c.get("/api/deals?kind=meal").get_json()["items"]
    assert meals and all(i["kind"] == "meal" for i in meals)


def test_item_price_change_bumps_checked_date(c):
    p = add_place(c, name="Price Watch")
    it = p["items"][0]
    A.db  # noqa: B018
    with A.app.app_context():
        A.db().execute("UPDATE items SET price_checked='2025-01-01' WHERE id=?", (it["id"],))
        A.db().commit()
    p = c.put(f"/admin/api/items/{it['id']}", json={"description": "with cheese"}).get_json()
    assert next(i for i in p["items"] if i["id"] == it["id"])["price_checked"] == "2025-01-01"
    p = c.put(f"/admin/api/items/{it['id']}", json={"price": 12.25}).get_json()
    row = next(i for i in p["items"] if i["id"] == it["id"])
    assert row["price"] == 12.25 and row["price_checked"] == A.today()
    with A.app.app_context():
        A.db().execute("UPDATE items SET price_checked='2025-01-01' WHERE id=?", (it["id"],))
        A.db().commit()
    p = c.post(f"/admin/api/items/{it['id']}/checked").get_json()
    assert next(i for i in p["items"] if i["id"] == it["id"])["price_checked"] == A.today()


def test_validation(c):
    assert c.post("/admin/api/places", json={"name": " "}).status_code == 400
    assert c.post("/admin/api/places", json={"name": "X", "rating": 9}).status_code == 400
    p = add_place(c, name="Validate", items=[])
    assert c.post(f"/admin/api/places/{p['id']}/items", json={"name": "Taco", "price": "cheap"}).status_code == 400
    assert c.post(f"/admin/api/places/{p['id']}/items", json={"price": 3}).status_code == 400
    assert c.post(f"/admin/api/places/{p['id']}/items", json={"name": "Taco", "price": "-1"}).status_code == 400


def test_closed_places_hidden_from_public(c):
    p = add_place(c, name="Gone Now")
    c.put(f"/admin/api/places/{p['id']}", json={"closed": True})
    assert c.get(f"/api/places/{p['id']}").status_code == 404
    assert "Gone Now" not in [x["name"] for x in c.get("/api/places").get_json()["places"]]
    assert "Gone Now" in [x["name"] for x in c.get("/admin/api/places?closed=1").get_json()["places"]]


# ------------------------------------------------------------------ photos
def test_photos_staged_attached_tagged_and_deleted(c):
    up = c.post("/admin/api/uploads", data={"file": [(jpeg(), "a.jpg"), (jpeg(), "b.jpg")]},
                content_type="multipart/form-data").get_json()["uploads"]
    assert len(up) == 2 and all(t.startswith("tmp-") for t in up)
    assert c.get(f"/photos/{up[0]}", headers=CF).status_code == 404  # staged photos aren't public
    p = add_place(c, name="Photo Place", uploads=up + ["../../etc/passwd", "tmp-zzz.jpg"])
    assert len(p["photos"]) == 2
    f = p["photos"][0]["file"]
    assert f.startswith(f"{p['id']}-") and (A.PHOTO_DIR / f).exists() and (A.PHOTO_DIR / ("t-" + f)).exists()
    assert c.get(f"/photos/{f}", headers=CF).status_code == 200

    burrito = p["items"][0]["id"]
    p = c.post(f"/admin/api/places/{p['id']}/photos", data={"file": (jpeg(), "dish.jpg"), "item_id": str(burrito),
               "caption": "the burrito"}, content_type="multipart/form-data").get_json()
    dish = next(i for i in p["items"] if i["id"] == burrito)["photos"]
    assert len(dish) == 1 and dish[0]["caption"] == "the burrito"
    deal = next(i for i in c.get("/api/deals").get_json()["items"] if i["id"] == burrito)
    assert deal["photo"] == dish[0]["file"]  # a dish's own photo beats the place's

    other = add_place(c, name="Other Place", items=[{"name": "Soup", "price": 6}])
    r = c.put(f"/admin/api/photos/{p['photos'][0]['id']}", json={"item_id": other["items"][0]["id"]})
    assert r.status_code == 400

    last = p["photos"][-1]
    p = c.put(f"/admin/api/photos/{last['id']}", json={"cover": True}).get_json()
    assert p["photos"][0]["id"] == last["id"]

    p = c.delete(f"/admin/api/photos/{last['id']}").get_json()
    assert not (A.PHOTO_DIR / last["file"]).exists() and len(p["photos"]) == 2
    files = [x["file"] for x in p["photos"]]
    assert c.delete(f"/admin/api/places/{p['id']}").status_code == 200
    assert not any((A.PHOTO_DIR / x).exists() for x in files)


def test_bad_image_rejected(c):
    r = c.post("/admin/api/uploads", data={"file": (io.BytesIO(b"not an image"), "x.jpg")},
               content_type="multipart/form-data")
    assert r.status_code == 400


def test_exif_rotation_applied(c):
    from PIL import Image
    img = Image.new("RGB", (400, 200), (10, 10, 10))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° on display, as phones do
    b = io.BytesIO()
    img.save(b, "JPEG", exif=exif.tobytes())
    b.seek(0)
    tok = c.post("/admin/api/uploads", data={"file": (b, "r.jpg")}, content_type="multipart/form-data").get_json()["uploads"][0]
    out = Image.open(A.PHOTO_DIR / tok)
    assert out.size == (200, 400) and not out.getexif().get(0x0112)


# ------------------------------------------------------------------ auth
def test_writes_need_access_through_cloudflare(c):
    r = c.post("/admin/api/places", json={"name": "Sneaky"}, headers=CF)
    assert r.status_code == 401 and "admin" in r.get_json()["reason"]
    assert c.get("/api/places", headers=CF).status_code == 200  # public reads still work


def make_token(email, aud="aud123"):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tok = jwt.encode({"email": email, "aud": aud, "iss": "https://team.example.com", "exp": int(time.time()) + 300},
                     key, algorithm="RS256")
    A._jwks = type("K", (), {"get_signing_key_from_jwt": lambda self, t: type("S", (), {"key": key.public_key()})()})()
    return tok


def test_access_jwt_and_admin_emails(c):
    ok = c.post("/admin/api/places", json={"name": "Friend's Find"},
                headers={**CF, "Cf-Access-Jwt-Assertion": make_token("Friend@Example.com")})
    assert ok.status_code == 201 and ok.get_json()["added_by"] == "friend@example.com"
    no = c.post("/admin/api/places", json={"name": "Stranger"},
                headers={**CF, "Cf-Access-Jwt-Assertion": make_token("stranger@example.com")})
    assert no.status_code == 401 and "ADMIN_EMAILS" in no.get_json()["reason"]
    bad_aud = c.post("/admin/api/places", json={"name": "Wrong app"},
                     headers={**CF, "Cf-Access-Jwt-Assertion": make_token("nick@example.com", aud="other")})
    assert bad_aud.status_code == 401
    A._jwks = None


def test_private_mode(c, monkeypatch):
    monkeypatch.setattr(A, "PUBLIC_VIEW", False)
    assert c.get("/api/places", headers=CF).status_code == 401
    assert c.get("/", headers=CF).status_code == 302
    assert c.get("/api/places").status_code == 200  # LAN


# ------------------------------------------------------------------ helpers
def test_parse_areas_and_nearest():
    areas = A.parse_areas("Concord|37.978|-122.031; bad ;Oakland|x|y;San Francisco|37.7749|-122.4194")
    assert [a["name"] for a in areas] == ["Concord", "San Francisco"]
    assert A.nearest_area(37.90, -122.06) == "Concord"  # Walnut Creek
    assert A.nearest_area(37.80, -122.27) == "San Francisco"  # Oakland is closer to SF than Concord


def test_parse_menu():
    text = 'Here you go: {"items": [{"name": "Combo #2", "price": "$12.99", "kind": "meal"},' \
           '{"name": "Fries", "price": null}, {"name": "", "price": 3}, {"name": "Taco", "price": 3.5, "kind": "weird"}],' \
           '"uncertain": ["combo price"]}'
    out = A.parse_menu(text)
    assert [(i["name"], i["price"], i["kind"]) for i in out["items"]] == \
        [("Taco", 3.5, "item"), ("Combo #2", 12.99, "meal"), ("Fries", None, "item")]
    assert out["uncertain"] == ["combo price"]


def test_menu_read_without_key(c):
    assert c.post("/admin/api/menu/read", json={"photos": []}).status_code == 503


def test_menu_read_with_key(c, monkeypatch):
    monkeypatch.setattr(A, "ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(A, "call_claude", lambda imgs, prompt: '{"items": [{"name": "Pho", "price": 14}]}')
    tok = c.post("/admin/api/uploads", data={"file": (jpeg(), "m.jpg")}, content_type="multipart/form-data").get_json()["uploads"][0]
    assert c.post("/admin/api/menu/read", json={"photos": ["../app.py"]}).status_code == 400
    out = c.post("/admin/api/menu/read", json={"photos": [tok]}).get_json()
    assert out["items"][0]["name"] == "Pho"


def test_nearby_merges_osm_and_known(c, monkeypatch):
    add_place(c, name="Already Here", address=None, lat=37.94805, lng=-122.06005, items=[])

    def fake(url, timeout=8, data=None):
        if "overpass" in url:
            return {"elements": [{"lat": 37.9481, "lon": -122.0601, "tags": {
                "name": "Los Gallos", "amenity": "restaurant", "cuisine": "mexican;burrito",
                "addr:housenumber": "1950", "addr:street": "Grant Street", "addr:city": "Concord"}},
                {"lat": 37.948, "lon": -122.06, "tags": {"amenity": "cafe"}}]}
        return {"address": {"house_number": "1950", "road": "Grant Street", "city": "Concord", "suburb": "Downtown"}}
    monkeypatch.setattr(A, "http_json", fake)
    d = c.get("/admin/api/nearby?lat=37.948&lng=-122.06").get_json()
    assert d["area"] == "Concord" and d["address"] == "1950 Grant Street, Concord"
    assert [o["name"] for o in d["osm"]] == ["Los Gallos"] and d["osm"][0]["cuisine"] == "Mexican"
    assert "Already Here" in [k["name"] for k in d["known"]] and all(k["m"] < 150 for k in d["known"])


def test_exports_and_health(c):
    add_place(c, name="Exported")
    assert c.get("/healthz").get_json()["ok"]
    csv_text = c.get("/admin/api/export.csv").get_data(as_text=True)
    assert "Super burrito" in csv_text and csv_text.startswith("﻿")
    data = c.get("/admin/api/export.json").get_json()
    assert {"places", "items", "photos"} <= set(data)
    f = c.get("/api/facets").get_json()
    assert [a["name"] for a in f["areas"]][:2] == ["Concord", "San Francisco"]


def test_osm_search_filters_food_and_bounds_to_area(c, monkeypatch):
    add_place(c, name="Known Pho", address=None, lat=37.9701, lng=-122.0402, items=[])
    seen = {}

    def fake(url, timeout=8, data=None):
        seen["url"] = url
        return [
            {"category": "amenity", "type": "restaurant", "name": "Pho Concord", "lat": "37.97012", "lon": "-122.04018",
             "address": {"house_number": "1800", "road": "Willow Pass Road", "city": "Concord", "suburb": "Downtown"},
             "extratags": {"cuisine": "vietnamese;noodle", "phone": "+1 925-555-0100", "opening_hours": "Mo-Sa 10:00-21:00",
                           "website": "https://pho.example.com"}},
            {"category": "highway", "type": "bus_stop", "name": "Pho Stop", "lat": "37.97", "lon": "-122.04"},
            {"category": "amenity", "type": "fast_food", "name": "Taco Truck", "lat": "37.98", "lon": "-122.03"}]
    monkeypatch.setattr(A, "http_json", fake)
    d = c.get("/admin/api/osm/search?q=pho&area=Concord").get_json()
    assert "bounded=1" in seen["url"] and "extratags=1" in seen["url"] and "viewbox=-122.1811" in seen["url"]
    assert [r["name"] for r in d["results"]] == ["Pho Concord", "Taco Truck"]
    pho = d["results"][0]
    assert pho["address"] == "1800 Willow Pass Road, Concord" and pho["cuisine"] == "Vietnamese"
    assert pho["phone"] == "+1 925-555-0100" and pho["hours"] == "Mo-Sa 10:00-21:00" and pho["area"] == "Concord"
    assert pho["known"] is not None and d["results"][1]["known"] is None
    assert c.get("/admin/api/osm/search?q=").status_code == 400
    assert c.get("/api/osm/search?q=pho").status_code == 404  # editors only
    monkeypatch.setattr(A, "http_json", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert c.get("/admin/api/osm/search?q=pho").status_code == 502


def test_area_viewbox():
    lng1, lat1, lng2, lat2 = A.area_viewbox("San Francisco")
    assert lng1 < -122.4194 < lng2 and lat2 < 37.7749 < lat1
    everywhere = A.area_viewbox("")
    assert everywhere[0] < -122.4194 and everywhere[2] > -122.0311  # spans Concord and SF
