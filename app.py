import os
import random
import time
import threading
import logging
from datetime import datetime

from flask import Flask
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# ============================================================
# CONFIG
# ============================================================
URL = "https://opentalk.club/text/"

SEL_GIRL   = "div.ot-onb-actions button.ot-onb-action:first-child"
SEL_START  = "div.ot-onb-actions button.ot-onb-action.is-primary"
SEL_INPUT  = "input#mInput"
SEL_NEXT   = "button#mSend"
SEL_MSGS   = "#mMsgs"

MESSAGE_SETS = [
    ["Hii", "F", "talk to me on Chitmet gg", "Lisaaa9845"],
    ["hey", "F", "chat me on Chitmet gg", "Lisaaa982"],
    ["hi", "F", "let's talk on Chitmet gg", "Lisaaa987"],
    ["hello", "F", "msg me on Chitmet gg", "Lisaaa986"],
]

MATCH_TIMEOUT      = 90
MAX_CYCLES         = 99999999999999999999999999999999          # run until stopped/restarted by platform
POST_START_WAIT    = 3.0
TYPE_DELAY_MIN     = 0.02
TYPE_DELAY_MAX     = 0.08
ENTER_DELAY_MIN    = 0.3
ENTER_DELAY_MAX    = 0.8
MSG_GAP            = 3.5
POST_SEND_WAIT_MIN = 10.0
POST_SEND_WAIT_MAX = 13.0
POST_LAST_MSG_SETTLE_MIN = 0.5
POST_LAST_MSG_SETTLE_MAX = 1.0
SKIP_CLICK_GAP     = 0.6
CYCLE_PAUSE_MIN    = 3.0
CYCLE_PAUSE_MAX    = 9.0
TIMEOUT_STREAK_LIMIT = 3
LONG_BREAK_SECONDS   = 60.0

# ============================================================
# Logging (stdout only — Render captures it as logs)
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("opentalk")

# ============================================================
# Runtime state
# ============================================================
driver = None
stop_flag = False
bot_thread = None
running = False

# ============================================================
# Selenium
# ============================================================
def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    chrome_install = ChromeDriverManager().install()
    folder = os.path.dirname(chrome_install)
    chromedriver_path = os.path.join(folder, "chromedriver")
    # On Linux the binary has no .exe — fall back to whatever manager returned
    if not os.path.exists(chromedriver_path):
        chromedriver_path = chrome_install
    service = Service(chromedriver_path)

    d = webdriver.Chrome(service=service, options=options)
    d.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"}
    )
    return d


def human_type(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(TYPE_DELAY_MIN, TYPE_DELAY_MAX))


def wait_for(d, selector, timeout, condition="presence"):
    w = WebDriverWait(d, timeout)
    if condition == "visible":
        return w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
    if condition == "clickable":
        return w.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
    return w.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))


def try_click(d, selector, label, timeout=2):
    try:
        el = wait_for(d, selector, timeout=timeout, condition="clickable")
        el.click()
        log.info(f"clicked {label} (CSS)")
        return True
    except Exception:
        return False


def js_click_by_text(d, tag, text, label, timeout=8):
    xpath = f"//{tag}[contains(normalize-space(.), \"{text}\")]"
    try:
        btn = WebDriverWait(d, timeout).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
        d.execute_script(
            "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", btn
        )
        log.info(f"clicked {label} (JS fallback)")
        return True
    except Exception as e:
        log.info(f"JS fallback failed for {label}: {type(e).__name__}")
        return False


def handle_entry(d):
    if not try_click(d, SEL_GIRL, "'I'm a girl'", timeout=2):
        js_click_by_text(d, "button", "I'm a girl", "'I'm a girl'", timeout=8)
    if not try_click(d, SEL_START, "Start chatting", timeout=2):
        js_click_by_text(d, "button", "Start chatting", "Start chatting", timeout=8)


def is_matched(d):
    try:
        el = d.find_element(By.CSS_SELECTOR, SEL_MSGS)
        if el.get_attribute("data-ot-onb-active") != "1":
            return False
        inp = d.find_element(By.CSS_SELECTOR, SEL_INPUT)
        if not inp.is_displayed() or not inp.is_enabled():
            return False
        if inp.get_attribute("disabled") or inp.get_attribute("readonly"):
            return False
        return True
    except (NoSuchElementException, WebDriverException):
        return False


def skip_chat(d):
    btn = wait_for(d, SEL_NEXT, timeout=10, condition="clickable")
    btn.click()
    log.info("skip click 1 (armed)")
    time.sleep(SKIP_CLICK_GAP)
    btn = wait_for(d, SEL_NEXT, timeout=5, condition="clickable")
    btn.click()
    log.info("skip click 2 (confirmed)")
    time.sleep(1.0)


