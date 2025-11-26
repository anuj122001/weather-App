# tools.py (Twilio + APScheduler, module-level callables; keeps same function names)
import os
import logging
from datetime import datetime, timedelta
from typing import Optional

from twilio.rest import Client
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Global registry for the Tools instance so module-level functions can find it.
TOOLS_INSTANCE: Optional["Tools"] = None

def run_scheduled(to_number: str, message: str):
    """
    Module-level runner for sending scheduled WhatsApp messages.
    Must be module-level so APScheduler can serialize the job.
    """
    global TOOLS_INSTANCE
    if TOOLS_INSTANCE is None:
        logger.error("No Tools instance registered; cannot run scheduled job for %s", to_number)
        return "❌ No Tools instance available to send message."
    logger.info("Module-level runner calling Tools.send_whatsapp for %s", to_number)
    return TOOLS_INSTANCE.send_whatsapp(to_number, message)

def heartbeat_runner():
    """
    Module-level heartbeat that delegates to Tools._heartbeat for logging.
    Using a module-level function makes the job picklable.
    """
    global TOOLS_INSTANCE
    if TOOLS_INSTANCE is None:
        logger.warning("Heartbeat runner: no Tools instance registered.")
        return
    TOOLS_INSTANCE._heartbeat()

class Tools:
    """
    Tools helper using Twilio for WhatsApp + APScheduler for scheduling.
    Keep function names the same so other code can import/use without changes.
    Environment variables required:
      - TWILIO_ACCOUNT_SID
      - TWILIO_AUTH_TOKEN
      - TWILIO_WHATSAPP_FROM    (format: 'whatsapp:+1415xxxxxxx')
    """
    def __init__(self, sqlite_job_db: str = "sqlite:///jobs.sqlite"):
        global TOOLS_INSTANCE

        # Twilio credentials
        self.tw_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.tw_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_whatsapp = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g. "whatsapp:+1415..."
        self.client = Client(self.tw_sid, self.tw_token) if self.tw_sid and self.tw_token else None

        # APScheduler persistent jobstore (SQLite) + executors
        jobstores = {'default': SQLAlchemyJobStore(url=sqlite_job_db)}
        executors = {'default': ThreadPoolExecutor(10)}
        job_defaults = {'coalesce': False, 'max_instances': 3, 'misfire_grace_time': 86400}  # 24h grace

        self.scheduler = BackgroundScheduler(jobstores=jobstores,
                                             executors=executors,
                                             job_defaults=job_defaults,
                                             timezone="UTC")
        self.scheduler.start()
        logger.info("Scheduler started (UTC). Jobstore: %s", sqlite_job_db)

        # Register global instance so module-level runners can call into it
        TOOLS_INSTANCE = self
        logger.info("Tools instance registered as global TOOLS_INSTANCE")

        # schedule the module-level heartbeat (picklable)
        self.scheduler.add_job(heartbeat_runner, 'interval', seconds=30, id="heartbeat_job", replace_existing=True)
        logger.info("Heartbeat job scheduled (every 30s) using module-level runner.")

    def _heartbeat(self):
        # Instance-level heartbeat logic (not scheduled directly)
        logger.info("💓 Heartbeat: scheduler is alive at %s UTC", datetime.utcnow().isoformat())

    # def send_whatsapp(self, to_number: str, message: str) -> str:
    #     """
    #     Send a WhatsApp message immediately using Twilio.
    #     to_number must be E.164 format with 'whatsapp:' prefix, e.g. 'whatsapp:+9198XXXXXXXX'.
    #     """
    #     if not self.client or not self.from_whatsapp:
    #         logger.error("Twilio credentials missing (TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_WHATSAPP_FROM).")
    #         return "❌ Twilio credentials not configured (TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_WHATSAPP_FROM)."

    #     try:
    #         msg = self.client.messages.create(
    #             body=message,
    #             from_=self.from_whatsapp,   # e.g. "whatsapp:+1415..."
    #             to=to_number                # e.g. "whatsapp:+91..."
    #         )
    #         logger.info("Twilio sent message to %s; sid=%s", to_number, getattr(msg, "sid", "n/a"))
    #         return f"📩 WhatsApp (Twilio) sent: sid={getattr(msg, 'sid', '')}"
    #     except Exception as e:
    #         logger.exception("Twilio send error")
    #         return f"❌ Twilio error: {e}"

    def send_whatsapp(self, to_number: str, message: str) -> str:
        """
        Send via Twilio WhatsApp. Ensures both 'from_' and 'to' use the 'whatsapp:' prefix.
        to_number may be passed as '+9198...' or 'whatsapp:+9198...'; this normalizes to 'whatsapp:+...'.
        """
        # ensure Twilio client + from number exist
        if not self.client or not self.from_whatsapp:
            logger.error("Twilio credentials missing (TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_WHATSAPP_FROM).")
            return "❌ Twilio credentials not configured (TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_WHATSAPP_FROM)."

        # normalize from_ and to
        from_wh = self.from_whatsapp.strip()
        if not from_wh.startswith("whatsapp:"):
            from_wh = "whatsapp:" + from_wh.lstrip("+")

        to_wh = to_number.strip()
        if not to_wh.startswith("whatsapp:"):
            # allow either '+91...' or '91...'
            if to_wh.startswith("+"):
                to_wh = "whatsapp:" + to_wh
            else:
                to_wh = "whatsapp:+" + to_wh  # assume number without + should get prefixed

        logger.info("Sending via Twilio - from: %s  to: %s", from_wh, to_wh)
        try:
            msg = self.client.messages.create(
                body=message,
                from_=from_wh,
                to=to_wh
            )
            # log details so you can check Twilio console if something goes wrong
            logger.info("Twilio created message sid=%s, status=%s, to=%s", getattr(msg, "sid", "n/a"), getattr(msg, "status", "n/a"), getattr(msg, "to", "n/a"))
            return f"📩 WhatsApp (Twilio) sent: sid={getattr(msg, 'sid', '')}, to={getattr(msg, 'to', '')}"
        except Exception as e:
            logger.exception("Twilio send error")
            return f"❌ Twilio error: {e}"


    def schedule_whatsapp(self, to_number: str, message: str, delay_hours: float) -> str:
        """
        Schedule a WhatsApp message after delay_hours (float). The Python process must keep running.
        Signature unchanged: schedule_whatsapp(to_number, message, delay_hours)
        """
        try:
            run_time = datetime.utcnow() + timedelta(hours=float(delay_hours))
        except Exception:
            return "❌ Invalid delay_hours value. Must be a number."

        # Schedule module-level run_scheduled (picklable) with simple args
        job = self.scheduler.add_job(
            run_scheduled,
            "date",
            run_date=run_time,
            args=[to_number, message]
        )

        logger.info("Scheduled WhatsApp job_id=%s for %s UTC (to=%s)", job.id, run_time.isoformat(), to_number)
        return f"⏳ Scheduled WhatsApp message (job_id={job.id}) for {run_time} UTC"

    # Admin helpers
    def list_jobs(self):
        jobs = self.scheduler.get_jobs()
        return [{"id": j.id, "next_run": str(j.next_run_time), "args": j.args} for j in jobs]

    def cancel_job(self, job_id: str) -> str:
        try:
            self.scheduler.remove_job(job_id)
            return f"✅ Removed job {job_id}"
        except Exception as e:
            return f"❌ Error removing job {job_id}: {e}"
