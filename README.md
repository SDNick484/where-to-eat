# Where to Eat

A list of affordable lunch spots, mostly in Concord and San Francisco. It tracks the cheap things worth ordering at each one and what they cost, with photos from your phone and a map. Flask + SQLite, one small service on CT 210 next to Cookbooks, Dinner Log, the wish list and Roasted, styled with my Graphite Red design system.

- **Public:** `https://lunch.nickandrade.com/` shows the places, a *Deals* list of every dish cheapest first, and the map. Private notes and who added what are left out.
- **Editing:** `https://lunch.nickandrade.com/admin` sits behind Cloudflare Access. A few people can sign in there to add places, dishes and photos.

## How it's organized
| | What it is | Example |
|---|---|---|
| **Place** | a restaurant | Taqueria Los Gallos, Concord · Mexican · $ |
| **Dish** | something worth ordering, with its price | Super burrito $11.50 · *Lunch combo #2* $12.99 (meal deal, Mon–Fri 11–3) |
| **Photo** | the storefront, the menu, or a dish | a photo tagged to "Super burrito" shows next to it and on the Deals list |

- A dish's **type** is *Dish*, *Meal deal* (a combo with sides or a drink) or *Special* (daily or time-limited).
- **★ Go-to dish** marks what to actually order there. Go-to dishes are listed first on the place's card.
- Anything at or under **CHEAP_UNDER** ($15 by default) counts as a deal: its price is set in a red pill, and the place's card gets a red rule.

### Prices go stale
Each price records when it was last checked.
- Entering or changing a price sets that date to today.
- When a price is older than a month, the place page offers **still $X**. One tap confirms the price is unchanged.
- Prices older than six months get a clock mark everywhere, so you know to double-check them.

## Finding lunch
- **Places:** pick an area (Concord, San Francisco, or everywhere) and a price cap (*Under $10 / $15 / $20*). You can also search places and dishes by name, so "pho", "burrito" and "Mission" all work. Sort by cheapest, nearest, top rated, newest or name.
- **Near me:** sorts by distance from your phone's location. On *Deals* it lists dishes within 5 km.
- **Deals:** every dish with a price, cheapest first. Filter it to *Meal deals* or *Specials*.
- **Map:** markers show each place's cheapest dish. **Red** means something under the cap, **black** means the cheapest dish costs more, and **hollow** means no prices yet. After **Near me**, you're the black dot with a ring. Use the area buttons to jump between Concord and SF.
- **Directions** on a place opens Google Maps.

## Adding a place (on your phone, at the restaurant)
1. Tap **＋**, then **I'm here**.
   - Your location sets the map pin and the area, and the street address and neighborhood are looked up.
   - It lists the restaurants OpenStreetMap knows within ~90 m. Tap the right one to fill in its name, cuisine, address, phone, website and hours.
   - If a place already in the list is within ~150 m, it's shown with a link, so the same place isn't added twice.
2. **Take photo** for each shot, or **Choose photos** to pick several from the gallery. These are separate buttons because Android hides the camera when a picker allows several files.
3. Optionally type a couple of cheap dishes and their prices. Then **Save place**.

### From home: look it up on OpenStreetMap
Type the restaurant's name under **Or look it up on OpenStreetMap** and tap **Search**. It searches food places within about 13 km of the area you picked, or around all your areas if none is picked.
- Each match shows which of phone, hours and website OpenStreetMap has, and whether the place is already in your list.
- Tapping a match fills in only the fields that are still empty, plus the map pin. Anything you've typed stays.
- **Edit place** has the same search, to fill in details a place is missing later.

San Francisco is well covered. Concord has gaps, especially phone numbers and hours, so type in what's missing. The data is © OpenStreetMap contributors (ODbL). Credit is shown with the results and on every map.

You can also type the address and tap **Find** to check where the pin lands. Drag the pin if it's off. If you save without a pin, the address is looked up then: OpenStreetMap Nominatim first, then Photon, which tolerates typos. When a lookup service is down, the editor map retries a few unplaced addresses each time it opens. The area is filled in from the pin, using the nearest of `AREAS` within 30 km.

Location and the camera need HTTPS, so use `lunch.nickandrade.com` on the phone rather than the LAN IP.

## Adding dishes and photos
- On a place's page, add a dish with its price, type, details ("with rice, beans and a drink") and when it's offered.
- **Photos → Take photo** adds to the place. Under each photo, pick **which dish** it shows and add a caption. **★** makes a photo the place's main one.
- Photos are turned upright, resized to at most 1600 px, and re-saved as JPEG with a thumbnail. Re-saving drops the phone's EXIF data, including the GPS position in the photo.

### Read a menu photo (optional)
With `ANTHROPIC_API_KEY` set, a place's page offers **Read a menu photo**. You can also choose **Read this menu** under any photo already there.
1. Claude lists each dish with its price, type and hours, and flags anything it was unsure of.
2. Cheap dishes that aren't listed yet come pre-ticked. Fix any name or price, then **Add ticked**.
3. The menu photo itself stays with the place, captioned "Menu".

## Install / upgrade (CT 210)
Build the one-file installer from this repo, then run it in the container:
```sh
sh installer/build.sh                 # -> dist/setup-lunch.sh
pct push 210 dist/setup-lunch.sh /root/setup-lunch.sh
pct exec 210 -- sh /root/setup-lunch.sh
```
The script is safe to run again:
- It replaces the app in `/opt/lunch` but keeps `/var/lib/lunch` (the database and photos) and `/etc/conf.d/lunch`.
- The service is `lunch` (`rc-service lunch restart`) and logs to `/var/log/lunch.log`.
- `sh setup-lunch.sh --uninstall` removes the app and service and keeps the data.

