"""Browser automation tool for the agent — wraps ChromiumController as a Tool."""

from __future__ import annotations

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec
from orchestra.code_agent.browser.chromium import ChromiumController


class BrowserTool(Tool):
    """Browser automation tool that lets the agent control a real Chromium browser.

    Supports: navigation, clicking, form filling, screenshots, JavaScript execution,
    PDF generation, and text extraction. Runs headless by default.
    """

    spec = ToolSpec(
        name="browser",
        description="Control a Chromium browser: navigate to URLs, click elements, fill forms, take screenshots, execute JavaScript, extract page text, generate PDFs.",
        parameters={
            "action": {
                "type": "string",
                "enum": ["navigate", "click", "fill", "screenshot", "evaluate", "extract", "pdf"],
                "description": "Browser action to perform",
            },
            "url": {"type": "string", "description": "URL to navigate to (required for navigate action)", "default": ""},
            "selector": {"type": "string", "description": "CSS selector for click/fill actions", "default": ""},
            "value": {"type": "string", "description": "Value to fill in form field (required for fill action)", "default": ""},
            "script": {"type": "string", "description": "JavaScript code to execute (required for evaluate action)", "default": ""},
        },
    )

    def __init__(self):
        self._controller: ChromiumController | None = None

    async def _get_controller(self) -> ChromiumController:
        if self._controller is None:
            self._controller = ChromiumController(headless=True)
        return self._controller

    async def __call__(self, action: str = "navigate", url: str = "", selector: str = "",
                       value: str = "", script: str = "") -> ToolResult:
        ctrl = await self._get_controller()

        if action == "navigate":
            if not url:
                return ToolResult(error="URL required for navigate action")
            result = await ctrl.navigate(url)
            if result.success and result.data:
                text = await ctrl.extract_text()
                return ToolResult(output=f"Navigated to: {result.data.url}\nTitle: {result.data.title}\n\nPage text:\n{text[:3000]}")
            return ToolResult(error=result.error or "Navigation failed")

        elif action == "click":
            if not selector:
                return ToolResult(error="CSS selector required for click action")
            result = await ctrl.click(selector)
            if result.success:
                text = await ctrl.extract_text()
                return ToolResult(output=f"Clicked: {selector}\n\nPage text:\n{text[:2000]}")
            return ToolResult(error=result.error or "Click failed")

        elif action == "fill":
            if not selector or not value:
                return ToolResult(error="CSS selector and value required for fill action")
            result = await ctrl.fill(selector, value)
            if result.success:
                return ToolResult(output=f"Filled {selector} with: {value[:100]}")
            return ToolResult(error=result.error or "Fill failed")

        elif action == "screenshot":
            result = await ctrl.screenshot()
            if result.success and result.data:
                # Return metadata — the actual screenshot would be too large for text
                return ToolResult(output=f"Screenshot captured ({len(result.data.screenshot)} bytes base64)")
            return ToolResult(error=result.error or "Screenshot failed")

        elif action == "evaluate":
            if not script:
                return ToolResult(error="JavaScript code required for evaluate action")
            result = await ctrl.evaluate(script)
            if result.success and result.data:
                return ToolResult(output=f"Result: {result.data.content[:2000]}")
            return ToolResult(error=result.error or "Script execution failed")

        elif action == "extract":
            text = await ctrl.extract_text()
            return ToolResult(output=f"Page text:\n{text[:3000]}")

        elif action == "pdf":
            result = await ctrl.pdf()
            if result.success and result.data:
                return ToolResult(output=f"PDF saved: {result.data.content}")
            return ToolResult(error=result.error or "PDF generation failed")

        return ToolResult(error=f"Unknown action: {action}")
