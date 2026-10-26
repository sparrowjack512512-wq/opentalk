import os
import random
import time
import threading
import logging
import traceback
from flask import Flask
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, InvalidSessionIdException

# ============================================================
# CONFIG
# ============================================================
URL = "https://opentalk.club/text/"

SEL_GIRL  = "button.ot-onb-action:not(.is-primary)"
SEL_START = "button.ot-onb-action.is-primary"
SEL_INPUT = "#chatInput"
SEL_SEND  = "#chatSend"
SEL_SKIP  = "#startBtn"
SEL_LEAVE = "#stopBtn"

MESSAGE_SETS = [
    ["Hii", "F 20", "talk to me on Chitmet gg", "Lisaaa9848"],
    ["hey", "F 20", "chat with me on Chitmet gg", "Lisaaa9848"],
    ["heyyy", "F 20", "find me on Chitmet gg", "Lisaaa9848"],
    ["hiii there", "F 20", "let's chat on Chitmet gg", "Lisaaa9848"],
    ["hellooo", "F 20", "message me on Chitmet gg", "Lisaaa9848"],
    ["hey you", "F 20", "come talk on Chitmet gg", "Lisaaa9848"],
    ["hiiiii", "F 20", "join me on Chitmet gg", "Lisaaa9848"],
    ["heyy", "F 20", "wanna chat on Chitmet gg?", "Lisaaa9848"],
    ["hello", "F 20", "let's connect on Chitmet gg", "Lisaaa9848"],
    ["hii dear", "F 20", "I'm on Chitmet gg", "Lisaaa9848"],
    ["heyyyy", "F 20", "come say hi on Chitmet gg", "Lisaaa9848"],
    ["hiii :) ", "F 20", "talk with me on Chitmet gg", "Lisaaa9848"],
    ["hey there", "F 20", "find me over on Chitmet gg", "Lisaaa9848"],
    ["helloooo", "F 20", "let's talk on Chitmet gg", "Lisaaa9848"],
    ["hii", "F 20", "send me a message on Chitmet gg", "Lisaaa9848"],
    ["heyyy :) ", "F 20", "let's have a chat on Chitmet gg", "Lisaaa9848"],
    ["hiiii", "F 20", "you can reach me on Chitmet gg", "Lisaaa9848"],
    ["hey what's up", "F 20", "chat with me over on Chitmet gg", "Lisaaa9848"],
    ["hii cutie", "F 20", "come chat with me on Chitmet gg", "Lisaaa9848"],
    ["heyy", "F 20", "say hello on Chitmet gg", "Lisaaa9848"]
]

MATCH_TIMEOUT      = 90
MAX_CYCLES         = 999999999999999
POST_START_WAIT    = 3.0
TYPE_DELAY_MIN     = 0.02
TYPE_DELAY_MAX     = 0.08
ENTER_DELAY_MIN    = 0.3
ENTER_DELAY_MAX    = 0.8
MSG_GAP            = 3.5
POST_SEND_WAIT_MIN = 20.0
POST_SEND_WAIT_MAX = 25.0
POST_LAST_MSG_SETTLE_MIN = 1.0
POST_LAST_MSG_SETTLE_MAX = 2.0
SKIP_CLICK_GAP     = 0.6
CYCLE_PAUSE_MIN    = 3.0
CYCLE_PAUSE_MAX    = 9.0

CAPTCHA_WAIT_TIMEOUT = 40.0
RECONNECT_TIME = 5

PROXY_URL = os.environ.get("PROXY_URL", "")
IS_SERVER = os.name != "nt"

# ============================================================
# LOGGING
# ============================================================
LOG_FILE = "opentalk_bot.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger("opentalk")

running = False
stop_flag = False
driver = None

# ============================================================
# HELPERS (unchanged)
# ============================================================
def human_type(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(TYPE_DELAY_MIN, TYPE_DELAY_MAX))

def wait_for(d, selector, timeout, condition="presence"):
    w = WebDriverWait(d, timeout)
    if condition == "clickable":
        return w.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
    if condition == "visible":
        return w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
    return w.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))

