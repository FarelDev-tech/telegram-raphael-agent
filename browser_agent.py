import os
import sys
import time
import json
import base64
import datetime
import requests

# Force UTF-8 encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SCREENSHOT_DIR = r"C:\Users\USER\telegram_bridge\screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

GEMINI_API_KEY = "AIzaSyCAAuwepqWxoXJ2P8mmLUX4H0Wg2H5HFt8"

class LocalBrowserAgent:
    def __init__(self, headless=False):
        self.headless = headless
        self.executable_path = CHROME_PATH if os.path.exists(CHROME_PATH) else EDGE_PATH

    def _query_vision_action(self, instruction, screenshot_b64, page_url, page_title, step_history):
        """Asks Gemini Multimodal to inspect the web page and decide the next action."""
        prompt = (
            f"You are the Browser Agent Engine (Project Mariner Style) for Raphael AI-Brain.\n"
            f"Goal from Master Farel: \"{instruction}\"\n"
            f"Current URL: {page_url}\n"
            f"Current Page Title: {page_title}\n"
            f"Step History so far: {json.dumps(step_history)}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Look closely at the screenshot of the browser window.\n"
            f"2. Decide the SINGLE BEST NEXT ACTION to make progress toward the goal.\n"
            f"3. Return ONLY a valid JSON object with this exact structure:\n"
            f"{{\n"
            f"  \"thought\": \"Brief explanation of what you see and why this action is chosen\",\n"
            f"  \"action\": \"navigate | click | type | scroll_down | scroll_up | press_enter | extract_data | done\",\n"
            f"  \"url\": \"https://... (if action is navigate)\",\n"
            f"  \"selector\": \"CSS selector or visible text (e.g. text='Search', button:has-text('Cari'), input[name='q'])\",\n"
            f"  \"text\": \"Text to type (if action is type)\",\n"
            f"  \"extracted_summary\": \"Final summarized findings to report to Master Farel (if action is done or extract_data)\"\n"
            f"}}"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": screenshot_b64
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024}
        }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.7-flash:generateContent?key={GEMINI_API_KEY}"
        try:
            res = requests.post(url, json=payload, timeout=20)
            if res.status_code == 200:
                data = res.json()
                text_out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if "```json" in text_out:
                    text_out = text_out.split("```json")[1].split("```")[0].strip()
                elif "```" in text_out:
                    text_out = text_out.split("```")[1].split("```")[0].strip()
                return json.loads(text_out)
        except Exception as e:
            print(f"[Vision Action Error] {e}")
            # Fallback to gemini-3.6-flash or gemini-3.5-flash
            for fb_model in ["gemini-3.6-flash", "gemini-3.5-flash"]:
                try:
                    url_fb = f"https://generativelanguage.googleapis.com/v1beta/models/{fb_model}:generateContent?key={GEMINI_API_KEY}"
                    res_fb = requests.post(url_fb, json=payload, timeout=20)
                    if res_fb.status_code == 200:
                        data = res_fb.json()
                        text_out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if "```json" in text_out:
                            text_out = text_out.split("```json")[1].split("```")[0].strip()
                        elif "```" in text_out:
                            text_out = text_out.split("```")[1].split("```")[0].strip()
                        return json.loads(text_out)
                except Exception:
                    pass
        return None

    def execute_task(self, instruction, start_url=None, max_steps=5, callback_status=None):
        """
        Executes an end-to-end browser automation task.
        Returns: dict with status, final_summary, screenshots list, and execution trace.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {
                "success": False,
                "error": "Playwright belum terpasang. Jalankan 'pip install playwright' terlebih dahulu."
            }

        steps_log = []
        captured_screenshots = []
        final_summary = ""

        # Default start URL if none provided
        if not start_url:
            if "google" in instruction.lower():
                start_url = "https://www.google.com"
            elif "tokopedia" in instruction.lower():
                start_url = "https://www.tokopedia.com"
            elif "youtube" in instruction.lower():
                start_url = "https://www.youtube.com"
            elif "github" in instruction.lower():
                start_url = "https://www.github.com"
            else:
                # Use Google search as default entry
                clean_q = instruction.replace("cari", "").replace("buka", "").strip()
                start_url = f"https://www.google.com/search?q={requests.utils.quote(clean_q)}"

        if callback_status:
            callback_status(f"🌐 Membuka peramban Chrome: `{start_url}`...")

        with sync_playwright() as p:
            try:
                # Launch real Google Chrome if available, otherwise Chromium
                launch_kwargs = {
                    "headless": self.headless,
                    "args": ["--start-maximized", "--disable-blink-features=AutomationControlled"]
                }
                if self.executable_path and os.path.exists(self.executable_path):
                    launch_kwargs["executable_path"] = self.executable_path

                browser = p.chromium.launch(**launch_kwargs)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
                page = context.new_page()

                # Step 0: Navigate to initial URL
                page.goto(start_url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)

                for step_num in range(1, max_steps + 1):
                    # Capture screenshot
                    ts = int(time.time())
                    ss_path = os.path.join(SCREENSHOT_DIR, f"step_{step_num}_{ts}.png")
                    page.screenshot(path=ss_path, full_page=False)
                    captured_screenshots.append(ss_path)

                    with open(ss_path, "rb") as img_f:
                        ss_b64 = base64.b64encode(img_f.read()).decode("utf-8")

                    current_url = page.url
                    page_title = page.title()

                    # Decide next action via Gemini Vision
                    decision = self._query_vision_action(instruction, ss_b64, current_url, page_title, steps_log)
                    if not decision:
                        # Fallback: extract text from page
                        page_text = page.inner_text("body")[:1500]
                        final_summary = f"Konten Halaman ({page_title}):\n{page_text}"
                        break

                    action = decision.get("action", "done")
                    thought = decision.get("thought", "")
                    steps_log.append({"step": step_num, "action": action, "thought": thought, "url": current_url})

                    if callback_status:
                        callback_status(f"🤖 **Langkah {step_num}:** {thought} (Aksi: `{action}`)")

                    if action == "done":
                        final_summary = decision.get("extracted_summary") or decision.get("thought", "Tugas navigasi selesai.")
                        break
                    elif action == "navigate":
                        next_url = decision.get("url")
                        if next_url:
                            page.goto(next_url, timeout=20000, wait_until="domcontentloaded")
                            time.sleep(2)
                    elif action == "click":
                        sel = decision.get("selector", "")
                        if sel:
                            try:
                                page.click(sel, timeout=5000)
                                time.sleep(2)
                            except Exception:
                                # Try clicking by text
                                page.get_by_text(sel).first.click(timeout=5000)
                                time.sleep(2)
                    elif action == "type":
                        sel = decision.get("selector", "")
                        text_to_type = decision.get("text", "")
                        if sel and text_to_type:
                            try:
                                page.fill(sel, text_to_type, timeout=5000)
                                page.keyboard.press("Enter")
                                time.sleep(2)
                            except Exception:
                                page.keyboard.type(text_to_type)
                                page.keyboard.press("Enter")
                                time.sleep(2)
                    elif action == "scroll_down":
                        page.mouse.wheel(0, 500)
                        time.sleep(1.5)
                    elif action == "scroll_up":
                        page.mouse.wheel(0, -500)
                        time.sleep(1.5)
                    elif action == "press_enter":
                        page.keyboard.press("Enter")
                        time.sleep(2)
                    elif action == "extract_data":
                        final_summary = decision.get("extracted_summary", "")
                        break

                if not final_summary:
                    # Final text extraction
                    try:
                        final_summary = page.inner_text("body")[:1500]
                    except Exception:
                        final_summary = f"Navigasi selesai di {page.url} ({page.title()})"

                browser.close()

                return {
                    "success": True,
                    "summary": final_summary,
                    "screenshots": captured_screenshots,
                    "steps": steps_log,
                    "final_url": current_url,
                    "final_title": page_title
                }

            except Exception as e:
                print(f"[Browser Execution Error] {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "screenshots": captured_screenshots,
                    "steps": steps_log
                }

browser_agent = LocalBrowserAgent(headless=False)
