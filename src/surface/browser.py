import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser, Error as PWError
from safety.allowlist import Allowlist, PolicyViolation

from .types import ActionResult, ElementRef
from .helpers import (
    failed,
    is_top_level_navigation,
    policy_refusal,
    refused,
    resolve_locator,
    select_failure_message,
    succeeded,
)




class BrowserSession:
    def __init__(self, headless: bool = False, allowlist: Allowlist | None = None):
        self._pw = sync_playwright().start()
        self.browser: Browser = self._pw.chromium.launch(headless=headless)
        self.page: Page = self.browser.new_page()
        self.allowlist = allowlist or Allowlist()
        self._blocked_nav: str | None = None
        self.page.context.route("**/*", self._guard_navigation) 
        self._dialogs: list[str] = []
        self.page.on("dialog", self._on_dialog)


    def __enter__(self):
        return self
    

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


    # --------------- Actions ---------------------------
    def goto(self, url: str) -> ActionResult:
        if refusal := policy_refusal(self.allowlist, "navigate", url, label=url):
            return refusal
        start = time.time()
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            self.allowlist.check_url(self.page.url)
            return succeeded("navigate", url, start)
        except PolicyViolation as e:
            return refused("navigate", url, e)
        except PWError as e:
            return failed("navigate", url, e)
        

    def read_text(self, ref: ElementRef, description: str = "") -> ActionResult:
        label = description or ref.value
        if refusal := policy_refusal(self.allowlist, "read", self.page.url, label):
            return refusal
        
        start = time.time()
        try:
            text = resolve_locator(self.page, ref).inner_text(timeout=3000)
            return succeeded("read", label, start, value=text.strip())
        except Exception as e:
            return failed("read", label, e)


    def click(self, ref: ElementRef, description: str = "") -> ActionResult:
        label = description or ref.value
        if refusal := policy_refusal(self.allowlist, "click", self.page.url, label):
            return refusal
        start = time.time()
        try:
            resolve_locator(self.page, ref).click(timeout=5000)
            self.page.wait_for_timeout(250) 
            self._raise_if_blocked()
            self.allowlist.check_url(self.page.url)
            return succeeded("click", label, start)
        except PolicyViolation as e:
            return refused("click", label, e)
        except Exception as e:
            return failed("click", label, e)



    def select_option(self, ref: ElementRef, value: str, description: str = "") -> ActionResult:
        label = description or ref.value
        if refusal := policy_refusal(self.allowlist, "select_option", self.page.url, label):
            return refusal
        
        start = time.time()
        try:
            loc = self._resolve(ref)
        except Exception as e:
            return ActionResult(False, "select_option", label, error=str(e))
        
        try:
            loc.select_option(value=value, timeout=5000)
            self.allowlist.check_url(self.page.url)
            return succeeded("select_option", label, start, value=value)
        except PolicyViolation as e:
            return refused("select_option", label, e)
        except Exception as e:
            return failed("select_option", label, select_failure_message(loc, value, e))
        

    def type_text(self, ref: ElementRef, text: str, description: str = "") -> ActionResult:
        label = description or ref.value
        if refusal := policy_refusal(self.allowlist, "type_text", self.page.url, label, reported_as="type"):
            return refusal
        
        start = time.time()
        try:
            loc = resolve_locator(self.page, ref)
            loc.fill("", timeout=5000)
            loc.fill(text, timeout=5000)
            return succeeded("type", label, start)
        except Exception as e:
            return failed("type", label, e)
        

    # ------  Observation and utilities (used by replay and escalation) -----
    def get_url(self) -> str:
        return self.page.url
    

    def get_visible_text(self) -> str:
        return self.page.inner_text("body")
    

    def wait(self, ms: int) -> None:
        self.page.wait_for_timeout(ms)


    def is_visible(self, selector: str) -> bool:
        try:
            return self.page.locator(selector).first.is_visible()
        except Exception:
            return False
        

    def bring_to_front(self) -> None:
        self.page.bring_to_front()


    def screenshot(self, out_path: str) -> str:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=out_path)
        return out_path


    def pop_dialogs(self) -> list[str]:
        seen, self._dialogs = self._dialogs, []
        return seen


    def close(self):
        self.browser.close()
        self._pw.stop()


    # ------- Guards (Playwright event handlers) ----------
    def _guard_navigation(self, route, request):
        """Cancels top level navigations to URLs outside the allowlist"""
        if is_top_level_navigation(request):
            try:
                self.allowlist.check_url(request.url)
            except PolicyViolation as e:
                self._blocked_nav = str(e)
                return route.fulfill(status=204, body="")
        route.continue_()


    def _raise_if_blocked(self):
        if self._blocked_nav:
            msg, self._blocked_nav = self._blocked_nav, None
            raise PolicyViolation(msg)
    

    def _on_dialog(self, dialog):
        """Records any JS dialog and dismiss it"""
        self._dialogs.append(f"{dialog.type}: {dialog.message}")
        dialog.dismiss()




    
        


        
        