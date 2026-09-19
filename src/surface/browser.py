import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PWTimeout

from .types import ActionResult, ElementRef, LocatorStrategy

from safety.allowlist import Allowlist, PolicyViolation


class BrowserSession:

    def __init__(self, headless: bool = False, allowlist: Allowlist | None = None):
        self._pw = sync_playwright().start()
        self.browser: Browser = self._pw.chromium.launch(headless=headless)
        self.page: Page = self.browser.new_page()
        self.allowlist = allowlist or Allowlist()

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


    # navigation
    def goto(self, url: str) -> ActionResult:
        start = time.time()
        try:
            self.allowlist.check_action("navigate", url=url)
            self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            self.allowlist._check_url(self.page.url)
            return ActionResult(True, "navigate",  url, duration_ms=int((time.time() - start) * 1000))
        except PWTimeout as e:
            return ActionResult(False, "navigate", url, error=str(e))
        except PolicyViolation as e:
            return ActionResult(False, "navigate", url, error=str(e))


    # esolving a locator descriptor to a live locator
    def _resolve(self, ref: ElementRef):
        candidates = [ref] + ref.fallbacks
        errors = []
        for candidate in candidates:
            try:
                loc = self._to_playwright_locator(candidate)
                loc.wait_for(state="visible", timeout=3000)
                return loc
            except Exception as e:
                errors.append(f"{candidate.strategy.value}='{candidate.value}': {type(e).__name__}: {e}")
                continue
        detail = " | ".join(errors)
        raise RuntimeError(f"No locator strategy matched. Attempts: {detail}")


    def _to_playwright_locator(self, ref: ElementRef):
        if ref.strategy == LocatorStrategy.ROLE_NAME:
            return self.page.get_by_role(ref.role, name=ref.value, exact=False).first
        if ref.strategy == LocatorStrategy.CSS:
            return self.page.locator(ref.value).first
        if ref.strategy == LocatorStrategy.TEXT:
            return self.page.get_by_text(ref.value, exact=False).first
        if ref.strategy == LocatorStrategy.XPATH:
            return self.page.locator(f"xpath={ref.value}").first
        raise ValueError(f"Unknown strategy {ref.strategy}")
    

    def read_text(self, ref: ElementRef, description: str = "") -> ActionResult:
        try:
            self.allowlist.check_action("read", url=self.page.url)
        except PolicyViolation as e:
            return ActionResult(False, "read", description or ref.value, error=str(e))

        start = time.time()
        try:
            text = self._resolve(ref).inner_text(timeout=3000)
            return ActionResult(True, "read", description or ref.value, duration_ms=int((time.time() - start) * 1000), value=text.strip())
        except Exception as e:
            return ActionResult(False, "read", description or ref.value, error=str(e))


    #  actions 
    def click(self, ref: ElementRef, description: str = "") -> ActionResult:
        try:
            self.allowlist.check_action("click", url=self.page.url)
        except PolicyViolation as e:
            return ActionResult(False, "click", description or ref.value, error=str(e))
        
        start = time.time()
        try:
            self._resolve(ref).click(timeout=5000)
            self.allowlist._check_url(self.page.url)
            return ActionResult(True, "click", description or ref.value, duration_ms=int((time.time() - start) * 1000))
        except Exception as e:
            return ActionResult(False, "click", description or ref.value, error=str(e))
        
    def select_option(self, ref: ElementRef, value: str, description: str = "") -> ActionResult:
        try:
            self.allowlist.check_action("select_option", url=self.page.url)
        except PolicyViolation as e:
            return ActionResult(False, "select_option", description or ref.value, error=str(e))

        start = time.time()
        try:
            self._resolve(ref).select_option(value=value, timeout=5000)
            return ActionResult(True, "select_option", description or ref.value, duration_ms=int((time.time() - start) * 1000), value=value)
        except Exception as e:
            return ActionResult(False, "select_option", description or ref.value, error=str(e))


    def type_text(self, ref: ElementRef, text: str, description: str = "") -> ActionResult:
        try:
            self.allowlist.check_action("type_text", url=self.page.url)
        except PolicyViolation as e:
            return ActionResult(False, "type", description or ref.value, error=str(e))
        
        start = time.time()
        try:
            loc = self._resolve(ref)
            loc.fill("", timeout=5000)
            loc.fill(text, timeout=5000)
            return ActionResult(True, "type", description or ref.value, duration_ms=int((time.time() - start) * 1000))
        except Exception as e:
            return ActionResult(False, "type", description or ref.value, error=str(e))


    def screenshot(self, out_path: str) -> str:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=out_path)
        return out_path


    def close(self):
        self.browser.close()
        self._pw.stop()