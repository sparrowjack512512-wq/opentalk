
import logging
import os
import signal
import sys
import threading
import time
import traceback

from flask import Flask, jsonify
from seleniumbase import Driver

# =========================================================
# CONFIGURATION
# =========================================================

TEST_URL = "https://example.com/"
CYCLE_INTERVAL_SECONDS = 10
RESTART_AFTER_CYCLES = 30
PAGE_LOAD_TIMEOUT_SECONDS = 20
ERROR_RETRY_SECONDS = 5
HEARTBEAT_INTERVAL_SECONDS = 15

FLASK_PORT = int(os.environ.get("PORT", "10000"))

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

log = logging.getLogger("render-browser-worker")

# =========================================================
# SHARED STATE
# =========================================================

app = Flask(__name__)
stop_event = threading.Event()
state_lock = threading.Lock()

state = {
    "running": False,
    "browser_ready": False,
    "cycle": 0,
    "browser_restarts": 0,
    "last_error": None,
    "last_success": None,
    "last_activity": None,
    "worker_phase": "starting",
}


def update_state(**kwargs):
    with state_lock:
        state.update(kwargs)


def get_state():
    with state_lock:
        return dict(state)


def log_activity(message, phase=None):
    timestamp = time.strftime(
        "%Y-%m-%d %H:%M:%S UTC",
        time.gmtime(),
    )

    changes = {"last_activity": timestamp}
    if phase is not None:
        changes["worker_phase"] = phase

    update_state(**changes)
    log.info("%s", message)


# =========================================================
# SHUTDOWN
# =========================================================

def handle_shutdown(signum, frame):
    log.warning("SHUTDOWN: Signal received: %s", signum)
    stop_event.set()


# =========================================================
# BROWSER
# =========================================================

def create_browser():
    log_activity("BROWSER: Starting Chrome", "starting_browser")

    browser = Driver(
        browser="chrome",
        headless=True,
        binary_location="/usr/bin/google-chrome",
    )

    browser.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
    browser.set_script_timeout(PAGE_LOAD_TIMEOUT_SECONDS)

    update_state(browser_ready=True)
    log_activity("BROWSER: Chrome started successfully", "ready")

    return browser


def close_browser(browser):
    if browser is None:
        return

    try:
        log_activity("BROWSER: Closing Chrome", "closing_browser")
        browser.quit()
        log_activity("BROWSER: Chrome closed", "browser_closed")
    except Exception:
        log.exception("BROWSER: Error while closing Chrome")


# =========================================================
# ONE TEST CYCLE
# =========================================================

def run_test_cycle(browser, cycle_number):
    log_activity(
        f"CYCLE {cycle_number}: Beginning navigation to {TEST_URL}",
        "navigating",
    )

    browser.get(TEST_URL)

    log_activity(
        f"CYCLE {cycle_number}: Navigation completed",
        "reading_page",
    )

    title = browser.title
    url = browser.current_url

    if not title:
        raise RuntimeError("Test page returned an empty title")

    timestamp = time.strftime(
        "%Y-%m-%d %H:%M:%S UTC",
        time.gmtime(),
    )

    update_state(
        cycle=cycle_number,
        last_success=timestamp,
        last_error=None,
    )

    log_activity(
        f"CYCLE {cycle_number} PASSED | "
        f"title={title!r} | url={url}",
        "cycle_passed",
    )


# =========================================================
# INDEPENDENT HEARTBEAT
# =========================================================

def heartbeat_monitor():
    log.info("WATCHDOG: Heartbeat monitor started")

    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        current = get_state()

        log.info(
            "WATCHDOG: Process alive | "
            "worker_running=%s | browser_ready=%s | "
            "last_completed_cycle=%s | phase=%s | "
            "last_activity=%s | browser_restarts=%s | "
            "last_error=%s",
            current["running"],
            current["browser_ready"],
            current["cycle"],
            current["worker_phase"],
            current["last_activity"],
            current["browser_restarts"],
            current["last_error"],
        )


# =========================================================
# BACKGROUND WORKER
# =========================================================

def worker():
    browser = None
    cycles_since_restart = 0

    update_state(
        running=True,
        browser_ready=False,
        last_error=None,
        worker_phase="starting",
    )

    log_activity("WORKER: Background worker started", "starting")

    try:
        while not stop_event.is_set():
            try:
                if browser is None:
                    browser = create_browser()

                cycle_number = cycles_since_restart + 1
                run_test_cycle(browser, cycle_number)
                cycles_since_restart += 1

                # Periodically test whether Chrome can restart cleanly.
                if cycles_since_restart >= RESTART_AFTER_CYCLES:
                    log_activity(
                        f"BROWSER: Restarting after "
                        f"{cycles_since_restart} successful cycles",
                        "restarting_browser",
                    )

                    update_state(browser_ready=False)
                    close_browser(browser)
                    browser = None
                    cycles_since_restart = 0

                    if stop_event.is_set():
                        break

                    browser = create_browser()

                    with state_lock:
                        state["browser_restarts"] += 1

                    log_activity(
                        "BROWSER: Restart completed",
                        "ready",
                    )

                log_activity(
                    f"WAIT: Beginning "
                    f"{CYCLE_INTERVAL_SECONDS}-second delay",
                    "waiting",
                )

                interrupted = stop_event.wait(
                    CYCLE_INTERVAL_SECONDS
                )

                if interrupted:
                    log_activity(
                        "WAIT: Interrupted by shutdown",
                        "stopping",
                    )
                    break

                log_activity(
                    "WAIT: Delay finished; starting next cycle",
                    "starting_next_cycle",
                )

            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"

                log.error("WORKER: Cycle failed: %s", error_text)
                log.debug("%s", traceback.format_exc())

                update_state(
                    browser_ready=False,
                    last_error=error_text,
                    worker_phase="error_recovery",
                )

                close_browser(browser)
                browser = None
                cycles_since_restart = 0

                if stop_event.wait(ERROR_RETRY_SECONDS):
                    break

    finally:
        update_state(
            browser_ready=False,
            worker_phase="stopping",
        )

        close_browser(browser)

        update_state(
            running=False,
            worker_phase="stopped",
        )

        log_activity("WORKER: Background worker stopped", "stopped")


# =========================================================
# HEALTH ENDPOINTS
# =========================================================

@app.route("/")
def health():
    current = get_state()
    code = 200 if current["running"] else 503

    return jsonify({
        "service": "Render Browser Test",
        **current,
    }), code


@app.route("/health")
def health_check():
    current = get_state()

    healthy = (
        current["running"]
        and current["browser_ready"]
        and current["last_error"] is None
    )

    return jsonify({
        "healthy": healthy,
        **current,
    }), 200 if healthy else 503


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    log.info("CONTAINER APPLICATION STARTING")

    worker_thread = threading.Thread(
        target=worker,
        name="browser-worker",
        daemon=True,
    )

    heartbeat_thread = threading.Thread(
        target=heartbeat_monitor,
        name="heartbeat-monitor",
        daemon=True,
    )

    worker_thread.start()
    heartbeat_thread.start()

    log.info("Starting Flask health server on port %s", FLASK_PORT)

    try:
        app.run(
            host="0.0.0.0",
            port=FLASK_PORT,
            use_reloader=False,
            threaded=True,
        )
    finally:
        log.info("APPLICATION: Shutdown started")
        stop_event.set()

        worker_thread.join(timeout=10)
        heartbeat_thread.join(timeout=3)

        log.info("APPLICATION: Shutdown complete")
