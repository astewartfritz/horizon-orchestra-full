"""Browser Agent — autonomous web navigation with DOM extraction and action planning.

The agent receives a high-level task ("find pricing for Notion"), navigates
the web autonomously, extracts structured data, and returns results. Uses
the LLM to decide what to click, where to navigate, and when to stop.

This is Horizon Prince's browser automation engine — but with persistent
sessions, multi-tab support, and a plan-act-observe loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .engine import BrowserEngine, BrowserPool, PageHandle

__all__ = ["BrowserAgent", "BrowseResult", "BrowseConfig"]

log = logging.getLogger("orchestra.browser.agent")


@dataclass
class BrowseConfig:
    max_steps: int = 30
    max_tokens: int = 4096
    screenshot_on_step: bool = False
    extract_links: bool = True
    extract_text: bool = True
    temperature: float = 0.3


@dataclass
class BrowseResult:
    """Result from an autonomous browsing session."""
    content: str = ""
    extracted_data: dict[str, Any] = field(default_factory=dict)
    pages_visited: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    steps_taken: int = 0
    duration: float = 0.0
    success: bool = True
    error: str = ""


# DOM simplification prompt
DOM_EXTRACT_JS = """
(() => {
    const elements = [];
    const interactable = document.querySelectorAll(
        'a, button, input, select, textarea, [role="button"], [onclick], [tabindex]'
    );
    interactable.forEach((el, i) => {
        if (i > 100) return;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        const tag = el.tagName.toLowerCase();
        const text = (el.textContent || '').trim().slice(0, 80);
        const href = el.href || '';
        const type = el.type || '';
        const placeholder = el.placeholder || '';
        const ariaLabel = el.getAttribute('aria-label') || '';
        const selector = tag +
            (el.id ? '#' + el.id : '') +
            (el.className ? '.' + el.className.split(' ')[0] : '');
        elements.push({
            index: i, tag, text, href: href.slice(0, 200),
            type, placeholder, ariaLabel, selector
        });
    });
    const title = document.title;
    const url = window.location.href;
    const bodyText = document.body?.innerText?.slice(0, 5000) || '';
    return { title, url, bodyText, elements };
})()
"""

AGENT_SYSTEM = """\
You are a browser navigation agent in Horizon Orchestra. You control a
Chromium browser to complete the user's task.

At each step you see the page's title, URL, visible text, and a list
of interactive elements (links, buttons, inputs). Decide what to do next.

Available actions (respond with JSON):
{
  "action": "click",     "selector": "CSS selector or element index"
}
{
  "action": "fill",      "selector": "input selector", "value": "text to type"
}
{
  "action": "navigate",  "url": "https://..."
}
{
  "action": "scroll",    "direction": "down" or "up"
}
{
  "action": "extract",   "description": "what data to extract from this page"
}
{
  "action": "done",      "result": "final answer or extracted data"
}

