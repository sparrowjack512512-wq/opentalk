import os
import time
import random
import threading
import logging
import traceback
from flask import Flask
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium_turnstile import solve_turnstile

# ============================================================
# CONFIG
# ============================================================
URL = "https://opentalk.club/text/"
SEL_GIRL  = "button.ot-onb-action:not(.is-primary)"
SEL_START = "button.ot-onb-action.is-primary"
SEL_INPUT = "#chatInput"
SEL_SEND  = "#chatSend"
SEL_SKIP  = "#startBtn"

MESSAGE_SETS = [
    ["Hii", "F", "talk to me on Chitmet gg", "Lisaaa9848"],
    ["hey", "F", "chat with me on Chitmet gg", "Lisaaa9848"],
]

MATCH_TIMEOUT = 90
POST_START_WAIT = 3.0
MSG_GAP = 3.5
POST_SEND_WAIT_MIN = 20.0
POST_SEND_WAIT_MAX = 25.0

# ============================================================
# TURNSTILE HOOK (captures sitekey before page JS runs)
# ============================================================
TURNSTILE_HOOK = """
window.__capturedSitekey = null;
window.__tsOriginal = window.turnstile;
Object.defineProperty(window, 'turnstile', {
    configurable: true,
    get() { return window.__tsOriginal; },
    set(v) {
        window.__tsOriginal = v;
        if (v && v.render && !v.__hooked) {
            const orig = v.render.bind(v);
            v.render = function(el, opts) {
                if (opts && opts.sitekey) {
                    window.__capturedSitekey = opts.sitekey;
                    console.log('CAPTURED_SITEKEY:' + opts.sitekey);
                }
                return orig(el, opts);
            };
            v.__hooked = true;
        }
    }
});
"""

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("opentalk")
running = False

def create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.binary_location = "/usr/bin/google-chrome"
    driver = webdriver.Chrome(options=options)
    
    # CRITICAL: inject hook BEFORE any page loads
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": TURNSTILE_HOOK}
    )
    return driver

def human_type(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.02, 0.08))

def wait_for(d, selector, timeout, condition="presence"):
    w = WebDriverWait(d, timeout)
    if condition == "clickable":
        return w.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
    return w.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))

def try_click(d, selector, label, timeout=2):
    try:
        el = wait_for(d, selector, timeout=timeout, condition="clickable")
        el.click()
        log.info(f"Clicked: {label}")
        return True
    except Exception as e:
        log.warning(f"Could not click '{label}': {type(e).__name__}")
        return False

def js_click(d, selector, label, timeout=5):
    try:
        el = WebDriverWait(d, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        d.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", el)
        log.info(f"Clicked (JS): {label}")
        return True
    except Exception as e:
        log.warning(f"Could not JS-click '{label}': {type(e).__name__}")
        return False

def is_matched(d):
    try:
        inp = d.find_element(By.CSS_SELECTOR, SEL_INPUT)
        return inp.is_displayed() and inp.is_enabled()
    except Exception:
        return False

def skip_chat(d):
    try:
        log.info("Skipping chat...")
        btn = wait_for(d, SEL_SKIP, timeout=10, condition="clickable")
        btn.click()
        log.info("Skip click 1")
        time.sleep(0.6)
        try:
            btn2 = wait_for(d, SEL_SKIP, timeout=5, condition="clickable")
            btn2.click()
            log.info("Skip click 2 (confirmed)")
            time.sleep(1.0)
        except Exception:
            pass
        log.info("Left chat.")
    except Exception as e:
        log.error(f"Skip failed: {type(e).__name__}: {e}")

def send_message(d, input_box, text):
    deadline = time.time() + 10
    while time.time() < deadline:
        if input_box.is_displayed() and input_box.is_enabled():
            break
        time.sleep(0.2)
    input_box.clear()
    human_type(input_box, text)
    time.sleep(random.uniform(0.3, 0.8))
    if not try_click(d, SEL_SEND, "send", timeout=3):
        input_box.send_keys(Keys.ENTER)

def run_cycle(d, messages):
    log.info(f"Waiting {POST_START_WAIT}s...")
    time.sleep(POST_START_WAIT)
    if not is_matched(d):
        log.info(f"Polling for match (up to {MATCH_TIMEOUT}s)...")
        deadline = time.time() + MATCH_TIMEOUT
        while time.time() < deadline:
            if is_matched(d):
                break
            time.sleep(0.4)
        else:
            raise TimeoutException("Match timeout")
    log.info("Matched!")
    input_box = d.find_element(By.CSS_SELECTOR, SEL_INPUT)
    log.info(f"Sending: {messages}")
    for i, msg in enumerate(messages):
        send_message(d, input_box, msg)
        log.info(f"Sent {i+1}: {msg}")
        if i < len(messages) - 1:
            time.sleep(MSG_GAP)
    time.sleep(random.uniform(POST_SEND_WAIT_MIN, POST_SEND_WAIT_MAX))
    skip_chat(d)

def bot_loop():
    global running
    running = True
    driver = None
    try:
        log.info("Starting bot...")
        driver = create_driver()
        driver.get(URL)
        time.sleep(5)

        # ---- Solve CAPTCHA using captured sitekey ----
        captured = driver.execute_script("return window.__capturedSitekey;")
        try:
            log.info("Solving Turnstile via Peak...")
            if captured:
                log.info(f"Using captured sitekey: {captured[:15]}...")
                token = solve_turnstile(driver, sitekey=captured)
            else:
                log.info("No captured sitekey, trying auto-detection...")
                token = solve_turnstile(driver)
            log.info(f"Token injected (length={len(token)}).")
            time.sleep(2)
        except Exception as e:
            log.warning(f"Peak solve failed: {e}")

        # ---- Entry ----
        log.info("Clicking entry buttons...")
        if not try_click(driver, SEL_GIRL, "'I'm a girl'"):
            js_click(driver, SEL_GIRL, "'I'm a girl'")
        time.sleep(1)
        if not try_click(driver, SEL_START, "Start chatting"):
            js_click(driver, SEL_START, "Start chatting")
        time.sleep(2)
        log.info("Entry complete.")

        # ---- Main Loop ----
        for cycle in range(1, 999999):
            log.info(f"\n{'='*20} CYCLE {cycle} {'='*20}")

            if not is_matched(driver):
                log.info("Clicking 'Start chatting'...")
                if not try_click(driver, SEL_START, "Start chatting", timeout=3):
                    js_click(driver, SEL_START, "Start chatting", timeout=3)

            try:
                run_cycle(driver, random.choice(MESSAGE_SETS))
            except TimeoutException:
                log.warning("Match timeout. Reloading...")
                driver.refresh()
                time.sleep(3)
                captured = driver.execute_script("return window.__capturedSitekey;")
                try:
                    solve_turnstile(driver, sitekey=captured) if captured else solve_turnstile(driver)
                    log.info("Re-solved CAPTCHA after reload.")
                except Exception as e:
                    log.warning(f"Re-solve failed: {e}")
            except Exception as e:
                log.error(f"Cycle error: {e}")
                time.sleep(2)

            time.sleep(random.uniform(3.0, 9.0))

    except Exception as e:
        log.critical(f"Fatal: {e}")
        log.critical(traceback.format_exc())
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        running = False
        log.info("Bot finished.")

app = Flask(__name__)

@app.route("/")
def health():
    return f"opentalk bot: running={running}", 200

if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
