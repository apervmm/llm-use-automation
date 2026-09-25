import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PWTimeout, Error as PWError

from .types import ActionResult, ElementRef, LocatorStrategy

from safety.allowlist import Allowlist, PolicyViolation


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


    def _diagnose_select_failure(self, loc, value: str) -> str:
        try:
            # loc = self.page.locator(ref.value).firsts
            options = loc.locator("option")
            count = options.count()
            if not loc.is_visible():
                return "The dropdown isn't visible on the page right now."
            if count == 0:
                return "The dropdown is visible but has 0 options loaded — the page likely hadn't finished loading yet."
            values = [options.nth(i).get_attribute("value") for i in range(count)]
            if value in values:
                return f"'{value}' IS present among {values} — the failure was something else (timing, stale element, etc.)."
            return f"The dropdown has {count} option(s): {values}. '{value}' isn't one of them."
        except Exception as e:
            return f"Couldn't inspect the dropdown: {type(e).__name__}: {e}"
    

    def _verify(self, loc, candidate: ElementRef) -> bool:
        if not candidate.expected_name:
            return True  # nothing to check against (e.g. old artifacts)
        
        if candidate.strategy == LocatorStrategy.CSS:
            is_stable = candidate.value.startswith("#") or "[name=" in candidate.value
            if is_stable:
                return True
            
        if candidate.role not in ("link", "button"):
            return True
        
        try:
            actual = loc.evaluate(
                "el => (el.getAttribute('aria-label') || el.innerText || el.textContent || '').trim()"
            )
        except Exception:
            return True
        
        if not actual:
            return True
        
        return candidate.expected_name.strip().lower() in actual.strip().lower()
    

    def _guard_navigation(self, route, request):
        """Cancel top-level navigations (any tab, including popups) to URLs outside the allowlist."""
        if request.is_navigation_request():
            try:
                is_top_level = request.frame.parent_frame is None
            except Exception:
                is_top_level = True
            if is_top_level:
                try:
                    self.allowlist._check_url(request.url)
                except PolicyViolation as e:
                    self._blocked_nav = str(e)
                    return route.fulfill(status=204, body="")
        route.continue_()


    def _raise_if_blocked(self):
        if self._blocked_nav:
            msg, self._blocked_nav = self._blocked_nav, None
            raise PolicyViolation(msg)
    

    def _on_dialog(self, dialog):
        """Record any JS dialog and dismiss it (never auto-accept)."""
        self._dialogs.append(f"{dialog.type}: {dialog.message}")
        dialog.dismiss()


    def pop_dialogs(self) -> list[str]:
        """Return dialogs seen since the last call, and clear the list."""
        seen, self._dialogs = self._dialogs, []
        return seen


    # esolving a locator descriptor to a live locator
    def _resolve(self, ref: ElementRef):
        candidates = [ref] + ref.fallbacks
        errors = []
        for candidate in candidates:
            try:
                loc = self._to_playwright_locator(candidate)
                loc.wait_for(state="visible", timeout=3000)
                if not self._verify(loc, candidate):
                    errors.append(f"{candidate.strategy.value}='{candidate.value}': resolved but name mismatch")
                    continue
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
    
    def get_visible_text(self) -> str:
        return self.page.inner_text("body")
    
    def get_url(self) -> str:
        return self.page.url
    
    def wait(self, ms: int) -> None:
        self.page.wait_for_timeout(ms)

    def is_visible(self, selector: str) -> bool:
        try:
            return self.page.locator(selector).first.is_visible()
        except Exception:
            return False
        

    def bring_to_front(self) -> None:
        self.page.bring_to_front()
    
    # navigation
    def goto(self, url: str) -> ActionResult:
        start = time.time()
        try:
            self.allowlist.check_action("navigate", url=url)
            self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            self.allowlist._check_url(self.page.url)
            return ActionResult(True, "navigate",  url, duration_ms=int((time.time() - start) * 1000))
        except PolicyViolation as e:
            return ActionResult(False, "navigate", url, error=str(e), policy_violation=True)
        except PWError as e:
            return ActionResult(False, "navigate", url, error=str(e))
        

    def read_text(self, ref: ElementRef, description: str = "") -> ActionResult:
        try:
            self.allowlist.check_action("read", url=self.page.url)
        except PolicyViolation as e:
            return ActionResult(False, "read", description or ref.value, error=str(e), policy_violation=True)

        start = time.time()
        try:
            text = self._resolve(ref).inner_text(timeout=3000)
            return ActionResult(True, "read", description or ref.value, duration_ms=int((time.time() - start) * 1000), value=text.strip())
        except Exception as e:
            return ActionResult(False, "read", description or ref.value, error=str(e))


    #  actions 
    def click(self, ref: ElementRef, description: str = "") -> ActionResult:
        label = description or ref.value
        try:
            self.allowlist.check_action("click", url=self.page.url)
        except PolicyViolation as e:
            return ActionResult(False, "click", description or ref.value, error=str(e), policy_violation=True)
        
        start = time.time()
        try:
            self._resolve(ref).click(timeout=5000)
            self.page.wait_for_timeout(250) 
            self._raise_if_blocked()
            self.allowlist._check_url(self.page.url)
            return ActionResult(True, "click", description or ref.value, duration_ms=int((time.time() - start) * 1000))
        except PolicyViolation as e:
            return ActionResult(False, "click", label, error=str(e), policy_violation=True)
        except Exception as e:
            return ActionResult(False, "click", description or ref.value, error=str(e))
        
        
    def select_option(self, ref: ElementRef, value: str, description: str = "") -> ActionResult:
        # loc = self._resolve(ref) 
        label = description or ref.value

        # 1. Policy check 
        try:
            self.allowlist.check_action("select_option", url=self.page.url)
        except PolicyViolation as e:
            return ActionResult(False, "select_option", label, error=str(e), policy_violation=True)

        # loc = self._resolve(ref) 
        start = time.time()


        try:
            loc = self._resolve(ref)
        except Exception as e:
            return ActionResult(False, "select_option", label, error=str(e))

                # 3. Wait for the wanted option to load, then select it
        try:
            # loc.locator(f'option[value="{value}"]').wait_for(state="attached", timeout=5000)
            loc.select_option(value=value, timeout=5000)
            self.allowlist._check_url(self.page.url)
            return ActionResult(
                True, 
                "select_option", 
                label,
                duration_ms=int((time.time() - start) * 1000), 
                value=value
            )
        except PolicyViolation as e:
            return ActionResult(False, "select_option", label, error=str(e), policy_violation=True)
        except Exception as e:
            diagnosis = self._diagnose_select_failure(loc, value)   # loc, not ref
            first_line = str(e).splitlines()[0]
            return ActionResult(
                False, 
                "select_option", 
                label,
                error=f"{diagnosis} | raw error: {type(e).__name__}: {first_line}"
        )


    def type_text(self, ref: ElementRef, text: str, description: str = "") -> ActionResult:
        try:
            self.allowlist.check_action("type_text", url=self.page.url)
        except PolicyViolation as e:
            return ActionResult(False, "type", description or ref.value, error=str(e), policy_violation=True)
        
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