"""Tests for BrowserConnector, BrowserSession, BrowserConfig, and PageState.

All tests run offline — every Playwright call is mocked.
"""

from __future__ import annotations

import asyncio
import base64
import sys
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run(coro):
    """Run an async coroutine in the current event loop (test helper)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# BrowserConfig tests
# ---------------------------------------------------------------------------

class BrowserConfigTests(unittest.TestCase):

    def _get_config(self):
        from orchestra.browser_connector import BrowserConfig
        return BrowserConfig

    def test_default_config(self):
        BrowserConfig = self._get_config()
        cfg = BrowserConfig()
        self.assertEqual(cfg.mode, "local")
        self.assertTrue(cfg.headless)
        self.assertTrue(cfg.stealth)
        self.assertTrue(cfg.block_ads)
        self.assertEqual(cfg.viewport_width, 1280)
        self.assertEqual(cfg.viewport_height, 720)
        self.assertEqual(cfg.locale, "en-US")

    def test_custom_config(self):
        BrowserConfig = self._get_config()
        cfg = BrowserConfig(
            mode="remote_cdp",
            headless=False,
            remote_url="ws://localhost:9222",
            stealth=False,
            timeout=60_000,
        )
        self.assertEqual(cfg.mode, "remote_cdp")
        self.assertFalse(cfg.headless)
        self.assertEqual(cfg.remote_url, "ws://localhost:9222")
        self.assertFalse(cfg.stealth)
        self.assertEqual(cfg.timeout, 60_000)

    def test_block_ads_default(self):
        BrowserConfig = self._get_config()
        cfg = BrowserConfig()
        self.assertTrue(cfg.block_ads)

    def test_block_resources_default(self):
        BrowserConfig = self._get_config()
        cfg = BrowserConfig()
        self.assertEqual(cfg.block_resources, ["font"])

    def test_timeout_default(self):
        BrowserConfig = self._get_config()
        cfg = BrowserConfig()
        self.assertEqual(cfg.timeout, 30_000)

    def test_stealth_default(self):
        BrowserConfig = self._get_config()
        cfg = BrowserConfig()
        self.assertTrue(cfg.stealth)


# ---------------------------------------------------------------------------
# PageState / ClickResult / ExtractResult tests
# ---------------------------------------------------------------------------

class PageStateTests(unittest.TestCase):

    def test_page_state_defaults(self):
        from orchestra.browser_connector import PageState
        state = PageState()
        self.assertEqual(state.url, "")
        self.assertEqual(state.title, "")
        self.assertEqual(state.content_length, 0)
        self.assertEqual(state.tab_id, "")
        self.assertEqual(state.load_state, "")

    def test_click_result_defaults(self):
        from orchestra.browser_connector import ClickResult
        result = ClickResult(success=True, selector="#btn")
        self.assertTrue(result.success)
        self.assertEqual(result.selector, "#btn")
        self.assertEqual(result.element_text, "")
        self.assertEqual(result.new_url, "")

    def test_extract_result_defaults(self):
        from orchestra.browser_connector import ExtractResult
        result = ExtractResult(success=True, selector="a")
        self.assertTrue(result.success)
        self.assertEqual(result.count, 0)
        self.assertEqual(result.items, [])


# ---------------------------------------------------------------------------
# BrowserSession tests — mock playwright
# ---------------------------------------------------------------------------

def _make_playwright_mocks():
    """Return a (playwright_mock, async_playwright_fn) tuple for patching."""
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html><body>Hello</body></html>")
    mock_page.evaluate = AsyncMock(return_value="visible text")
    mock_page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.url = "https://example.com"
    mock_page.locator = MagicMock()
    mock_locator = MagicMock()
    mock_locator.first = MagicMock()
    mock_locator.first.click = AsyncMock()
    mock_locator.first.text_content = AsyncMock(return_value="Submit")
    mock_locator.first.type = AsyncMock()
    mock_locator.first.fill = AsyncMock()
    mock_page.locator.return_value = mock_locator

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.add_init_script = AsyncMock()
    mock_context.route = AsyncMock()
    mock_context.on = MagicMock()
    mock_context.add_cookies = AsyncMock()
    mock_context.cookies = AsyncMock(return_value=[{"name": "session", "value": "abc"}])
    mock_context.clear_cookies = AsyncMock()
    mock_context.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)
    mock_chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium = mock_chromium
    mock_pw_instance.stop = AsyncMock()

    mock_pw_ctx = AsyncMock()
    mock_pw_ctx.__aenter__ = AsyncMock(return_value=mock_pw_instance)
    mock_pw_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pw_ctx.start = AsyncMock(return_value=mock_pw_instance)

    async def fake_async_playwright():
        return mock_pw_ctx

    # Make async_playwright() callable that returns the context manager object
    # BrowserSession calls: self._playwright = await async_playwright().start()
    mock_async_playwright = MagicMock()
    mock_ap_result = MagicMock()
    mock_ap_result.start = AsyncMock(return_value=mock_pw_instance)
    mock_async_playwright.return_value = mock_ap_result

    return {
        "mock_page": mock_page,
        "mock_context": mock_context,
        "mock_browser": mock_browser,
        "mock_chromium": mock_chromium,
        "mock_pw_instance": mock_pw_instance,
        "async_playwright": mock_async_playwright,
    }


class BrowserSessionTests(unittest.IsolatedAsyncioTestCase):

    def test_session_init_no_playwright(self):
        """BrowserSession.start() raises RuntimeError when playwright is missing."""
        from orchestra.browser_connector import BrowserSession
        session = BrowserSession()
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", False):
            with self.assertRaises(RuntimeError) as ctx:
                run(session.start())
            self.assertIn("playwright", str(ctx.exception).lower())

    async def test_session_init_with_mock(self):
        """BrowserSession constructs correctly with mocked playwright."""
        mocks = _make_playwright_mocks()
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
        self.assertTrue(session.is_running)
        self.assertIsNotNone(session._page)
        await session.close()

    async def test_navigate_builds_correct_url(self):
        """navigate() calls page.goto with the URL and wait_until."""
        mocks = _make_playwright_mocks()
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
            await session.navigate("https://example.com", wait_until="load")
        mocks["mock_page"].goto.assert_called_once_with(
            "https://example.com",
            wait_until="load",
            timeout=30_000,
        )
        await session.close()

    async def test_get_content_calls_page_content(self):
        """get_content() calls page.content()."""
        mocks = _make_playwright_mocks()
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
            html = await session.get_content()
        self.assertIn("<html>", html)
        mocks["mock_page"].content.assert_called()
        await session.close()

    async def test_get_text_calls_evaluate(self):
        """get_text() calls page.evaluate with innerText expression."""
        mocks = _make_playwright_mocks()
        mocks["mock_page"].evaluate = AsyncMock(return_value="Hello World")
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
            text = await session.get_text()
        self.assertEqual(text, "Hello World")
        mocks["mock_page"].evaluate.assert_called_with("document.body.innerText")
        await session.close()

    async def test_screenshot_returns_bytes(self):
        """screenshot() returns raw bytes from page.screenshot()."""
        mocks = _make_playwright_mocks()
        expected_bytes = b"\x89PNG\r\n\x1a\n" + b"\xAB" * 50
        mocks["mock_page"].screenshot = AsyncMock(return_value=expected_bytes)
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
            data = await session.screenshot()
        self.assertEqual(data, expected_bytes)
        await session.close()

    async def test_click_calls_page_locator(self):
        """click() calls page.locator().first.click()."""
        mocks = _make_playwright_mocks()
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
            result = await session.click("#submit-btn")
        mocks["mock_page"].locator.assert_called_with("#submit-btn")
        self.assertTrue(result.success)
        await session.close()

    async def test_type_text_calls_locator_type(self):
        """type_text() calls locator.first.type()."""
        mocks = _make_playwright_mocks()
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
            ok = await session.type_text("#email", "user@example.com")
        self.assertTrue(ok)
        mocks["mock_page"].locator("#email").first.type.assert_called()
        await session.close()

    async def test_fill_calls_locator_fill(self):
        """fill() calls locator.first.fill()."""
        mocks = _make_playwright_mocks()
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
            ok = await session.fill("#password", "secret")
        self.assertTrue(ok)
        await session.close()

    async def test_evaluate_calls_page_evaluate(self):
        """evaluate() calls page.evaluate() with the given script."""
        mocks = _make_playwright_mocks()
        mocks["mock_page"].evaluate = AsyncMock(return_value=42)
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
            result = await session.evaluate("1 + 41")
        self.assertEqual(result, 42)
        mocks["mock_page"].evaluate.assert_called_with("1 + 41")
        await session.close()

    async def test_get_cookies_returns_list(self):
        """get_cookies() returns a list of cookie dicts."""
        mocks = _make_playwright_mocks()
        expected = [{"name": "session", "value": "abc123"}]
        mocks["mock_context"].cookies = AsyncMock(return_value=expected)
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
            cookies = await session.get_cookies()
        self.assertEqual(cookies, expected)
        await session.close()

    async def test_set_cookies_calls_add_cookies(self):
        """set_cookies() calls context.add_cookies() with provided list."""
        mocks = _make_playwright_mocks()
        from orchestra.browser_connector import BrowserSession, BrowserConfig
        cfg = BrowserConfig(stealth=False, block_ads=False, block_resources=[])
        session = BrowserSession(config=cfg)
        cookie_list = [{"name": "auth", "value": "token123", "url": "https://example.com"}]
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await session.start()
            await session.set_cookies(cookie_list)
        mocks["mock_context"].add_cookies.assert_called_once_with(cookie_list)
        await session.close()


# ---------------------------------------------------------------------------
# BrowserConnector tests
# ---------------------------------------------------------------------------

class BrowserConnectorTests(unittest.IsolatedAsyncioTestCase):

    def test_connector_name(self):
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        self.assertEqual(conn.name, "browser")

    def test_connector_not_connected_initially(self):
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        self.assertFalse(conn.connected)

    async def test_connect_local_mode_no_playwright(self):
        """connect() returns False and logs an error when playwright is missing."""
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", False):
            result = await conn.connect({"mode": "local"})
        self.assertFalse(result)
        self.assertFalse(conn.connected)

    async def test_connect_sets_connected(self):
        """connect() sets connected=True when playwright is available."""
        mocks = _make_playwright_mocks()
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            result = await conn.connect({"mode": "local", "stealth": "false", "block_ads": "false"})
        self.assertTrue(result)
        self.assertTrue(conn.connected)
        await conn.disconnect()

    async def test_execute_navigate(self):
        """execute('navigate') calls session.navigate and returns page state."""
        mocks = _make_playwright_mocks()
        mocks["mock_page"].goto = AsyncMock()
        mocks["mock_page"].title = AsyncMock(return_value="Example Domain")
        mocks["mock_page"].url = "https://example.com"
        mocks["mock_page"].content = AsyncMock(return_value="<html></html>")
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await conn.connect({"mode": "local", "stealth": "false", "block_ads": "false"})
            result = await conn.execute("navigate", {"url": "https://example.com"})
        self.assertIn("url", result)
        self.assertNotIn("error", result)
        await conn.disconnect()

    async def test_execute_get_content(self):
        """execute('get_content') returns html and length keys."""
        mocks = _make_playwright_mocks()
        mocks["mock_page"].content = AsyncMock(return_value="<html><body>Test</body></html>")
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await conn.connect({"mode": "local", "stealth": "false", "block_ads": "false"})
            result = await conn.execute("get_content", {})
        self.assertIn("html", result)
        self.assertIn("length", result)
        self.assertNotIn("error", result)
        await conn.disconnect()

    async def test_execute_screenshot_returns_base64(self):
        """execute('screenshot') base64-encodes the raw PNG bytes."""
        raw_bytes = b"\x89PNG\r\n\x1a\n" + b"\xCC" * 32
        mocks = _make_playwright_mocks()
        mocks["mock_page"].screenshot = AsyncMock(return_value=raw_bytes)
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await conn.connect({"mode": "local", "stealth": "false", "block_ads": "false"})
            result = await conn.execute("screenshot", {})
        self.assertIn("screenshot_base64", result)
        decoded = base64.b64decode(result["screenshot_base64"])
        self.assertEqual(decoded, raw_bytes)
        self.assertEqual(result["format"], "png")
        await conn.disconnect()

    async def test_execute_unknown_action(self):
        """execute() with an unknown action returns an error dict."""
        mocks = _make_playwright_mocks()
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await conn.connect({"mode": "local", "stealth": "false", "block_ads": "false"})
            result = await conn.execute("fly_to_the_moon", {})
        self.assertIn("error", result)
        await conn.disconnect()

    async def test_execute_when_not_connected(self):
        """execute() returns an error dict when the browser is not connected."""
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        result = await conn.execute("navigate", {"url": "https://example.com"})
        self.assertIn("error", result)
        self.assertFalse(conn.connected)

    async def test_disconnect_closes_session(self):
        """disconnect() closes the underlying BrowserSession."""
        mocks = _make_playwright_mocks()
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        with patch("orchestra.browser_connector.HAS_PLAYWRIGHT", True), \
             patch("orchestra.browser_connector.async_playwright", mocks["async_playwright"]):
            await conn.connect({"mode": "local", "stealth": "false", "block_ads": "false"})
            self.assertTrue(conn.connected)
            await conn.disconnect()
        # After disconnect the context should have been closed
        mocks["mock_context"].close.assert_called()


# ---------------------------------------------------------------------------
# Tool definitions tests
# ---------------------------------------------------------------------------

class ToolDefinitionsTests(unittest.TestCase):

    def _get_tools(self):
        from orchestra.browser_connector import BrowserConnector
        conn = BrowserConnector()
        return conn.get_tool_definitions()

    def test_get_tool_definitions_returns_list(self):
        tools = self._get_tools()
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 0)

    def test_browser_navigate_in_tools(self):
        tools = self._get_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn("browser_navigate", names)
        nav = next(t for t in tools if t["function"]["name"] == "browser_navigate")
        params = nav["function"]["parameters"]["properties"]
        self.assertIn("url", params)

    def test_browser_screenshot_in_tools(self):
        tools = self._get_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn("browser_screenshot", names)

    def test_all_tools_have_required_fields(self):
        tools = self._get_tools()
        for tool in tools:
            self.assertIn("type", tool, f"Tool missing 'type': {tool}")
            self.assertIn("function", tool, f"Tool missing 'function': {tool}")
            func = tool["function"]
            self.assertIn("name", func, f"Function missing 'name': {func}")
            self.assertIn("description", func, f"Function missing 'description': {func}")
            self.assertIn("parameters", func, f"Function missing 'parameters': {func}")


# ---------------------------------------------------------------------------
# New connectors from arch_e.py
# ---------------------------------------------------------------------------

class ArchEConnectorTests(unittest.TestCase):

    def test_notion_connector_not_connected_initially(self):
        from orchestra.arch_e import NotionConnector
        conn = NotionConnector()
        self.assertFalse(conn.connected)

    def test_linear_connector_not_connected_initially(self):
        from orchestra.arch_e import LinearConnector
        conn = LinearConnector()
        self.assertFalse(conn.connected)

    def test_jira_connector_not_connected_initially(self):
        from orchestra.arch_e import JiraConnector
        conn = JiraConnector()
        self.assertFalse(conn.connected)


if __name__ == "__main__":
    unittest.main()