def send_message(d, input_box, text):
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if input_box.is_displayed() and input_box.is_enabled():
                if not input_box.get_attribute("disabled") and not input_box.get_attribute("readonly"):
                    break
        except Exception:
            pass
        time.sleep(0.2)
    else:
        raise WebDriverException("input never became interactable")

    last_err = None
    for attempt in range(3):
        try:
            input_box.clear()
            human_type(input_box, text)
            time.sleep(random.uniform(ENTER_DELAY_MIN, ENTER_DELAY_MAX))
            input_box.send_keys(Keys.ENTER)
            time.sleep(0.25)
            remaining = input_box.get_attribute("value")
            if remaining and remaining.strip():
                log.info("  Enter didn't clear input — clicking mSend")
                d.find_element(By.CSS_SELECTOR, SEL_NEXT).click()
                time.sleep(0.25)
            return
        except WebDriverException as e:
            last_err = e
            log.info(f"  send attempt {attempt+1} failed: {type(e).__name__} — retrying")
            time.sleep(0.4)
    raise last_err if last_err else WebDriverException("send failed")


def run_one_cycle(d, messages):
    log.info(f"waiting {POST_START_WAIT}s for auto-connect...")
    time.sleep(POST_START_WAIT)

    if not is_matched(d):
        log.info("polling for match...")
        deadline = time.time() + MATCH_TIMEOUT
        while time.time() < deadline:
            if stop_flag:
                raise KeyboardInterrupt
            if is_matched(d):
                break
            time.sleep(0.4)
        else:
            raise TimeoutException("match timeout")
    log.info("matched")

    input_box = d.find_element(By.CSS_SELECTOR, SEL_INPUT)
    log.info(f"message set: {messages}")

    for i, msg in enumerate(messages):
        if stop_flag:
            raise KeyboardInterrupt
        send_message(d, input_box, msg)
        log.info(f"sent message {i+1}: {msg}")
        if i < len(messages) - 1:
            time.sleep(MSG_GAP)

    settle = random.uniform(POST_LAST_MSG_SETTLE_MIN, POST_LAST_MSG_SETTLE_MAX)
    log.info(f"settle pause: {settle:.2f}s")
    time.sleep(settle)

    post_wait = random.uniform(POST_SEND_WAIT_MIN, POST_SEND_WAIT_MAX)
    log.info(f"waiting {post_wait:.2f}s before skip ...")
    waited = 0.0
    while waited < post_wait:
        if stop_flag:
            raise KeyboardInterrupt
        time.sleep(0.2)
        waited += 0.2

    skip_chat(d)
    log.info("left chat")


# ============================================================
# Bot loop
# ============================================================
def bot_loop():
    global driver, stop_flag, running
    stop_flag = False
    running = True
    try:
        log.info("Starting headless browser...")
        driver = create_driver()
        driver.get(URL)
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            pass

        handle_entry(driver)

        consecutive_timeouts = 0
        for cycle in range(1, MAX_CYCLES + 1):
            if stop_flag:
                break
            log.info(f"\n--- cycle {cycle} ---")
            messages = random.choice(MESSAGE_SETS)
            try:
                if not is_matched(driver):
                    if not try_click(driver, SEL_START, "Start chatting", timeout=2):
                        js_click_by_text(driver, "button", "Start chatting", "Start chatting", timeout=5)
                run_one_cycle(driver, messages)
                consecutive_timeouts = 0
            except KeyboardInterrupt:
                log.info("stop requested.")
                break
            except TimeoutException:
                consecutive_timeouts += 1
                log.warning(f"match timeout (streak {consecutive_timeouts}) — reloading")
                try:
                    driver.refresh(); time.sleep(2); handle_entry(driver)
                except WebDriverException:
                    try: driver.quit()
                    except Exception: pass
                    driver = create_driver()
                    driver.get(URL); time.sleep(2); handle_entry(driver)
                if consecutive_timeouts >= TIMEOUT_STREAK_LIMIT:
                    log.warning(f"pausing {LONG_BREAK_SECONDS}s")
                    time.sleep(LONG_BREAK_SECONDS)
                    consecutive_timeouts = 0
            except (NoSuchElementException, WebDriverException) as e:
                log.error(f"cycle error: {e} — retrying once")
                try:
                    time.sleep(1.5)
                    run_one_cycle(driver, messages)
                except Exception as e2:
                    log.error(f"retry failed: {e2} — reloading")
                    try:
                        driver.refresh(); time.sleep(2); handle_entry(driver)
                    except WebDriverException:
                        try: driver.quit()
                        except Exception: pass
                        driver = create_driver()
                        driver.get(URL); time.sleep(2); handle_entry(driver)
            except Exception as e:
                log.error(f"unknown error: {e} — skipping")
                time.sleep(2)

            if cycle < MAX_CYCLES:
                pause = random.uniform(CYCLE_PAUSE_MIN, CYCLE_PAUSE_MAX)
                log.info(f"cycle pause: {pause:.1f}s")
                waited = 0.0
                while waited < pause:
                    if stop_flag:
                        break
                    time.sleep(0.2)
                    waited += 0.2
                if stop_flag:
                    break
        log.info("bot loop finished.")
    except Exception as e:
        log.error(f"fatal: {e}")
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass
        driver = None
        running = False


# ============================================================
# Flask web service (keeps Render's Web Service alive)
# ============================================================
app = Flask(__name__)


@app.route("/")
def health():
    return f"OpenTalk bot: running={running}", 200


@app.route("/start")
def start_endpoint():
    global bot_thread
    if running:
        return "already running", 200
    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()
    return "started", 200


@app.route("/stop")
def stop_endpoint():
    global stop_flag
    stop_flag = True
    return "stop requested", 200


if __name__ == "__main__":
    # Auto-start bot when the service boots on Render
    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)