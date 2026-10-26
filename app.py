import os
import random
import time
import threading
import logging
import traceback
from flask import Flask
from seleniumbase import SB
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, InvalidSessionIdException

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
MAX_CYCLES = 999999
POST_START_WAIT = 3.0
TYPE_DELAY_MIN = 0.02
TYPE_DELAY_MAX = 0.08
ENTER_DELAY_MIN = 0.3
ENTER_DELAY_MAX = 0.8
MSG_GAP = 3.5
POST_SEND_WAIT_MIN = 20.0
POST_SEND_WAIT_MAX = 25.0
SKIP_CLICK_GAP = 0.6
CYCLE_PAUSE_MIN = 3.0
CYCLE_PAUSE_MAX = 9.0
CAPTCHA_WAIT_TIMEOUT = 40.0

IS_SERVER = os.name != "nt"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("opentalk")

running = False
stop_flag = False

def human_type(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(TYPE_DELAY_MIN, TYPE_DELAY_MAX))

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
    except (NoSuchElementException, WebDriverException):
        return False

def wait_for_captcha_to_pass(d, timeout=CAPTCHA_WAIT_TIMEOUT):
    log.info(f"Waiting up to {timeout}s for CAPTCHA...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            d.find_element(By.CSS_SELECTOR, SEL_GIRL)
            log.info("CAPTCHA passed! 'I'm a girl' present.")
            return True
        except NoSuchElementException:
            pass
        if is_matched(d):
            log.info("CAPTCHA passed! Chat input visible.")
            return True
        time.sleep(0.5)
    log.error(f"CAPTCHA not solved within {timeout}s.")
    return False

def handle_entry(d):
    log.info("Opening page...")
    try:
        d.uc_open_with_reconnect(URL, reconnect_time=5)
    except Exception as e:
        log.error(f"Failed to open URL: {e}")
        raise
    time.sleep(2)

    if not wait_for_captcha_to_pass(d, timeout=5):
        log.info("Attempting CAPTCHA solve via CDP...")
        try:
            # solve_captcha uses CDP, not PyAutoGUI
            d.solve_captcha()
        except Exception as e:
            log.warning(f"solve_captcha failed: {e}")
        if not wait_for_captcha_to_pass(d, timeout=CAPTCHA_WAIT_TIMEOUT):
            log.error("Could not bypass CAPTCHA.")
            raise TimeoutException("CAPTCHA not solved")

    log.info("Clicking entry buttons...")
    if not try_click(d, SEL_GIRL, "'I'm a girl'"):
        js_click(d, SEL_GIRL, "'I'm a girl'")
    time.sleep(1)
    if not try_click(d, SEL_START, "Start chatting"):
        js_click(d, SEL_START, "Start chatting")
    time.sleep(2)
    log.info("Entry flow completed.")

def skip_chat(d):
    try:
        log.info("Skipping chat...")
        btn = wait_for(d, SEL_SKIP, timeout=10, condition="clickable")
        btn.click()
        log.info("Skip click 1")
        time.sleep(SKIP_CLICK_GAP)
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
    time.sleep(random.uniform(ENTER_DELAY_MIN, ENTER_DELAY_MAX))
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
    global running, stop_flag
    running = True
    try:
        sb_kwargs = {"uc": True}
        if IS_SERVER:
            sb_kwargs["xvfb"] = True
            sb_kwargs["binary_location"] = "/usr/bin/google-chrome"
            log.info("Server mode: SB(uc=True, xvfb=True)")
        else:
            sb_kwargs["headless"] = False
            log.info("Local mode: SB(uc=True)")

        log.info("Entering SB context...")
        sb = SB(**sb_kwargs)
        try:
            sb.__enter__()
            log.info("SB entered.")
        except Exception as e:
            log.critical(f"SB __enter__ failed: {e}")
            log.critical(traceback.format_exc())
            return

        try:
            d = sb.driver
            log.info("Driver created.")
            handle_entry(d)

            for cycle in range(1, MAX_CYCLES + 1):
                if stop_flag:
                    break
                log.info(f"CYCLE {cycle}")

                try:
                    d.current_url
                except InvalidSessionIdException:
                    log.error("Session died.")
                    break

                if not is_matched(d):
                    log.info("Clicking 'Start chatting'...")
                    if not try_click(d, SEL_START, "Start chatting", timeout=3):
                        js_click(d, SEL_START, "Start chatting", timeout=3)

                try:
                    run_cycle(d, random.choice(MESSAGE_SETS))
                except TimeoutException:
                    log.warning("Match timeout. Reloading...")
                    d.refresh()
                    time.sleep(3)
                    if not wait_for_captcha_to_pass(d, timeout=5):
                        log.warning("CAPTCHA reappeared. Trying solve_captcha...")
                        try:
                            d.solve_captcha()
                        except Exception as e:
                            log.warning(f"solve_captcha failed: {e}")
                        if not wait_for_captcha_to_pass(d, timeout=CAPTCHA_WAIT_TIMEOUT):
                            log.error("Could not re-solve. Restarting.")
                            break
                except InvalidSessionIdException:
                    log.error("Session lost.")
                    break
                except Exception as e:
                    log.error(f"Cycle error: {e}")
                    time.sleep(2)

                time.sleep(random.uniform(CYCLE_PAUSE_MIN, CYCLE_PAUSE_MAX))

        finally:
            try:
                sb.__exit__(None, None, None)
            except Exception:
                pass

    except KeyboardInterrupt:
        log.info("Interrupted.")
    except Exception as e:
        log.critical(f"Fatal: {e}")
        log.critical(traceback.format_exc())
    finally:
        running = False
        log.info("Bot finished.")

app = Flask(__name__)

@app.route("/")
def health():
    return f"opentalk bot: running={running}", 200

if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
