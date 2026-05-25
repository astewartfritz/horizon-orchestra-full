"""Tests for scaffold generators and language context detection."""

import json
import tempfile
from pathlib import Path

import pytest

from orchestra.code_agent.scaffold.context import LanguageDetector, LANGUAGE_CONTEXTS
from orchestra.code_agent.scaffold.generator import TEMPLATES, ScaffoldGenerator


class TestLanguageDetector:
    def test_detect_rust(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "Cargo.toml").write_text("[package]\nname = \"test\"\n")
            d = LanguageDetector(td)
            assert d.detect() == "rust"

    def test_detect_typescript(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "package.json").write_text("{\"name\": \"test\"}\n")
            d = LanguageDetector(td)
            assert d.detect() == "typescript"

    def test_detect_python(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "pyproject.toml").write_text("[project]\nname = \"test\"\n")
            d = LanguageDetector(td)
            assert d.detect() == "python"

    def test_detect_mojo(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "mojoproject.toml").write_text("[project]\nname = \"test\"\n")
            d = LanguageDetector(td)
            assert d.detect() == "mojo"

    def test_detect_none(self):
        with tempfile.TemporaryDirectory() as td:
            d = LanguageDetector(td)
            assert d.detect() is None

    def test_format_context_rust(self):
        ctx = LanguageDetector.format_context("rust")
        assert "cargo build" in ctx
        assert "cargo test" in ctx
        assert "cargo clippy" in ctx
        assert "rust" in ctx

    def test_format_context_typescript(self):
        ctx = LanguageDetector.format_context("typescript")
        assert "npm run build" in ctx
        assert "npm test" in ctx

    def test_format_context_mojo(self):
        ctx = LanguageDetector.format_context("mojo")
        assert "mojo build" in ctx
        assert "mojo test" in ctx

    def test_language_name(self):
        assert LanguageDetector.language_name("rust") == "Rust"
        assert LanguageDetector.language_name("mojo") == "Mojo"
        assert LanguageDetector.language_name("unknown") == "Unknown"

    def test_get_context_rust(self):
        ctx = LanguageDetector().get_context("rust")
        assert "serde" in ctx
        assert "tokio" in ctx
        assert "cargo build" in ctx
        assert "cargo test" in ctx
        assert "cargo clippy" in ctx


class TestLanguageContexts:
    @pytest.mark.parametrize("lang", ["rust", "typescript", "python", "mojo"])
    def test_required_keys(self, lang):
        ctx = LANGUAGE_CONTEXTS[lang]
        assert "extensions" in ctx
        assert "build" in ctx or lang == "mojo"
        assert "test" in ctx
        assert "detect_files" in ctx

    def test_rust_deps(self):
        deps = LANGUAGE_CONTEXTS["rust"]["common_deps"]
        assert "serde" in deps
        assert "tokio" in deps
        assert "clap" in deps

    def test_typescript_deps(self):
        deps = LANGUAGE_CONTEXTS["typescript"]["common_deps"]
        assert "typescript" in deps
        assert "vitest" in deps

    def test_mojo_no_deps(self):
        assert LANGUAGE_CONTEXTS["mojo"]["common_deps"] == []


class TestNewTemplates:
    def test_rust_template_registered(self):
        assert "rust-package" in TEMPLATES

    def test_typescript_lib_registered(self):
        assert "typescript-lib" in TEMPLATES

    def test_typescript_cli_registered(self):
        assert "typescript-cli" in TEMPLATES

    def test_typescript_nextjs_registered(self):
        assert "typescript-nextjs" in TEMPLATES

    def test_mojo_template_registered(self):
        assert "mojo-package" in TEMPLATES

    def test_rust_template_files(self):
        files = TEMPLATES["rust-package"]
        assert "Cargo.toml" in files
        assert "src/main.rs" in files
        assert "src/lib.rs" in files
        assert "tests/integration.rs" in files
        assert ".github/workflows/ci.yml" in files

    def test_rust_toml_contains_deps(self):
        content = TEMPLATES["rust-package"]["Cargo.toml"]
        assert "clap" in content
        assert "serde" in content
        assert "tokio" in content
        assert "reqwest" in content

    def test_typescript_lib_files(self):
        files = TEMPLATES["typescript-lib"]
        assert "package.json" in files
        assert "tsconfig.json" in files
        assert "src/index.ts" in files
        assert "tests/index.test.ts" in files
        assert "eslint.config.js" in files
        assert ".github/workflows/ci.yml" in files

    def test_typescript_cli_has_commander(self):
        content = TEMPLATES["typescript-cli"]["package.json"]
        assert "commander" in content

    def test_typescript_nextjs_has_next(self):
        content = TEMPLATES["typescript-nextjs"]["package.json"]
        assert "next" in content

    def test_typescript_nextjs_files(self):
        files = TEMPLATES["typescript-nextjs"]
        assert "src/app/layout.tsx" in files
        assert "src/app/page.tsx" in files
        assert "tailwind.config.js" in files

    def test_mojo_files(self):
        files = TEMPLATES["mojo-package"]
        assert "mojoproject.toml" in files
        assert "src/main.mojo" in files
        assert "src/lib.mojo" in files
        assert "tests/test_main.mojo" in files
        assert "Makefile" in files
        assert "notebooks/example.ipynb" in files

    def test_mojo_notebook_valid_json(self):
        content = TEMPLATES["mojo-package"]["notebooks/example.ipynb"]
        formatted = content.format(name="test", description="Test")
        data = json.loads(formatted)
        assert data["nbformat"] == 4
        assert data["metadata"]["kernelspec"]["name"] == "mojo"

    def test_mojo_project_name_injected(self):
        content = TEMPLATES["mojo-package"]["mojoproject.toml"]
        formatted = content.format(name="myproject", description="Test")
        assert "myproject" in formatted
        assert "Test" in formatted


