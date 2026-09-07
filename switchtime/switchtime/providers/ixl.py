"""IXL lesson provider, driven through a headless browser.

IXL has no API and no webhooks, so the only way in is to be a signed-in browser.
Sessions are persisted per kid so the usual poll is a page load rather than a
fresh login, which keeps the traffic close to what a parent checking the
Analytics tab would generate.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..config import Config, IXLConfig, KidConfig
from .base import Lesson, ProviderError, ProviderResult
from .ixl_extract import extract_lessons

_LOG = logging.getLogger(__name__)

#: Only responses from these hosts are considered; avoids hoovering up adverts
#: and third-party telemetry that happen to be JSON.
_ALLOWED_HOST_HINT = "ixl.com"
_MAX_PAYLOAD_BYTES = 4_000_000


class IXLProvider:
    """Reads finished skills for each configured kid.

    One browser is shared; each kid gets their own context so their IXL session
    cookies never mix.
    """

    name = "ixl"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._ixl: IXLConfig = config.ixl
        self._playwright: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()
        # The ledger books everything in the configured timezone; day strings
        # are part of every lesson ref, so the scraper must agree with it
        # rather than following whatever the host clock is set to.
        self._tz = ZoneInfo(config.server.timezone)
        self._state_dir = Path(self._ixl.storage_state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self.last_error: str | None = None

    # ----- browser lifecycle -------------------------------------------

    async def _ensure_browser(self) -> Any:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - depends on install
            raise ProviderError(
                "playwright is not installed. Run: pip install playwright && playwright install chromium"
            ) from exc
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._ixl.headless)
        return self._browser

    async def close(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            finally:
                self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            finally:
                self._playwright = None

    def _state_path(self, kid_id: str) -> Path:
        return self._state_dir / f"{kid_id}.json"

    # ----- the actual scrape --------------------------------------------

    async def fetch(self, kid_id: str) -> ProviderResult:
        kid = self._config.kid(kid_id)
        if not kid.ixl_ready:
            return ProviderResult(
                ok=False,
                diagnostics=[f"No IXL credentials configured for {kid.name}"],
            )
        # Playwright contexts are cheap but the browser is not; serialise so a
        # forced sync and the background poll cannot launch two at once.
        async with self._lock:
            return await self._fetch_locked(kid)

    async def _fetch_locked(self, kid: KidConfig, *, dump_to: Path | None = None) -> ProviderResult:
        result = ProviderResult()
        payloads: list[Any] = []
        browser = await self._ensure_browser()

        state_path = self._state_path(kid.id)
        context_args: dict[str, Any] = {
            "locale": "en-GB",
            "viewport": {"width": 1280, "height": 900},
        }
        if state_path.exists():
            context_args["storage_state"] = str(state_path)

        context = await browser.new_context(**context_args)
        context.set_default_timeout(self._ixl.nav_timeout_ms)
        page = await context.new_page()

        async def on_response(response: Any) -> None:
            url = response.url
            if _ALLOWED_HOST_HINT not in url:
                return
            ctype = (response.headers or {}).get("content-type", "")
            if "json" not in ctype.lower():
                return
            try:
                body = await response.body()
            except Exception:  # noqa: BLE001 - response may already be gone
                return
            if len(body) > _MAX_PAYLOAD_BYTES:
                return
            try:
                payloads.append(json.loads(body))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return

        # Playwright hands responses to a sync callback, so each read runs as its
        # own task. Hold a reference: an un-awaited task can be garbage-collected
        # mid-flight, which would silently lose the payload it was reading.
        handlers: set[asyncio.Task] = set()

        def capture(response: Any) -> None:
            task = asyncio.ensure_future(on_response(response))
            handlers.add(task)
            task.add_done_callback(handlers.discard)

        page.on("response", capture)

        try:
            signed_in = await self._ensure_signed_in(page, kid, result, dump_to)
            if dump_to is not None:
                await self._capture(page, dump_to, kid.id, "1-after-signin")
                result.note(f"after sign-in, the browser was at {page.url}")
            if not signed_in:
                result.ok = False
                return result

            for index, url in enumerate(self._ixl.report_urls, start=2):
                try:
                    await page.goto(url, wait_until="networkidle")
                except Exception as exc:  # noqa: BLE001 - one bad report is survivable
                    result.note(f"{url} did not load: {type(exc).__name__}")
                    continue
                # Reports lazy-load their tables after the shell paints.
                await page.wait_for_timeout(2500)
                if dump_to is not None:
                    await self._capture(page, dump_to, kid.id, f"{index}-report")
                    result.note(f"{url} settled at {page.url}")

            # Let any response still being read finish before extracting.
            if handlers:
                await asyncio.wait(set(handlers), timeout=10)

            await context.storage_state(path=str(state_path))

            now = datetime.now(self._tz)
            today = now.date().isoformat()
            since = (now - timedelta(days=3)).date().isoformat()
            lessons = extract_lessons(
                payloads,
                today=today,
                min_smartscore=self._ixl.min_smartscore,
                since_day=since,
            )
            # A last resort, and the JSON-free case is exactly when it is needed:
            # do not make it conditional on having seen any JSON at all.
            if not lessons:
                lessons = await self._fallback_from_dom(page, today, result)

            result.lessons = lessons
            result.note(f"{len(payloads)} JSON payloads seen, {len(lessons)} lessons matched")
            if dump_to is not None:
                self._dump(dump_to, kid.id, payloads)
                result.note(f"payloads written to {dump_to}")
            self.last_error = None
            return result
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced to the parent view
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise ProviderError(self.last_error) from exc
        finally:
            await context.close()

    async def _ensure_signed_in(
        self, page: Any, kid: KidConfig, result: ProviderResult, dump_to: Path | None = None
    ) -> bool:
        """Reuse the stored session if it still works, otherwise sign in."""
        await page.goto(self._ixl.signin_url, wait_until="domcontentloaded")
        if "signin" not in page.url.lower():
            # Stored cookies were still good, but they may have expired back
            # to the family level rather than this child.
            return await self._select_profile(page, kid, result, dump_to)

        secret = kid.ixl_password or ""
        if not secret:
            # Submitting an empty box only produces IXL's own validation error,
            # which reads like a rejected password rather than a missing one.
            name = kid.ixl_password_env_name or "the ixl_password_env variable"
            result.note(
                f"No IXL password for {kid.name}: {name} is empty or unset in .env.local. "
                "Nothing else here can work until that is set."
            )
            if dump_to is not None:
                await self._capture(page, dump_to, kid.id, "0-no-password")
            return False
        result.note(f"signing in as {kid.ixl_username!r} with a {len(secret)}-character password")

        try:
            # Find the fields by role rather than by id. IXL's markup is not a
            # contract, but "the password box, and the text box next to it" is
            # stable in a way that a generated element id is not. Both must be
            # visible: the page carries hidden inputs that fill() would happily
            # accept and the form would then ignore.
            username = page.locator(
                "input[type='text']:visible, input[type='email']:visible, "
                "input[name*='user' i]:visible"
            ).first
            password = page.locator("input[type='password']:visible").first
            await password.wait_for(state="visible", timeout=self._ixl.nav_timeout_ms)

            await username.click()
            await username.fill(kid.ixl_username or "")
            await password.click()
            await password.fill(secret)

            # Confirm both fields actually hold what we typed. A value that did
            # not stick is the difference between "IXL refused us" and "we
            # submitted an empty box", and those need opposite fixes.
            typed_user = await username.input_value()
            typed_pass = await password.input_value()
            result.note(
                f"form now holds username={typed_user!r} and a "
                f"{len(typed_pass)}-character password"
            )
            if len(typed_pass) != len(secret):
                result.note(
                    "The password did not stick in the form. That is a page-structure "
                    "problem, not a wrong password."
                )
            if dump_to is not None:
                await self._capture(page, dump_to, kid.id, "0-before-submit")

            # Prefer the real button: some forms bind validation to the click
            # rather than to the form's submit event.
            button = page.locator(
                "button[type='submit']:visible, input[type='submit']:visible, "
                "button:has-text('Sign in'):visible"
            ).first
            if await button.count():
                await button.click()
            else:
                await password.press("Enter")
            await page.wait_for_load_state("networkidle")
        except Exception as exc:  # noqa: BLE001
            result.note(
                "Could not fill the sign-in form "
                f"({type(exc).__name__}). Run `switchtime probe {kid.id}` and look at "
                "the saved screenshot to see what the page actually showed."
            )
            return False

        # A family account answers a correct sign-in by opening a "Who are you?"
        # chooser *over* the sign-in page, leaving the URL on /signin. Judging
        # success by the URL alone therefore calls a working sign-in a failure,
        # so look for the chooser before believing the address bar.
        chooser = await self._wait_for_chooser(page, kid)
        if chooser is not None:
            result.note("Signed in; the profile chooser appeared.")
            return await self._select_profile(page, kid, result, dump_to, chooser)

        if "signin" not in page.url.lower():
            return await self._select_profile(page, kid, result, dump_to)

        # Still on the sign-in page with no chooser. A wrong password is the
        # obvious reading; a school account signing in through Google or Clever
        # is the other, and no password on this page would ever work for it.
        sso = await self._single_sign_on_hints(page)
        result.note(f"Still on the sign-in page after submitting as {kid.ixl_username!r}.")
        if sso:
            result.note(
                f"This page offers {', '.join(sso)} sign-in. If his IXL comes through "
                "school, there is no password to use here — see the README on school "
                "accounts."
            )
        else:
            result.note("Check the username and password, then try again.")
        return False

    @staticmethod
    async def _secret_word_input(page: Any) -> Any:
        """The per-child "secret word" box, or None if it is not on screen.

        IXL renders it as an ordinary text input, so selecting by type finds the
        username box on the sign-in form behind the modal instead. These
        strategies anchor on the prompt text itself, in decreasing precision.
        """
        strategies = (
            # An actual password field, if IXL ever makes it one.
            "input[type='password']:visible",
            # The first input after the words "secret word", case-insensitive.
            "xpath=//*[contains(translate(normalize-space(text()),"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
            "'secret word')]/following::input[1]",
            # A labelled box, however it is worded.
            "input[placeholder*='secret' i]:visible",
            "input[aria-label*='secret' i]:visible",
        )
        for selector in strategies:
            try:
                candidate = page.locator(selector).first
                if await candidate.count() and await candidate.is_visible():
                    return candidate
            except Exception:  # noqa: BLE001 - try the next strategy
                continue
        return None

    async def _wait_for_chooser(self, page: Any, kid: KidConfig, timeout_ms: int = 8000) -> Any:
        """The chooser entry for this child, once it appears. None if it does not.

        The names sit under avatar images and are not necessarily links or
        buttons, so match the text itself and let Playwright click through to
        whatever handles it.
        """
        if not kid.ixl_profile:
            return None
        try:
            entry = page.get_by_text(kid.ixl_profile, exact=True).first
            await entry.wait_for(state="visible", timeout=timeout_ms)
        except Exception:  # noqa: BLE001 - absence is a normal answer here
            return None
        return entry

    async def _select_profile(
        self,
        page: Any,
        kid: KidConfig,
        result: ProviderResult,
        dump_to: Path | None,
        entry: Any = None,
    ) -> bool:
        """Pick this child on a family account, and enter their own password.

        A family subscription signs in once and then shows a list of children;
        choosing one asks for a short password of their own. Without this the
        session stays at the family level and the analytics belong to whoever
        was last selected, which is worse than failing.
        """
        if not kid.ixl_profile:
            return True

        try:
            candidate = entry if entry is not None else await self._wait_for_chooser(
                page, kid, timeout_ms=3000
            )
            if candidate is None:
                result.note(
                    f"No profile chooser offering {kid.ixl_profile!r} — assuming the "
                    "session is already on the right child."
                )
                return True

            await candidate.click()
            await page.wait_for_timeout(1500)
            if dump_to is not None:
                await self._capture(page, dump_to, kid.id, "0b-profile-password")

            # IXL calls this a "secret word" and renders it as a plain text box,
            # not a password field, so it has to be found by what it sits next
            # to rather than by input type.
            prompt = await self._secret_word_input(page)
            if prompt is not None:
                secret = kid.ixl_profile_password or ""
                if not secret:
                    name = kid.ixl_profile_password_env_name or "ixl_profile_password_env"
                    result.note(
                        f"{kid.ixl_profile} is asked for a secret word but none is "
                        f"configured. Run `switchtime set-secret {name}`."
                    )
                    return False
                await prompt.click()
                await prompt.fill(secret)
                typed = await prompt.input_value()
                result.note(
                    f"secret word box holds {len(typed)} characters "
                    f"(configured: {len(secret)})"
                )
                # The arrow beside the box carries no text, so Enter is the
                # reliable way in; a named button is tried only as a fallback.
                await prompt.press("Enter")
                await page.wait_for_timeout(1500)
                if await self._secret_word_input(page) is not None:
                    button = page.locator(
                        "button[type='submit']:visible, input[type='submit']:visible"
                    ).first
                    if await button.count():
                        await button.click()
                await page.wait_for_load_state("networkidle")
            else:
                result.note(f"Chose {kid.ixl_profile}; no password was asked for.")
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            result.note(f"Could not select the {kid.ixl_profile!r} profile: {type(exc).__name__}")
            return False

        if dump_to is not None:
            await self._capture(page, dump_to, kid.id, "0c-after-profile")
        return True

    @staticmethod
    async def _single_sign_on_hints(page: Any) -> list[str]:
        """Names of any third-party sign-in options offered on the page."""
        try:
            # Only the text of things you could click. Reading page source instead
            # matches the analytics script every site loads, which made this
            # report Google sign-in on every page it ever saw.
            labels = await page.eval_on_selector_all(
                "a, button, [role='button']",
                "els => els.map(e => (e.innerText || '').trim()).filter(Boolean)",
            )
        except Exception:  # noqa: BLE001 - a diagnostic must not raise
            return []
        joined = " ".join(labels).lower()
        return [
            name
            for name, needle in (
                ("Google", "google"),
                ("Clever", "clever"),
                ("Microsoft", "microsoft"),
                ("ClassLink", "classlink"),
            )
            if needle in joined
        ]

    async def _fallback_from_dom(self, page: Any, today: str, result: ProviderResult) -> list[Lesson]:
        """Last resort: read the rendered report table instead of its JSON."""
        try:
            rows = await page.eval_on_selector_all(
                "table tr",
                "els => els.map(e => Array.from(e.querySelectorAll('td,th')).map(c => c.innerText.trim()))",
            )
        except Exception:  # noqa: BLE001
            return []
        objects = [
            {"name": row[0], "score": row[-1], "date": today}
            for row in rows
            if isinstance(row, list) and len(row) >= 2 and row[0]
        ]
        lessons = extract_lessons(
            objects, today=today, min_smartscore=self._ixl.min_smartscore
        )
        if lessons:
            result.note("Matched from the rendered table rather than JSON.")
        return lessons

    @staticmethod
    async def _capture(page: Any, out_dir: Path, kid_id: str, label: str) -> None:
        """Save a screenshot and the rendered HTML.

        The scraper has to work against an account nobody but its owner can see,
        so when it fails the only way to say why is to show the page it was
        looking at.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = out_dir / f"{kid_id}-{label}"
        try:
            await page.screenshot(path=f"{stem}.png", full_page=True)
        except Exception:  # noqa: BLE001 - a diagnostic must not raise
            pass
        try:
            (stem.with_suffix(".html")).write_text(await page.content(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    # ----- diagnostics ---------------------------------------------------

    async def probe(self, kid_id: str, out_dir: Path) -> ProviderResult:
        """Run a fetch and keep every payload, so selectors can be tuned by eye."""
        kid = self._config.kid(kid_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        if not kid.ixl_username:
            return ProviderResult(
                ok=False, diagnostics=[f"No ixl_username configured for {kid.name}."]
            )
        async with self._lock:
            return await self._fetch_locked(kid, dump_to=out_dir)

    @staticmethod
    def _dump(out_dir: Path, kid_id: str, payloads: list[Any]) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = out_dir / f"{kid_id}-{stamp}.json"
        target.write_text(json.dumps(payloads, indent=2)[:20_000_000], encoding="utf-8")
        _LOG.info("wrote %s payloads to %s", len(payloads), target)
