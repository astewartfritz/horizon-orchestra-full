from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BoilerplateTemplate:
    name: str
    description: str
    code: str
    language: str = "python"


_TEMPLATES: dict[str, str] = {
    "class": """class {name}:
    def __init__(self{params}):
{init_body}

    def __repr__(self) -> str:
        return f"{name}({repr_fields})"
""",
    "dataclass": """from dataclasses import dataclass


@dataclass
class {name}:
{fields}
""",
    "context-manager": """from contextlib import contextmanager


@contextmanager
def {name}({params}):
    # Setup
    try:
        yield
    finally:
        # Teardown
        pass
""",
    "decorator": """from functools import wraps


def {name}({params}):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Before
            result = func(*args, **kwargs)
            # After
            return result
        return wrapper
    return decorator
""",
    "singleton": """class {name}:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self{params}):
        if self._initialized:
            return
        self._initialized = True
{init_body}
""",
    "factory": """from abc import ABC, abstractmethod


class {name}Product(ABC):
    @abstractmethod
    def operation(self) -> str:
        pass


class ConcreteProductA({name}Product):
    def operation(self) -> str:
        return "Result A"


class ConcreteProductB({name}Product):
    def operation(self) -> str:
        return "Result B"


class {name}Factory:
    def create_product(self, product_type: str) -> {name}Product:
        mapping = {{
            "a": ConcreteProductA,
            "b": ConcreteProductB,
        }}
        cls = mapping.get(product_type.lower())
        if cls is None:
            raise ValueError(f"Unknown product: {{product_type}}")
        return cls()
""",
    "pydantic-model": """from pydantic import BaseModel, Field
from typing import Optional


class {name}(BaseModel):
{fields}
""",
    "fastapi-endpoint": """from fastapi import APIRouter, Depends, HTTPException
from typing import List

router = APIRouter(prefix="/{prefix}", tags=["{tag}"])


@router.get("/")
async def list_{items}():
    "Return all {items}."
    return []


@router.get("/{{{item_id}}}")
async def get_{item}({item_id}: int):
    "Return a single {item} by {item_id}, or 404 if it does not exist."
    raise HTTPException(status_code=404, detail="not found")


@router.post("/")
async def create_{item}(data: dict):
    "Persist a new {item} and return the created representation."
    return {{"created": True, "{item}": data}}
""",
    "cli-app": """import click


@click.group()
def cli():
    \"\"\"{name} CLI tool.\"\"\"


@cli.command()
@click.argument("input")
@click.option("--verbose", "-v", is_flag=True)
def process(input, verbose):
    \"\"\"Process INPUT.\"\"\"
    if verbose:
        click.echo(f"Processing {{input}}...")
    click.echo(f"Done: {{input}}")


if __name__ == "__main__":
    cli()
""",
    "async-worker": """import asyncio
import logging

logger = logging.getLogger(__name__)


class {name}:
    def __init__(self, concurrency: int = 5):
        self.concurrency = concurrency
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def start(self):
        self._running = True
        workers = [asyncio.create_task(self._worker(i)) for i in range(self.concurrency)]
        await asyncio.gather(*workers)

    async def stop(self):
        self._running = False

    async def enqueue(self, item):
        await self._queue.put(item)

    async def _worker(self, worker_id: int):
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._process(item, worker_id)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Worker {{worker_id}} error: {{e}}")

    async def _process(self, item, worker_id: int):
        # Override in subclass
        pass
""",
    "unittest": """import unittest


class Test{name}(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_basic(self):
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
""",
    "pytest": """import pytest


@pytest.fixture
def {fixture}():
    "Provide a {fixture} for the test; teardown runs after the yield."
    resource = {{}}  # Replace with real resource construction.
    yield resource
    resource.clear()  # Replace with resource.close() or equivalent.


def test_{name}():
    assert True


@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
])
def test_parametrized(input, expected):
    assert input * 2 == expected
""",
    "error-handler": """class {name}Error(Exception):
    \"\"\"Base exception for {name} module.\"\"\"
    pass


class NotFoundError({name}Error):
    def __init__(self, resource: str, id):
        super().__init__(f"{{resource}} not found: {{id}}")
        self.resource = resource
        self.id = id


class ValidationError({name}Error):
    def __init__(self, field: str, message: str):
        super().__init__(f"Validation error on {{field}}: {{message}}")
        self.field = field
        self.message = message
""",
    "middleware": """from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import time


class {name}Middleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed = time.perf_counter() - start
        response.headers["X-Process-Time"] = f"{{elapsed:.4f}}"
        return response
""",
    "dockerfile": """FROM python:{version}-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "{entrypoint}"]
""",
    "makefile": """.PHONY: install test lint clean

install:
\tpip install -e ".[dev]"

test:
\tpython -m pytest tests/

lint:
\truff check src/

clean:
\trm -rf build/ dist/ *.egg-info
\trm -rf .pytest_cache/ __pycache__/
\tfind . -type d -name __pycache__ -exec rm -rf {{}} + 2>/dev/null || true

run:
\tpython -m {module}
""",
}


class BoilerplateGenerator:
    def __init__(self):
        self.templates: dict[str, BoilerplateTemplate] = {}
        for name, code in _TEMPLATES.items():
            self.templates[name] = BoilerplateTemplate(name=name, description=_DESCRIPTIONS.get(name, ""), code=code)

    def list_templates(self) -> list[BoilerplateTemplate]:
        return list(self.templates.values())

    def get_template(self, name: str) -> Optional[BoilerplateTemplate]:
        return self.templates.get(name)

    def generate(self, template_name: str, **kwargs) -> str:
        tmpl = self.templates.get(template_name)
        if not tmpl:
            raise ValueError(f"Unknown template: {template_name}. Available: {', '.join(self.templates.keys())}")

        defaults = self._get_defaults(template_name)
        defaults.update(kwargs)
        combined = defaults

        try:
            return tmpl.code.format(**combined)
        except KeyError as e:
            return f"# Missing template variable: {e}\n" + tmpl.code

    def _get_defaults(self, name: str) -> dict:
        defaults: dict = {
            "name": "MyClass",
            "params": "",
            "init_body": "    pass",
            "fields": "    name: str",
            "repr_fields": "name={{self.name!r}}",
            "prefix": "api",
            "tag": "default",
            "items": "items",
            "item": "item",
            "item_id": "item_id",
            "version": "3.11",
            "entrypoint": "main.py",
            "module": "src",
            "fixture": "default_fixture",
        }
        return defaults


_DESCRIPTIONS: dict[str, str] = {
    "class": "Standard Python class with constructor and repr",
    "dataclass": "Python dataclass with type annotations",
    "context-manager": "Context manager using contextlib",
    "decorator": "Decorator with functools.wraps",
    "singleton": "Singleton pattern implementation",
    "factory": "Abstract factory pattern with ABC",
    "pydantic-model": "Pydantic v2 data model",
    "fastapi-endpoint": "FastAPI CRUD router endpoints",
    "cli-app": "Click-based CLI application skeleton",
    "async-worker": "Async worker with configurable concurrency",
    "unittest": "unittest.TestCase test skeleton",
    "pytest": "pytest test with fixtures and parametrize",
    "error-handler": "Custom exception hierarchy",
    "middleware": "Starlette ASGI middleware",
    "dockerfile": "Dockerfile for Python application",
    "makefile": "Makefile with common targets",
}