On first install it copies `CF_TEAM_DOMAIN`, `ADMIN_EMAILS` and `ANTHROPIC_API_KEY` from `/etc/conf.d/cookbooks` or `/etc/conf.d/roasted` when they're set there.

Port **8769**. The others are Dinner Log 8765, wish list 8766, Cookbooks 8767 and Roasted 8768. To use another port, run `LUNCH_PORT=… sh setup-lunch.sh` the first time.

## Cloudflare (same setup as Cookbooks and Roasted)
1. **Tunnel → Public hostname**: `lunch.nickandrade.com` → `http://<CT 210 IP>:8769`, on the same tunnel as the other apps.
2. **Access → Applications → Add → Self-hosted**:
   - Domain `lunch.nickandrade.com`, **path `admin`**. Leave the root unprotected so the list stays public.
   - Policy: Allow → Emails → everyone who should be able to add places, e.g. with One-time PIN.
   - Copy the **AUD tag**.
3. In `/etc/conf.d/lunch`:
   - Set `CF_AUD`, and `CF_TEAM_DOMAIN` if it wasn't copied.
   - Set `ADMIN_EMAILS` to the same people, comma separated. The app checks it as well as the Access policy.
   - Then run `rc-service lunch restart`.

The app also verifies the Access JWT itself, so an unsigned request that reaches it through the tunnel can't edit. Each place, dish and photo records the email of whoever added it, and editors can see it.

Requests that don't come through Cloudflare, i.e. directly on the LAN, can edit while `LAN_EDIT=1`.

To keep the whole thing private, set `PUBLIC_VIEW=0`. `/` then redirects to `/admin`, and photos and the public API need a sign-in.

## Settings (`/etc/conf.d/lunch`)
| Setting | Default | What it does |
|---|---|---|
| `AREAS` | `Concord\|37.9780\|-122.0311;San Francisco\|37.7749\|-122.4194` | Area chips, map buttons, and the area a new place gets from its pin |
| `CHEAP_UNDER` | `15` | Dollar cap for "cheap" (deal prices) |
| `PUBLIC_VIEW` | `1` | `0` puts everything behind `/admin` |
| `LAN_EDIT` | `1` | Direct LAN requests may edit |
| `ADMIN_EMAILS` | | Who may edit; empty = anyone the Access policy lets in |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Menu reading |

## On the phone
Open `https://lunch.nickandrade.com/admin` in Chrome and choose **Install app**. Like Dinner Log, it has a small service worker so Android offers the install. The manifest is requested with credentials, so installing works behind Access. It always loads fresh data and shows the last copy when you're offline.

## Backups and alerts
- `/etc/periodic/daily/lunch-backup` writes a consistent SQLite snapshot to `/var/backups/ct210/<date>/lunch-lunch.db.gz`, next to the other apps' snapshots. It uses the same `KEEP_DAYS`, `BACKUP_TARGET` and log as `ct210-backup` (`/etc/conf.d/ct210-ops`).
- With `BACKUP_TARGET` set, photos are copied to `<target>/files/lunch/photos/`.
- The installer adds Lunch to `HEALTH_CHECKS` in `/etc/conf.d/ct210-ops`. That covers both a fresh list and the one Roasted's installer wrote, and the original is kept as `.bak` if the edit doesn't take. The 15-minute health check then alerts Home Assistant if the app goes down.
- The service runs under `supervise-daemon`, so a crash restarts it.

Restore by hand:
```sh
rc-service lunch stop
gunzip -c /var/backups/ct210/<date>/lunch-lunch.db.gz > /var/lib/lunch/lunch.db
chown lunch /var/lib/lunch/lunch.db
rc-service lunch start
```
**More → Download** gives a CSV (one row per dish) or everything as JSON.

## Development
```sh
pip install flask pillow pyjwt cryptography pytest
python3 app.py                      # http://localhost:8769/admin, data in ./data
python3 -m pytest -q tests
```

## Look and feel
Styled with my **Graphite Red** design system:
- Black, white and graphite greys on square corners, with Archivo type, regular-weight headlines, 1.5px line icons and hairline dividers instead of shadows. The dark theme uses the blue-black canvas.
- Progressive Red is the accent. It marks active states (the selected tab, the mark by the name, the rule above each section) and deals (prices under the cap, and a red rule on cards that have them). Small text on red is black (5.0:1); white is used on red only at 20px bold.
- British racing green marks your go-to dishes, in light mode only. On the dark canvas it would be too faint (1.5:1), so it switches to white there.
- Photos do the emotional work. Each card leads with the place's main photo, and the place page opens with it full width. A place without photos gets a tile in the style of the system's cover: a black slab, white speed rules and one red block.
- The street map keeps OpenStreetMap's normal colors. The markers use fixed colors because the map is light in both themes.

The token names in `static/style.css` match the system's `tokens.json`. In dark mode, secondary text stays in `ink` because the system's dark `ink-soft` is too faint for body copy.

## Credits
- [Leaflet](https://leafletjs.com) 1.9.4 (BSD-2-Clause), bundled in `static/leaflet`, with © OpenStreetMap tiles.
- Place lookups use OpenStreetMap Nominatim, Photon and the Overpass API.
- [Archivo](https://github.com/Omnibus-Type/Archivo) (SIL Open Font License 1.1), bundled in `static/fonts` from `@fontsource-variable/archivo` 5.2.8.