class TestTemplateCount:
    def test_total_templates(self):
        assert len(TEMPLATES) == 10

    def test_new_templates_present(self):
        new = {"rust-package", "typescript-lib", "typescript-cli", "typescript-nextjs", "mojo-package"}
        assert new.issubset(set(TEMPLATES.keys()))


class TestScaffoldGenerator:
    @pytest.mark.asyncio
    async def test_generator_unknown_template(self):
        gen = ScaffoldGenerator()
        result = await gen(template="nonexistent", name="test")
        assert result.error is not None
        assert "Unknown" in result.error

    @pytest.mark.asyncio
    async def test_generator_wrong_params(self):
        gen = ScaffoldGenerator()
        result = await gen(template="rust-package", name="", output_dir=tempfile.mkdtemp())
        assert result.output is not None

    @pytest.mark.asyncio
    async def test_generator_rust(self):
        with tempfile.TemporaryDirectory() as td:
            gen = ScaffoldGenerator()
            result = await gen(template="rust-package", name="myapp", output_dir=td)
            assert result.error is None or result.error == ""
            assert (Path(td) / "Cargo.toml").exists()
            assert (Path(td) / "src/main.rs").exists()
            assert (Path(td) / "src/lib.rs").exists()
            assert (Path(td) / ".rustfmt.toml").exists()
            cargo = (Path(td) / "Cargo.toml").read_text()
            assert "myapp" in cargo

    @pytest.mark.asyncio
    async def test_generator_typescript_lib(self):
        with tempfile.TemporaryDirectory() as td:
            gen = ScaffoldGenerator()
            result = await gen(template="typescript-lib", name="mylib", output_dir=td)
            assert not result.error
            assert (Path(td) / "package.json").exists()
            assert (Path(td) / "tsconfig.json").exists()
            assert (Path(td) / "src/index.ts").exists()
            pkg = json.loads((Path(td) / "package.json").read_text())
            assert pkg["name"] == "mylib"

    @pytest.mark.asyncio
    async def test_generator_typescript_cli(self):
        with tempfile.TemporaryDirectory() as td:
            gen = ScaffoldGenerator()
            result = await gen(template="typescript-cli", name="mycli", output_dir=td)
            assert not result.error
            assert (Path(td) / "src/cli.ts").exists()
            pkg = json.loads((Path(td) / "package.json").read_text())
            assert pkg["bin"]["mycli"] == "./dist/cli.js"

    @pytest.mark.asyncio
    async def test_generator_typescript_nextjs(self):
        with tempfile.TemporaryDirectory() as td:
            gen = ScaffoldGenerator()
            result = await gen(template="typescript-nextjs", name="myapp", output_dir=td)
            assert not result.error
            assert (Path(td) / "src/app/layout.tsx").exists()
            assert (Path(td) / "src/app/page.tsx").exists()

    @pytest.mark.asyncio
    async def test_generator_mojo(self):
        with tempfile.TemporaryDirectory() as td:
            gen = ScaffoldGenerator()
            result = await gen(template="mojo-package", name="mymod", description="Mojo test", output_dir=td)
            assert not result.error
            assert (Path(td) / "mojoproject.toml").exists()
            assert (Path(td) / "src/main.mojo").exists()
            assert (Path(td) / "src/lib.mojo").exists()
            assert (Path(td) / "Makefile").exists()
            main = (Path(td) / "src/main.mojo").read_text()
            assert "mymod" not in main  # name not in main.mojo template
            readme = (Path(td) / "README.md").read_text()
            assert "Mojo test" in readme
