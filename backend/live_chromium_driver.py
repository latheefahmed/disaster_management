import re
import time
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


def find_frontend_base() -> str:
    candidates = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
    ]
    for base in candidates:
        try:
            r = requests.get(base + "/login", timeout=3)
            if r.status_code == 200:
                return base
        except Exception:
            pass
    raise RuntimeError("No frontend /login endpoint reachable")


def choose_option(select_locator, target_code: str) -> bool:
    options = select_locator.locator("option")
    for i in range(options.count()):
        opt = options.nth(i)
        label = (opt.inner_text() or "").strip()
        value = (opt.get_attribute("value") or "").strip()
        if value == target_code or re.search(r"\b" + re.escape(target_code) + r"\b", label):
            if value:
                select_locator.select_option(value=value)
            else:
                select_locator.select_option(label=label)
            return True
    return False


def login(page, base: str, role: str, username: str, passwords: list[str], state_code: str | None, district_code: str | None) -> bool:
    for password in passwords:
        print(f"[STEP] Login attempt role={role}, user={username}, pass={password}")
        page.goto(base + "/login", wait_until="domcontentloaded")
        page.get_by_placeholder(re.compile("username", re.I)).fill(username)
        page.get_by_placeholder(re.compile("password", re.I)).fill(password)

        selects = page.locator("select")
        selects.nth(0).select_option(role)
        if state_code and selects.count() > 1:
            choose_option(selects.nth(1), state_code)
        if district_code and selects.count() > 2:
            choose_option(selects.nth(2), district_code)

        page.get_by_role("button", name=re.compile("login", re.I)).click()

        ok = False
        for _ in range(40):
            url = page.url
            token = page.evaluate("() => localStorage.getItem('token')")
            if re.search(rf"/{role}$", url) and token:
                ok = True
                break
            page.wait_for_timeout(250)

        if ok:
            print(f"[PASS] Logged in as {role}")
            return True

        print(f"[FAIL] Login failed with password={password}")
    return False


def click_tabs(page, names: list[str], scope: str):
    for tab in names:
        try:
            page.get_by_role("button", name=tab).click(timeout=3000)
            print(f"[STEP] {scope} tab -> {tab}")
            page.wait_for_timeout(900)
        except Exception:
            print(f"[FAIL] {scope} tab not clickable -> {tab}")


def main():
    base = find_frontend_base()
    print(f"[STEP] Frontend base: {base}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=180)
        context = browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()

        district_ok = login(
            page=page,
            base=base,
            role="district",
            username="district_603",
            passwords=["disctrict123", "district123", "pw"],
            state_code="33",
            district_code="603",
        )

        if district_ok:
            click_tabs(page, ["Requests", "Allocations", "Upstream Supply", "Unmet", "Agent Recommendations", "Run History"], "District")

        state_ok = login(
            page=page,
            base=base,
            role="state",
            username="state_33",
            passwords=["state123", "pw"],
            state_code="33",
            district_code=None,
        )

        if state_ok:
            click_tabs(page, ["District Requests", "Mutual Aid Outgoing / Incoming", "State Stock", "Agent Recommendations", "Run History"], "State")

        print("[STEP] Keeping browser open for 120 seconds for live viewing...")
        time.sleep(120)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