Rules:
- Navigate efficiently. Don't revisit pages.
- Extract the specific data the user asked for.
- If you can't find what you need, try a different approach.
- Call "done" when you have the answer or when you're stuck.
"""


class BrowserAgent:
    """Autonomous browser agent powered by LLM decision-making."""

    def __init__(
        self,
        pool: BrowserPool | None = None,
        router: Any = None,
        config: BrowseConfig | None = None,
    ) -> None:
        self.pool = pool
        self.router = router
        self.config = config or BrowseConfig()

    async def browse(
        self,
        task: str,
        start_url: str = "",
        model: str = "kimi-k2.5",
    ) -> BrowseResult:
        """Execute an autonomous browsing task."""
        t0 = time.monotonic()
        result = BrowseResult()

        if not self.pool:
            self.pool = BrowserPool()

        engine = await self.pool.acquire()
        page_handle = await engine.new_page(start_url or "https://www.google.com")
        result.pages_visited.append(page_handle.url)

        try:
            messages = [
                {"role": "system", "content": AGENT_SYSTEM},
                {"role": "user", "content": f"Task: {task}"},
            ]

            for step in range(self.config.max_steps):
                # Observe: get page state
                page_state = await self._observe(engine, page_handle)
                messages.append({
                    "role": "user",
                    "content": f"[Step {step + 1}] Current page:\n{json.dumps(page_state, indent=2)[:6000]}",
                })

                # Think: ask LLM what to do
                action = await self._think(messages, model)
                if not action:
                    result.error = "LLM returned no action"
                    break

                messages.append({
                    "role": "assistant",
                    "content": json.dumps(action),
                })

                # Act: execute the action
                if action.get("action") == "done":
                    result.content = action.get("result", "")
                    result.extracted_data = action.get("data", {})
                    result.steps_taken = step + 1
                    break

                act_result = await self._act(engine, page_handle, action)
                messages.append({
                    "role": "user",
                    "content": f"Action result: {json.dumps(act_result)[:2000]}",
                })

                # Track visited pages
                current_url = page_handle.url
                if current_url and current_url not in result.pages_visited:
                    result.pages_visited.append(current_url)

                # Screenshot if configured
                if self.config.screenshot_on_step:
                    ss = await engine.execute_on_page(
                        page_handle.id, "screenshot",
                        path=f"/tmp/horizon_workspace/browse_step_{step}.png",
                    )
                    if "path" in ss:
                        result.screenshots.append(ss["path"])

                result.steps_taken = step + 1

        except Exception as exc:
            result.error = str(exc)
            result.success = False
            log.error("Browser agent error: %s", exc)
        finally:
            await engine.close_page(page_handle.id)
            result.duration = round(time.monotonic() - t0, 2)

        return result

    async def _observe(self, engine: BrowserEngine, handle: PageHandle) -> dict[str, Any]:
        """Extract the current page state for the LLM."""
        page = handle._page
        if not page:
            return {"error": "Page closed"}

        try:
            dom_data = await page.evaluate(DOM_EXTRACT_JS)
            handle.url = dom_data.get("url", handle.url)
            handle.title = dom_data.get("title", handle.title)

            # Simplify for the LLM
            elements = dom_data.get("elements", [])[:50]
            simplified = []
            for el in elements:
                desc = f"[{el['index']}] <{el['tag']}>"
                if el.get("text"):
                    desc += f" \"{el['text'][:60]}\""
                if el.get("href"):
                    desc += f" → {el['href'][:100]}"
                if el.get("placeholder"):
                    desc += f" (placeholder: {el['placeholder']})"
                simplified.append(desc)

            return {
                "title": dom_data.get("title", ""),
                "url": dom_data.get("url", ""),
                "text_preview": dom_data.get("bodyText", "")[:3000],
                "interactive_elements": simplified,
            }
        except Exception as exc:
            return {"error": str(exc), "url": handle.url}

    async def _think(self, messages: list[dict], model: str) -> dict[str, Any] | None:
        """Ask the LLM to decide the next action."""
        if not self.router:
            return {"action": "done", "result": "No router configured"}

        try:
            client, model_id = self.router.get_client(model)
            resp = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            content = resp.choices[0].message.content or ""
            return json.loads(content)
        except Exception as exc:
            log.warning("Browser agent think failed: %s", exc)
            return None

    async def _act(self, engine: BrowserEngine, handle: PageHandle, action: dict) -> dict[str, Any]:
        """Execute a browser action."""
        act_type = action.get("action", "")

        if act_type == "navigate":
            return await engine.navigate(handle.id, action.get("url", ""))

        elif act_type == "click":
            selector = action.get("selector", "")
            # Support index-based selection: "[3]" → click 3rd interactable
            if selector.startswith("[") and selector.endswith("]"):
                try:
                    idx = int(selector.strip("[]"))
                    return await engine.execute_on_page(
                        handle.id, "evaluate",
                        expression=f"""
                            (() => {{
                                const els = document.querySelectorAll('a, button, input, [role="button"]');
                                if (els[{idx}]) {{ els[{idx}].click(); return 'clicked index {idx}'; }}
                                return 'element not found';
                            }})()
                        """,
                    )
                except ValueError:
                                        import logging as _log; _log.getLogger('browser.agent').debug('Suppressed exception', exc_info=True)
            return await engine.execute_on_page(handle.id, "click", selector=selector)

        elif act_type == "fill":
            return await engine.execute_on_page(
                handle.id, "fill",
                selector=action.get("selector", ""),
                value=action.get("value", ""),
            )

        elif act_type == "scroll":
            pixels = 500 if action.get("direction") == "down" else -500
            return await engine.execute_on_page(handle.id, "scroll", pixels=pixels)

        elif act_type == "extract":
            return await engine.execute_on_page(handle.id, "text")

        return {"error": f"Unknown action: {act_type}"}
