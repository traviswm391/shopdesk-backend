"""
Email service for ShopDesk AI using Resend (https://resend.com).
Set RESEND_API_KEY in Railway environment variables to enable.
Free tier: 3,000 emails/month â sufficient for weekly digests across all shops.
"""
import logging
import requests
from app.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, html: str) -> bool:
    """Send a transactional email via Resend. Returns True on success."""
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not configured â skipping email to %s", to)
        return False
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.from_email,
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            logger.info("Email sent â %s | %s", to, subject)
            return True
        logger.error("Resend error %s: %s", resp.status_code, resp.text)
        return False
    except Exception as exc:
        logger.error("Email send exception: %s", exc)
        return False


def build_weekly_digest_html(shop_name: str, location: str, stats: dict) -> str:
    """Build an HTML email body for the weekly digest."""
    total = stats.get("total_calls", 0)
    booked = stats.get("appointments_booked", 0)
    rate = stats.get("conversion_rate", 0)
    avg_dur = stats.get("avg_duration_seconds", 0) or 0
    mins, secs = int(avg_dur // 60), int(avg_dur % 60)
    dur = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
    loc_label = f" &middot; {location}" if location else ""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f4f6;margin:0;padding:24px}}
  .card{{max-width:560px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.08)}}
  .top{{background:#f97316;padding:28px 32py}}
  .top h1{{color:#fff;margin:0;font-size:22px;font-weight:700}}
  .top p{{color:rgba(255,255,255,.85);margin:4px 0 0;font-size:13px}}
  .body{{padding:28px 32px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:20px 0}}
  .stat{{background:#f9fafb;border-radius:10px;padding:16px;text-align:center}}
  .stat b{{display:block;font-size:30px;font-weight:800;color:#111;line-height:1}}
  .stat span{{font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-top:4px;display:block}}
  .btn{{display:block;background:#f97316;color:#fff;text-decoration:none;text-align:center;padding:14px;border-radius:8px;font-weight:600;font-size:15px;margin-top:24px}}
  .foot{{padding:16px 32px;font-size:12px;color:#9ca3af;border-top:1px solid #f3f4f6}}
</style>
</head>
<body>
<div class="card">
  <div class="top">
    <h1>Weekly Summary</h1>
    <p>{shop_name}{loc_label} &middot; ShopDesk AI Receptionist</p>
  </div>
  <div class="body">
    <p style="color:#374151;font-size:15px;margin:0 0 4px">Here's how your AI receptionist performed this week:</p>
    <div class="grid">
      <div class="stat"><b>{total}</b><span>Total Calls</span></div>
      <div class="stat"><b>{booked}</b><span>Appointments Booked</span></div>
      <div class="stat"><b>{rate}%</b><span>Booking Rate</span></div>
      <div class="stat"><b>{dur}</b><span>Avg Call Length</span></div>
    </div>
    <a class="btn" href="{settings.app_url}/dashboard">View Full Dashboard &rarr;</a>
  </div>
  <div class="foot">You're receiving this because you use ShopDesk AI. Log in to manage notification preferences.</div>
</div>
</body>
</html>"""
