"""DOM Interpreter — transforms raw page DOM into typed, LLM-friendly representations.

Frontier's DOM interpreter converts a live browser page into structured
objects that agents can reason about and act on.  The three-stage pipeline
(extract → prune → type) produces ``InteractableElement`` instances that
map directly to callable actions (click, type, select) rather than
brittle CSS selectors.

Two output formats are generated:
- **Structured**: ``list[InteractableElement]`` for programmatic use.
- **Text**: Markdown table for injection into LLM system prompts.

Usage::

    from orchestra.frontier.dom_interpreter import DOMInterpreter
    interp = DOMInterpreter()
    snapshot = await interp.interpret(page_handle)
    print(interp.to_markdown_table(snapshot.elements))
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

try:
    from playwright.async_api import Page as _PlaywrightPage  # noqa: F401

    _HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    _HAS_PLAYWRIGHT = False

__all__ = [
    "DOMInterpreter",
    "DOMSnapshot",
    "DOMNode",
    "InteractableElement",
    "DOMAction",
    "FormGroup",
    "InterpreterConfig",
]

log = logging.getLogger("orchestra.frontier.dom_interpreter")

# ---------------------------------------------------------------------------
# JavaScript extraction snippets — executed inside the browser page
# ---------------------------------------------------------------------------

_EXTRACT_DOM_JS = """
(() => {
    const nodes = [];
    let nodeId = 0;
    const MAX_NODES = 5000;
    const MAX_DEPTH = __MAX_DEPTH__;

    const PRUNED_TAGS = new Set([
        'script', 'style', 'noscript', 'svg', 'path', 'meta', 'link',
        'br', 'hr', 'wbr', 'template', 'slot', 'base', 'col',
    ]);

    const INTERACTABLE_TAGS = new Set([
        'a', 'button', 'input', 'select', 'textarea', 'option',
        'details', 'summary', 'dialog', 'label',
    ]);

    const INTERACTABLE_ROLES = new Set([
        'button', 'link', 'menuitem', 'option', 'radio', 'switch',
        'tab', 'checkbox', 'textbox', 'combobox', 'searchbox',
        'spinbutton', 'slider', 'menuitemcheckbox', 'menuitemradio',
    ]);

    function walk(el, depth, parentId) {
        if (nodeId >= MAX_NODES || depth > MAX_DEPTH) return;
        const tag = (el.tagName || '').toLowerCase();
        if (PRUNED_TAGS.has(tag)) return;

        const currentId = nodeId++;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const visible = (
            style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            style.opacity !== '0' &&
            rect.width > 0 &&
            rect.height > 0
        );

        const role = el.getAttribute('role') || '';
        const ariaLabel = el.getAttribute('aria-label') || '';
        const placeholder = el.placeholder || '';
        const isInteractable = (
            INTERACTABLE_TAGS.has(tag) ||
            INTERACTABLE_ROLES.has(role) ||
            el.hasAttribute('onclick') ||
            el.hasAttribute('tabindex') ||
            el.contentEditable === 'true'
        );

        const textContent = (el.childNodes.length <= 3)
            ? Array.from(el.childNodes)
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .join(' ')
                .slice(0, 200)
            : '';

        const attrs = {};
        if (el.id) attrs.id = el.id;
        if (el.className && typeof el.className === 'string') {
            attrs.class = el.className.slice(0, 120);
        }
        if (el.href) attrs.href = el.href.slice(0, 500);
        if (el.type) attrs.type = el.type;
        if (el.name) attrs.name = el.name;
        if (el.value !== undefined && el.value !== '') {
            attrs.value = String(el.value).slice(0, 200);
        }

        const childIds = [];
        for (const child of el.children) {
            const cid = nodeId;
            walk(child, depth + 1, currentId);
            if (nodeId > cid) childIds.push(cid);
        }

        nodes.push({
            node_id: currentId,
            tag: tag,
            role: role,
            label: ariaLabel || placeholder || textContent,
            value: el.value !== undefined ? String(el.value).slice(0, 200) : '',
            attributes: attrs,
            bounding_box: [
                Math.round(rect.x), Math.round(rect.y),
                Math.round(rect.width), Math.round(rect.height),
            ],
            visible: visible,
            interactable: isInteractable,
            children: childIds,
            parent: parentId,
            depth: depth,
        });
    }

    walk(document.body, 0, null);
    return {
        url: window.location.href,
        title: document.title || '',
        node_count: document.querySelectorAll('*').length,
        nodes: nodes,
    };
})()
"""

_EXTRACT_ACCESSIBILITY_JS = """
(() => {
    const tree = [];
    const MAX_ITEMS = 2000;
    let count = 0;

    function walkA11y(el, depth) {
        if (count >= MAX_ITEMS || depth > 20) return;
        const role = el.getAttribute('role') || el.tagName.toLowerCase();
        const ariaLabel = el.getAttribute('aria-label') || '';
        const ariaDescribedBy = el.getAttribute('aria-describedby') || '';
        const ariaExpanded = el.getAttribute('aria-expanded');
        const ariaChecked = el.getAttribute('aria-checked');
        const ariaSelected = el.getAttribute('aria-selected');
        const ariaDisabled = el.getAttribute('aria-disabled');
        const ariaHidden = el.getAttribute('aria-hidden');

        if (ariaHidden === 'true') return;

        const text = (el.childNodes.length <= 3)
            ? Array.from(el.childNodes)
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .join(' ')
                .slice(0, 200)
            : '';

        const item = {
            role: role,
            name: ariaLabel || text,
            depth: depth,
        };
        if (ariaExpanded !== null) item.expanded = ariaExpanded === 'true';
        if (ariaChecked !== null) item.checked = ariaChecked === 'true';
        if (ariaSelected !== null) item.selected = ariaSelected === 'true';
        if (ariaDisabled !== null) item.disabled = ariaDisabled === 'true';
        if (ariaDescribedBy) item.describedby = ariaDescribedBy;

        tree.push(item);
        count++;

        for (const child of el.children) {
            walkA11y(child, depth + 1);
        }
    }

    walkA11y(document.body, 0);
    return tree;
})()
"""

_EXTRACT_FORMS_JS = """
(() => {
    const forms = [];
    document.querySelectorAll('form').forEach((form, fi) => {
        if (fi >= 20) return;
        const fields = [];
        const inputs = form.querySelectorAll('input, select, textarea, button');
        inputs.forEach((inp, ii) => {
            if (ii >= 50) return;
            const tag = inp.tagName.toLowerCase();
            const rect = inp.getBoundingClientRect();
            fields.push({
                tag: tag,
                type: inp.type || '',
                name: inp.name || '',
                id: inp.id || '',
                value: tag === 'select'
                    ? Array.from(inp.options).map(o => ({
                        value: o.value,
                        text: o.text.slice(0, 100),
                        selected: o.selected,
                    }))
                    : String(inp.value || '').slice(0, 200),
                placeholder: inp.placeholder || '',
                required: inp.required || false,
                disabled: inp.disabled || false,
                label: inp.getAttribute('aria-label') || '',
                bounding_box: [
                    Math.round(rect.x), Math.round(rect.y),
                    Math.round(rect.width), Math.round(rect.height),
                ],
            });
        });

        forms.push({
            form_index: fi,
            action: form.action || '',
            method: (form.method || 'GET').toUpperCase(),
            id: form.id || '',
            name: form.name || '',
            fields: fields,
        });
    });
    return forms;
})()
"""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class InterpreterConfig:
    """Configuration for the DOM interpreter pipeline."""

    max_elements: int = 200
    max_depth: int = 15
    include_hidden: bool = False
    include_aria: bool = True
    chunk_size: int = 30
    prune_scripts: bool = True
    prune_styles: bool = True
    prune_svg: bool = True
    min_element_size: int = 5


@dataclass
class DOMNode:
    """A single interpreted DOM element."""

    node_id: int
    tag: str
    role: str
    node_type: str  # clickable | input | select | text | container | navigation | media
    label: str
    value: str
    attributes: dict[str, str]
    bounding_box: tuple[int, int, int, int]
    visible: bool
    interactable: bool
    children: list[int]
    parent: int | None
    depth: int


@dataclass
class DOMAction:
    """An action that can be performed on a DOM node."""

    action_type: str  # click | type | select | hover | scroll | clear | submit | focus
    node_id: int
    value: str = ""
    description: str = ""


@dataclass
class InteractableElement:
    """A typed interactive element — the core abstraction.

    Transforms raw DOM into callable/assignable objects:
    - Buttons → CallableAction (click, submit)
    - Inputs  → AssignableField (type text, select option)
    - Links   → NavigableTarget (follow URL)
    - Forms   → FormGroup (collection of assignable fields)
    """

    element_type: str  # button | link | text_input | checkbox | radio | select | textarea | form | toggle
    node: DOMNode
    actions: list[DOMAction]
    form_group: str | None
    priority: float  # 0-1, relevance to current task


@dataclass
class FormGroup:
    """A form with its fields as assignable variables."""

    form_id: str
    action: str
    method: str
    fields: list[InteractableElement]
    submit_button: InteractableElement | None


@dataclass
class DOMSnapshot:
    """Complete interpreted state of a page."""

    url: str
    title: str
    elements: list[InteractableElement]
    forms: list[FormGroup]
    navigation: list[InteractableElement]
    text_content: str
    node_count: int
    interactable_count: int
    timestamp: float
    snapshot_id: str


# ---------------------------------------------------------------------------
# Tag/role → element_type mapping helpers
# ---------------------------------------------------------------------------

_TAG_TYPE_MAP: dict[str, str] = {
    "a": "link",
    "button": "button",
    "input": "text_input",
    "select": "select",
    "textarea": "textarea",
    "option": "select",
    "details": "toggle",
    "summary": "button",
}

_INPUT_TYPE_MAP: dict[str, str] = {
    "checkbox": "checkbox",
    "radio": "radio",
    "submit": "button",
    "reset": "button",
    "button": "button",
    "file": "text_input",
    "password": "text_input",
    "email": "text_input",
    "text": "text_input",
    "search": "text_input",
    "tel": "text_input",
    "url": "text_input",
    "number": "text_input",
    "date": "text_input",
    "datetime-local": "text_input",
    "time": "text_input",
    "color": "text_input",
    "range": "text_input",
    "hidden": "text_input",
}

_ROLE_TYPE_MAP: dict[str, str] = {
    "button": "button",
    "link": "link",
    "menuitem": "button",
    "option": "select",
    "radio": "radio",
    "switch": "toggle",
    "tab": "button",
    "checkbox": "checkbox",
    "textbox": "text_input",
    "combobox": "select",
    "searchbox": "text_input",
    "spinbutton": "text_input",
    "slider": "text_input",
    "menuitemcheckbox": "checkbox",
    "menuitemradio": "radio",
}

_NODE_TYPE_MAP: dict[str, str] = {
    "a": "clickable",
    "button": "clickable",
    "input": "input",
    "select": "select",
    "textarea": "input",
    "img": "media",
    "video": "media",
    "audio": "media",
    "nav": "navigation",
    "header": "navigation",
    "footer": "navigation",
    "ul": "container",
    "ol": "container",
    "div": "container",
    "section": "container",
    "article": "container",
    "main": "container",
    "form": "container",
    "table": "container",
}


def _infer_node_type(tag: str, role: str, interactable: bool) -> str:
    """Infer a semantic node_type from tag, role, and interactability."""
    if role in _ROLE_TYPE_MAP:
        rtype = _ROLE_TYPE_MAP[role]
        if rtype in ("button", "link", "toggle"):
            return "clickable"
        if rtype in ("text_input", "textarea"):
            return "input"
        if rtype in ("checkbox", "radio", "select"):
            return "select"
    if tag in _NODE_TYPE_MAP:
        return _NODE_TYPE_MAP[tag]
    if interactable:
        return "clickable"
    return "text"


def _infer_element_type(tag: str, role: str, attrs: dict[str, str]) -> str:
    """Infer InteractableElement.element_type from tag/role/attrs."""
    if role and role in _ROLE_TYPE_MAP:
        return _ROLE_TYPE_MAP[role]
    if tag == "input":
        input_type = attrs.get("type", "text")
        return _INPUT_TYPE_MAP.get(input_type, "text_input")
    return _TAG_TYPE_MAP.get(tag, "button")


def _actions_for_element(element_type: str, node: DOMNode) -> list[DOMAction]:
    """Return available DOMActions for a given element type."""
    actions: list[DOMAction] = []
    nid = node.node_id
    label = node.label or node.tag

    if element_type in ("button", "toggle"):
        actions.append(DOMAction("click", nid, description=f"Click '{label}'"))
    elif element_type == "link":
        href = node.attributes.get("href", "")
        actions.append(DOMAction("click", nid, description=f"Navigate to '{label}'"))
        if href:
            actions.append(DOMAction("hover", nid, description=f"Hover over link '{label}'"))
    elif element_type in ("text_input", "textarea"):
        actions.append(DOMAction("click", nid, description=f"Focus '{label}'"))
        actions.append(DOMAction("type", nid, description=f"Type into '{label}'"))
        actions.append(DOMAction("clear", nid, description=f"Clear '{label}'"))
    elif element_type == "select":
        actions.append(DOMAction("click", nid, description=f"Open '{label}'"))
        actions.append(DOMAction("select", nid, description=f"Select option in '{label}'"))
    elif element_type in ("checkbox", "radio"):
        actions.append(DOMAction("click", nid, description=f"Toggle '{label}'"))
    else:
        actions.append(DOMAction("click", nid, description=f"Click '{label}'"))

    # All elements support focus
    actions.append(DOMAction("focus", nid, description=f"Focus '{label}'"))
    return actions


def _is_navigation_element(node: DOMNode) -> bool:
    """Check whether a node belongs to navigation."""
    nav_indicators = {"nav", "header", "footer", "menu", "sidebar", "navbar", "topbar"}
    if node.tag in ("nav",):
        return True
    attrs_str = " ".join(node.attributes.values()).lower()
    return any(ind in attrs_str for ind in nav_indicators)


# ---------------------------------------------------------------------------
# DOMInterpreter
# ---------------------------------------------------------------------------


class DOMInterpreter:
    """Transforms raw page DOM into typed, LLM-friendly representations.

    Three-stage pipeline:

    1. **Extract** — pull raw DOM + accessibility tree from the page via JS.
    2. **Prune** — remove invisible, non-interactive, script/style elements.
    3. **Type** — convert remaining elements into ``InteractableElement`` objects.

    Generates two representations:

    - **Structured**: ``list[InteractableElement]`` for programmatic use.
    - **Text**: Markdown table for LLM system prompt injection.
    """

    def __init__(self, config: InterpreterConfig | None = None) -> None:
        self.config = config or InterpreterConfig()
        self._extract_dom_js = _EXTRACT_DOM_JS.replace(
            "__MAX_DEPTH__", str(self.config.max_depth)
        )
        log.debug("DOMInterpreter initialised (max_elements=%d)", self.config.max_elements)

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    async def interpret(self, page_handle: Any) -> DOMSnapshot:
        """Run the full extract → prune → type pipeline on *page_handle*.

        Parameters
        ----------
        page_handle:
            A Playwright ``Page`` object (or any object exposing an
            ``evaluate`` coroutine).

        Returns
        -------
        DOMSnapshot
            Complete interpreted state of the page.
        """
        raw = await self.extract_raw(page_handle)
        nodes = self.prune(raw)
        elements = self.type_elements(nodes)

        # Identify forms
        forms = self._build_form_groups(raw, nodes, elements)

        # Identify navigation elements
        nav_elements = [e for e in elements if _is_navigation_element(e.node)]

        # Build text content from visible nodes
        text_parts: list[str] = []
        for n in nodes:
            if n.label and n.node_type == "text":
                text_parts.append(n.label)
        text_content = "\n".join(text_parts)[:20_000]

        snapshot = DOMSnapshot(
            url=raw.get("url", ""),
            title=raw.get("title", ""),
            elements=elements,
            forms=forms,
            navigation=nav_elements,
            text_content=text_content,
            node_count=raw.get("node_count", 0),
            interactable_count=len(elements),
            timestamp=time.time(),
            snapshot_id=uuid.uuid4().hex[:12],
        )
        log.info(
            "Interpreted %s — %d nodes → %d interactable elements, %d forms",
            snapshot.url,
            snapshot.node_count,
            snapshot.interactable_count,
            len(snapshot.forms),
        )
        return snapshot

    # ------------------------------------------------------------------
    # Stage 1: Extract
    # ------------------------------------------------------------------

    async def extract_raw(self, page_handle: Any) -> dict[str, Any]:
        """Execute JavaScript extraction on the page and return raw data.

        Returns a dict with keys ``url``, ``title``, ``node_count``,
        ``nodes`` (list[dict]), ``accessibility`` (list[dict]), and
        ``forms`` (list[dict]).
        """
        if not _HAS_PLAYWRIGHT:
            log.warning("Playwright unavailable — returning empty extraction")
            return {"url": "", "title": "", "node_count": 0, "nodes": [], "accessibility": [], "forms": []}

        try:
            dom_data = await page_handle.evaluate(self._extract_dom_js)
        except Exception as exc:
            log.error("DOM extraction failed: %s", exc)
            dom_data = {"url": "", "title": "", "node_count": 0, "nodes": []}

        a11y_data: list[dict[str, Any]] = []
        if self.config.include_aria:
            a11y_data = await self.get_accessibility_tree(page_handle)

        try:
            forms_data = await page_handle.evaluate(_EXTRACT_FORMS_JS)
        except Exception as exc:
            log.error("Form extraction failed: %s", exc)
            forms_data = []

        dom_data["accessibility"] = a11y_data
        dom_data["forms"] = forms_data
        return dom_data

    # ------------------------------------------------------------------
    # Stage 2: Prune
    # ------------------------------------------------------------------

    def prune(self, raw_dom: dict) -> list[DOMNode]:
        """Filter raw nodes into a pruned list of ``DOMNode`` objects.

        Removes:
        - invisible elements (unless ``include_hidden`` is set)
        - elements smaller than ``min_element_size``
        - elements beyond ``max_depth``
        - duplicates by ``node_id``
        """
        raw_nodes: list[dict[str, Any]] = raw_dom.get("nodes", [])
        pruned: list[DOMNode] = []
        seen_ids: set[int] = set()

        for rn in raw_nodes:
            nid = rn.get("node_id", -1)
            if nid in seen_ids:
                continue

            # Visibility filter
            if not self.config.include_hidden and not rn.get("visible", False):
                continue

            # Depth filter
            depth = rn.get("depth", 0)
            if depth > self.config.max_depth:
                continue

            # Size filter
            bbox = rn.get("bounding_box", [0, 0, 0, 0])
            if len(bbox) < 4:
                bbox = [0, 0, 0, 0]
            width, height = bbox[2], bbox[3]
            if width < self.config.min_element_size and height < self.config.min_element_size:
                # Allow zero-size only if it's a form-related hidden input
                tag = rn.get("tag", "")
                attrs = rn.get("attributes", {})
                if not (tag == "input" and attrs.get("type") == "hidden"):
                    continue

            tag = rn.get("tag", "")
            role = rn.get("role", "")
            interactable = rn.get("interactable", False)

            node = DOMNode(
                node_id=nid,
                tag=tag,
                role=role,
                node_type=_infer_node_type(tag, role, interactable),
                label=rn.get("label", ""),
                value=rn.get("value", ""),
                attributes=rn.get("attributes", {}),
                bounding_box=tuple(bbox[:4]),  # type: ignore[arg-type]
                visible=rn.get("visible", True),
                interactable=interactable,
                children=rn.get("children", []),
                parent=rn.get("parent"),
                depth=depth,
            )
            pruned.append(node)
            seen_ids.add(nid)

            if len(pruned) >= self.config.max_elements * 5:
                # Hard cap to avoid runaway processing
                break

        log.debug("Prune: %d raw → %d nodes", len(raw_nodes), len(pruned))
        return pruned

    # ------------------------------------------------------------------
    # Stage 3: Type
    # ------------------------------------------------------------------

    def type_elements(self, nodes: list[DOMNode]) -> list[InteractableElement]:
        """Convert pruned DOMNodes into typed ``InteractableElement`` objects.

        Only interactable nodes are promoted to elements.  The result is
        capped at ``config.max_elements``.
        """
        elements: list[InteractableElement] = []

        for node in nodes:
            if not node.interactable:
                continue

            element_type = _infer_element_type(node.tag, node.role, node.attributes)
            actions = _actions_for_element(element_type, node)

            elem = InteractableElement(
                element_type=element_type,
                node=node,
                actions=actions,
                form_group=None,
                priority=self._compute_priority(node),
            )
            elements.append(elem)

            if len(elements) >= self.config.max_elements:
                break

        log.debug("Typed %d interactable elements", len(elements))
        return elements

    # ------------------------------------------------------------------
    # LLM-friendly output
    # ------------------------------------------------------------------

    def to_markdown_table(
        self, elements: list[InteractableElement], max_rows: int = 50
    ) -> str:
        """Render elements as a compact Markdown table for LLM prompts.

        Columns: ID | Type | Label | Actions | Extra
        """
        rows: list[str] = [
            "| ID | Type | Label | Actions | Extra |",
            "|---|---|---|---|---|",
        ]
        for i, elem in enumerate(elements[:max_rows]):
            actions_str = ", ".join(a.action_type for a in elem.actions[:4])
            extra_parts: list[str] = []
            href = elem.node.attributes.get("href", "")
            if href:
                extra_parts.append(f"href={href[:60]}")
            if elem.form_group:
                extra_parts.append(f"form={elem.form_group}")
            extra = "; ".join(extra_parts) if extra_parts else ""
            label = elem.node.label.replace("|", "\\|")[:60]
            rows.append(
                f"| {elem.node.node_id} | {elem.element_type} | {label} | {actions_str} | {extra} |"
            )

        if len(elements) > max_rows:
            rows.append(f"| ... | ({len(elements) - max_rows} more) | | | |")

        return "\n".join(rows)

    def to_action_prompt(
        self, elements: list[InteractableElement], task: str
    ) -> str:
        """Generate a prompt asking the LLM which action to take next.

        Includes the element table and the current task description.
        """
        table = self.to_markdown_table(elements)
        prompt = (
            f"You are an AI browser agent. Your current task:\n\n"
            f"**{task}**\n\n"
            f"Below are the interactive elements on the current page:\n\n"
            f"{table}\n\n"
            f"Choose the next action. Reply with JSON:\n"
            f'{{"action_type": "...", "node_id": ..., "value": "...", '
            f'"reasoning": "..."}}\n\n'
            f"Available action types: click, type, select, hover, scroll, "
            f"clear, submit, focus.\n"
            f'If the task is complete, reply: {{"action_type": "done", '
            f'"reasoning": "..."}}'
        )
        return prompt

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    def chunk(
        self, nodes: list[DOMNode], chunk_size: int | None = None
    ) -> list[list[DOMNode]]:
        """Split a list of DOM nodes into chunks for large pages.

        Parameters
        ----------
        nodes:
            Full list of DOMNodes to chunk.
        chunk_size:
            Override for ``config.chunk_size``.
        """
        size = chunk_size or self.config.chunk_size
        if size <= 0:
            return [nodes]
        return [nodes[i : i + size] for i in range(0, len(nodes), size)]

    # ------------------------------------------------------------------
    # Accessibility tree
    # ------------------------------------------------------------------

    async def get_accessibility_tree(self, page_handle: Any) -> dict[str, Any]:
        """Extract the accessibility tree from the page.

        Returns a list of dicts with ``role``, ``name``, ``depth``,
        and optional state keys (``expanded``, ``checked``, etc.).
        """
        if not _HAS_PLAYWRIGHT:
            return {}
        try:
            tree = await page_handle.evaluate(_EXTRACT_ACCESSIBILITY_JS)
            return tree
        except Exception as exc:
            log.error("Accessibility tree extraction failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_priority(self, node: DOMNode) -> float:
        """Heuristic priority score for an interactable node.

        Higher priority for:
        - elements with visible labels
        - primary-action tags (button, a)
        - smaller DOM depth (more prominent)
        - elements with common action roles
        """
        score = 0.5

        # Label presence
        if node.label:
            score += 0.1

        # Tag bonus
        if node.tag in ("button", "a"):
            score += 0.1
        elif node.tag in ("input", "textarea"):
            score += 0.05

        # Role bonus
        if node.role in ("button", "link", "textbox", "searchbox"):
            score += 0.1

        # Depth penalty (deeper = less prominent)
        if node.depth <= 3:
            score += 0.1
        elif node.depth >= 10:
            score -= 0.1

        # Visibility bonus
        if node.visible:
            score += 0.05

        return max(0.0, min(1.0, score))

    def _build_form_groups(
        self,
        raw_dom: dict[str, Any],
        nodes: list[DOMNode],
        elements: list[InteractableElement],
    ) -> list[FormGroup]:
        """Build FormGroup objects from extracted form data.

        Links InteractableElements back to their parent forms so that
        agents can fill entire forms programmatically.
        """
        forms_raw: list[dict[str, Any]] = raw_dom.get("forms", [])
        if not forms_raw:
            return []

        # Build lookup from node tag+name/id to InteractableElement
        elem_by_name: dict[str, InteractableElement] = {}
        elem_by_id: dict[str, InteractableElement] = {}
        for elem in elements:
            name = elem.node.attributes.get("name", "")
            eid = elem.node.attributes.get("id", "")
            if name:
                elem_by_name[name] = elem
            if eid:
                elem_by_id[eid] = elem

        form_groups: list[FormGroup] = []
        for form_data in forms_raw:
            form_id = form_data.get("id") or form_data.get("name") or f"form_{form_data.get('form_index', 0)}"
            action = form_data.get("action", "")
            method = form_data.get("method", "GET")

            field_elements: list[InteractableElement] = []
            submit_btn: InteractableElement | None = None

            for fd in form_data.get("fields", []):
                field_name = fd.get("name", "")
                field_id = fd.get("id", "")
                field_tag = fd.get("tag", "")
                field_type = fd.get("type", "")

                # Find matching InteractableElement
                matched = elem_by_name.get(field_name) or elem_by_id.get(field_id)
                if matched is None:
                    # Create a synthetic element for fields not in the pruned set
                    bbox_raw = fd.get("bounding_box", [0, 0, 0, 0])
                    if len(bbox_raw) < 4:
                        bbox_raw = [0, 0, 0, 0]
                    synthetic_node = DOMNode(
                        node_id=-1,
                        tag=field_tag,
                        role="",
                        node_type="input" if field_tag in ("input", "textarea") else "select",
                        label=fd.get("label", "") or fd.get("placeholder", "") or field_name,
                        value=str(fd.get("value", "")),
                        attributes={"name": field_name, "id": field_id, "type": field_type},
                        bounding_box=tuple(bbox_raw[:4]),  # type: ignore[arg-type]
                        visible=True,
                        interactable=True,
                        children=[],
                        parent=None,
                        depth=0,
                    )
                    etype = _infer_element_type(field_tag, "", {"type": field_type})
                    matched = InteractableElement(
                        element_type=etype,
                        node=synthetic_node,
                        actions=_actions_for_element(etype, synthetic_node),
                        form_group=form_id,
                        priority=0.5,
                    )

                # Tag this element as belonging to this form
                matched.form_group = form_id

                # Detect submit button
                if field_tag == "button" or (field_tag == "input" and field_type in ("submit", "button")):
                    if submit_btn is None:
                        submit_btn = matched
                else:
                    field_elements.append(matched)

            fg = FormGroup(
                form_id=form_id,
                action=action,
                method=method,
                fields=field_elements,
                submit_button=submit_btn,
            )
            form_groups.append(fg)

        log.debug("Built %d form groups", len(form_groups))
        return form_groups
