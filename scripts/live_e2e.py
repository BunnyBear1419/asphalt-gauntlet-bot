#!/usr/bin/env python3
"""Read-only live browser acceptance checks for the deployed RSL site.

This suite deliberately avoids authenticated mutations, submissions, purchases,
club creation, match settlement, tournament changes, and Discord writes.
It exercises the real deployed website with Chromium and verifies that the
public shell and previously fragile navigation/control surfaces are functional.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

BASE_URL = os.getenv("RSL_LIVE_URL", "https://asph.discloud.app").rstrip("/")
AUTH_STATE_JSON = os.getenv("RSL_E2E_AUTH_STATE", "").strip()
AUTH_STATE_FILE = os.getenv("RSL_E2E_AUTH_STATE_FILE", "").strip()
PUBLIC_ROUTES = [
    "/",
    "/rules",
    "/help",
    "/calendar",
    "/tournaments",
]
PROTECTED_ROUTES = [
    "/clubs",
    "/player/settings",
    "/admin",
]


def check_page(page: Page, path: str) -> None:
    url = f"{BASE_URL}{path}"
    response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    if response is None:
        raise AssertionError(f"{path}: navigation returned no response")
    if response.status >= 500:
        raise AssertionError(f"{path}: HTTP {response.status}")
    if not page.title():
        raise AssertionError(f"{path}: missing document title")
    page.wait_for_load_state("networkidle", timeout=15_000)


def check_public_shell(page: Page) -> None:
    page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=15_000)

    nav = page.locator('nav[aria-label="Primary navigation"]')
    if nav.count() != 1:
        raise AssertionError("homepage: primary navigation missing")

    for href in ("/", "/clubs", "/rules"):
        if page.locator(f'nav a[href="{href}"]').count() == 0:
            raise AssertionError(f"homepage: missing navigation target {href}")

    companion = page.locator("details.companion-nav-dropdown")
    if companion.count() != 1:
        raise AssertionError("homepage: Companion navigation is missing or duplicated")

    companion_link = companion.locator('a.companion-info-link[href="https://alu.shohanlab.com/"]')
    if companion_link.count() != 1:
        raise AssertionError("homepage: Companion target changed unexpectedly")


def check_clubs_controls(page: Page) -> None:
    check_page(page, "/clubs")
    if "/login" in page.url:
        raise AssertionError("clubs: authenticated state was rejected and redirected to login")

    create = page.locator("#open-create")
    if create.count() != 1:
        raise AssertionError("clubs: Create Club control missing")

    create.click()
    panel = page.locator("#create-panel")
    if panel.count() != 1 or not panel.is_visible():
        raise AssertionError("clubs: Create Club control did not open its panel")

    add_link = page.locator("#add-create-club-link")
    if add_link.count() != 1:
        raise AssertionError("clubs: Add Link control missing")
    before = page.locator("#create-club-links").locator("input").count()
    add_link.click()
    after = page.locator("#create-club-links").locator("input").count()
    if after <= before:
        raise AssertionError("clubs: Add Link control did not update the form")

    close = page.locator("#close-create")
    if close.count() != 1:
        raise AssertionError("clubs: Close control missing")
    close.click()
    if panel.is_visible():
        raise AssertionError("clubs: Close control did not close the panel")


def check_responsive(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2")
    if overflow:
        raise AssertionError("mobile homepage has horizontal overflow")
    page.set_viewport_size({"width": 1440, "height": 1000})


def check_protected_redirects(page: Page) -> None:
    for path in PROTECTED_ROUTES:
        page.goto(BASE_URL + path, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        if "/login" not in page.url:
            body = page.locator("body").inner_text().lower()
            if "login" not in body and "staff" not in body and "unauthorized" not in body:
                raise AssertionError(f"{path}: no visible authentication/staff gate")


def load_auth_state() -> dict:
    raw = AUTH_STATE_JSON
    source = "RSL_E2E_AUTH_STATE"
    if not raw and AUTH_STATE_FILE:
        source = "RSL_E2E_AUTH_STATE_FILE"
        raw = Path(AUTH_STATE_FILE).read_text(encoding="utf-8")
    if not raw:
        raise AssertionError("authenticated suite requested but no auth state was supplied")
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{source} is not valid JSON") from exc
    if not isinstance(state, dict):
        raise AssertionError(f"{source} must contain a JSON object")
    cookies = state.get("cookies", [])
    origins = state.get("origins", [])
    if not isinstance(cookies, list) or not isinstance(origins, list):
        raise AssertionError(f"{source} has an invalid Playwright storage-state shape")
    expiring = [
        float(cookie.get("expires", 0) or 0)
        for cookie in cookies
        if isinstance(cookie, dict) and float(cookie.get("expires", 0) or 0) > 0
    ]
    if expiring and max(expiring) <= time.time():
        raise AssertionError(f"{source} is expired; create a fresh test-account storage state")
    return state


def check_authenticated_routes(page: Page) -> None:
    routes = [
        "/player/settings",
        "/player",
        "/profile",
        "/my-tournaments",
        "/clubs",
        "/tournaments",
    ]
    for path in routes:
        check_page(page, path)
        if "/login" in page.url:
            raise AssertionError(f"{path}: authenticated state was rejected and redirected to login")
        body = page.locator("body").inner_text().lower()
        if "temporarily unavailable" in body or "service unavailable" in body:
            raise AssertionError(f"{path}: authenticated page shows an unavailable state")

    check_clubs_controls(page)


def run() -> int:
    failures: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    auth_enabled = bool(AUTH_STATE_JSON or AUTH_STATE_FILE)
    auth_state_path: str | None = None

    with sync_playwright() as pw:
        browser: Browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(f"{exc}\n{getattr(exc, \"stack\", \"\")}"))

        try:
            for path in PUBLIC_ROUTES:
                try:
                    check_page(page, path)
                except Exception as exc:
                    failures.append(str(exc))

            try:
                check_public_shell(page)
            except Exception as exc:
                failures.append(str(exc))

            try:
                check_responsive(page)
            except Exception as exc:
                failures.append(str(exc))

            try:
                check_protected_redirects(page)
            except Exception as exc:
                failures.append(str(exc))

            if auth_enabled:
                try:
                    state = load_auth_state()
                    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
                        json.dump(state, handle)
                        auth_state_path = handle.name
                    auth_page = browser.new_page(
                        storage_state=auth_state_path,
                        viewport={"width": 1440, "height": 1000},
                    )
                    auth_page.on("pageerror", lambda exc: page_errors.append(f"auth: {exc}\n{getattr(exc, \"stack\", \"\")}"))
                    check_authenticated_routes(auth_page)
                    auth_page.close()
                except Exception as exc:
                    failures.append(f"authenticated: {exc}")
        finally:
            browser.close()
            if auth_state_path:
                Path(auth_state_path).unlink(missing_ok=True)

    # Only browser/runtime JavaScript errors are fatal. Third-party console noise
    # is intentionally not promoted to a failure because public pages can load
    # optional external integrations without affecting RSL functionality.
    if page_errors:
        failures.extend(f"pageerror: {item}" for item in page_errors[:10])

    print(f"RSL live browser base URL: {BASE_URL}")
    print(f"Public routes checked: {len(PUBLIC_ROUTES)}")
    print(f"Protected routes checked: {len(PROTECTED_ROUTES)}")
    print(f"Authenticated routes checked: {6 if auth_enabled else 0}")
    print("Authenticated suite enabled:", "yes" if auth_enabled else "no")
    print(f"Console error messages observed: {len(console_errors)}")
    print(f"Browser page errors observed: {len(page_errors)}")

    if failures:
        print("LIVE E2E FAILED")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("LIVE E2E PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
