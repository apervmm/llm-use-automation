from surface.browser import BrowserSession
from surface.perception import snapshot

session = BrowserSession(headless=False)
session.goto("https://parabank.parasoft.com/parabank/index.htm")

state = snapshot(session, screenshot_path="evidence/manual/homepage.png")
print("URL:", state.url)
print("Title:", state.title)
print(f"Found {len(state.interactive_elements)} interactive elements:")
for el in state.interactive_elements:
    print(f"  [{el.role}] {el.accessible_name!r}")

session.close()