def try_click(d, selector, label, timeout=2):
    try:
        el = wait_for(d, selector, timeout=timeout, condition="clickable")
        el.click()
        log.info(f"✅ Clicked: {label}")
        return True
    except Exception as e:
        log.warning(f"⚠️ Could not click '{label}': {type(e).__name__}")
        return False

def js_click(d, selector, label, timeout=5):
    try:
        el = WebDriverWait(d, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        d.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", el)
        log.info(f"✅ Clicked (JS): {label}")
        return True
    except Exception as e:
        log.warning(f"⚠️ Could not JS-click '{label}': {type(e).__name__}")
        return False

def is_matched(d):
    try:
        inp = d.find_element(By.CSS_SELECTOR, SEL_INPUT)
        return inp.is_displayed() and inp.is_enabled()
    except (NoSuchElementException, WebDriverException):
        return False

def wait_for_captcha_to_pass(d, timeout=CAPTCHA_WAIT_TIMEOUT):
    log.info(f"⏳ Waiting up to {timeout}s for CAPTCHA to be solved...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            d.find_element(By.CSS_SELECTOR, SEL_GIRL)
            log.info("✅ CAPTCHA passed! 'I'm a girl' button is present.")
            return True
        except NoSuchElementException:
            pass
        if is_matched(d):
            log.info("✅ CAPTCHA passed! Chat input is visible.")
            return True
        time.sleep(0.5)
    log.error(f"❌ CAPTCHA not solved within {timeout}s.")
    return False

def handle_entry(d):
    log.info("=" * 60)
    log.info(f"🚀 Opening page (Server mode: {IS_SERVER})...")
    log.info("=" * 60)
    try:
        d.uc_open_with_reconnect(URL, reconnect_time=RECONNECT_TIME)
    except Exception as e:
        log.error(f"❌ Failed to open URL: {e}")
        raise
    time.sleep(2)

    if not wait_for_captcha_to_pass(d, timeout=5):
        log.info("🔄 Attempting automatic CAPTCHA click via SeleniumBase...")
        try:
            d.uc_gui_click_captcha()
        except Exception as e:
            log.warning(f"⚠️ Automatic CAPTCHA click failed: {e}")
        if not wait_for_captcha_to_pass(d, timeout=CAPTCHA_WAIT_TIMEOUT):
            log.error("❌ Could not bypass CAPTCHA automatically.")
            raise TimeoutException("CAPTCHA not solved")

    log.info("🖱️ Clicking entry buttons...")
    if not try_click(d, SEL_GIRL, "'I'm a girl'"):
        js_click(d, SEL_GIRL, "'I'm a girl'")
    time.sleep(1)
    if not try_click(d, SEL_START, "Start chatting"):
        js_click(d, SEL_START, "Start chatting")
    time.sleep(2)
    log.info("✅ Entry flow completed.")

def skip_chat(d):
    try:
        log.info("⏭️ Skipping chat (#startBtn)...")
        btn = wait_for(d, SEL_SKIP, timeout=10, condition="clickable")
        log.info(f"   Before click 1: text='{btn.text}'")
        btn.click()
        log.info("✅ Skip click 1")
        time.sleep(SKIP_CLICK_GAP)
        try:
            btn2 = wait_for(d, SEL_SKIP, timeout=5, condition="clickable")
            log.info(f"   Before click 2: text='{btn2.text}'")
            btn2.click()
            log.info("✅ Skip click 2 (confirmed)")
            time.sleep(1.0)
        except Exception as e:
            log.warning(f"⚠️ Second skip click: {e}")
        log.info("✅ Left chat.")
    except Exception as e:
        log.error(f"❌ Skip failed: {type(e).__name__}: {e}")

def send_message(d, input_box, text):
    deadline = time.time() + 10
    while time.time() < deadline:
        if input_box.is_displayed() and input_box.is_enabled():
            break
        time.sleep(0.2)
    else:
        log.error("❌ Input box not ready.")
        return
    input_box.clear()
    human_type(input_box, text)
    time.sleep(random.uniform(ENTER_DELAY_MIN, ENTER_DELAY_MAX))
    if not try_click(d, SEL_SEND, "send", timeout=3):
        input_box.send_keys(Keys.ENTER)

def run_cycle(d, messages):
    log.info(f"⏳ Waiting {POST_START_WAIT}s...")
    time.sleep(POST_START_WAIT)
    if not is_matched(d):
        log.info(f"🔍 Polling for match (up to {MATCH_TIMEOUT}s)...")
        deadline = time.time() + MATCH_TIMEOUT
        while time.time() < deadline:
            if is_matched(d):
                break
            time.sleep(0.4)
        else:
            raise TimeoutException("Match timeout")
    log.info("🎉 Matched!")
    input_box = d.find_element(By.CSS_SELECTOR, SEL_INPUT)
    log.info(f"💬 Sending: {messages}")
    for i, msg in enumerate(messages):
        send_message(d, input_box, msg)
        log.info(f"✅ Sent {i+1}: {msg}")
        if i < len(messages) - 1:
            time.sleep(MSG_GAP)
    settle = random.uniform(POST_LAST_MSG_SETTLE_MIN, POST_LAST_MSG_SETTLE_MAX)
    time.sleep(settle)
    post_wait = random.uniform(POST_SEND_WAIT_MIN, POST_SEND_WAIT_MAX)
    log.info(f"⏳ Waiting {post_wait:.2f}s before skip...")
    time.sleep(post_wait)
    skip_chat(d)

# ============================================================
# BOT LOOP (uses Driver, not SB)
# ============================================================
def bot_loop():
    global running, stop_flag, driver
    running = True
    try:
        log.info("Creating Driver...")
        driver_kwargs = {"uc": True}
        if IS_SERVER:
            driver_kwargs["xvfb"] = True
            driver_kwargs["binary_location"] = "/usr/bin/google-chrome"
            log.info("Server mode: xvfb=True, binary=/usr/bin/google-chrome")
        else:
            driver_kwargs["headless"] = False
            log.info("Local mode: headless=False")

        try:
            driver = Driver(**driver_kwargs)
            log.info("✅ Driver created successfully.")
        except Exception as e:
            log.critical(f"❌ Driver creation failed: {e}")
            log.critical(traceback.format_exc())
            return

        handle_entry(driver)

        for cycle in range(1, MAX_CYCLES + 1):
            if stop_flag:
                break
            log.info(f"\n{'='*20} CYCLE {cycle} {'='*20}")
            try:
                driver.current_url
            except InvalidSessionIdException:
                log.error("❌ Session died. Restarting...")
                break

            if not is_matched(driver):
                log.info("🔄 Clicking 'Start chatting'...")
                if not try_click(driver, SEL_START, "Start chatting", timeout=3):
                    js_click(driver, SEL_START, "Start chatting", timeout=3)

            try:
                run_cycle(driver, random.choice(MESSAGE_SETS))
            except TimeoutException:
                log.warning("⏰ Match timeout. Reloading...")
                driver.refresh()
                time.sleep(3)
                if not wait_for_captcha_to_pass(driver, timeout=5):
                    log.warning("⚠️ CAPTCHA reappeared. Attempting solve...")
                    try:
                        driver.uc_gui_click_captcha()
                    except:
                        pass
                    if not wait_for_captcha_to_pass(driver, timeout=CAPTCHA_WAIT_TIMEOUT):
                        log.error("❌ Could not re-solve. Restarting.")
                        break
            except InvalidSessionIdException:
                log.error("❌ Session lost. Restarting...")
                break
            except Exception as e:
                log.error(f"❌ Cycle error: {e}")
                time.sleep(2)

            pause = random.uniform(CYCLE_PAUSE_MIN, CYCLE_PAUSE_MAX)
            log.info(f"💤 Cycle pause: {pause:.1f}s")
            time.sleep(pause)

    except KeyboardInterrupt:
        log.info("🛑 Interrupted.")
    except Exception as e:
        log.critical(f"💥 Fatal in bot_loop: {e}")
        log.critical(traceback.format_exc())
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        running = False
        log.info("🏁 Bot finished.")

# ============================================================
# FLASK
# ============================================================
app = Flask(__name__)

@app.route("/")
def health():
    return f"opentalk bot: running={running}", 200

# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
