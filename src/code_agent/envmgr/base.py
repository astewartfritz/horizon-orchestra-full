from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class VenvInfo:
    name: str
    path: str
    python_version: str = ""
    packages: int = 0


class EnvManager:
    def __init__(self, envs_dir: str = ".venvs"):
        self.envs_dir = Path(envs_dir).resolve()
        self.envs_dir.mkdir(parents=True, exist_ok=True)

    def create(self, name: str, python_path: str = "") -> VenvInfo:
        venv_path = self.envs_dir / name
        if venv_path.exists():
            raise FileExistsError(f"Environment '{name}' already exists at {venv_path}")

        python = python_path or sys.executable
        subprocess.run(
            [python, "-m", "venv", str(venv_path)],
            check=True, capture_output=True, timeout=120,
        )
        return self._get_venv_info(name, venv_path)

    def remove(self, name: str) -> bool:
        venv_path = self.envs_dir / name
        if not venv_path.exists():
            return False

        import shutil
        shutil.rmtree(str(venv_path))
        return True

    def list(self) -> list[VenvInfo]:
        infos: list[VenvInfo] = []
        for entry in self.envs_dir.iterdir():
            if entry.is_dir() and (entry / "pyvenv.cfg").exists():
                infos.append(self._get_venv_info(entry.name, entry))
        return sorted(infos, key=lambda v: v.name)

    def exists(self, name: str) -> bool:
        return (self.envs_dir / name / "pyvenv.cfg").exists()

    def get(self, name: str) -> Optional[VenvInfo]:
        venv_path = self.envs_dir / name
        if not (venv_path / "pyvenv.cfg").exists():
            return None
        return self._get_venv_info(name, venv_path)

    def pip_install(self, name: str, packages: list[str]) -> str:
        pip = self._pip_path(name)
        if not pip:
            raise FileNotFoundError(f"Environment '{name}' not found")
        result = subprocess.run([pip, "install"] + packages, capture_output=True, text=True, timeout=120)
        return result.stdout + result.stderr

    def pip_list(self, name: str) -> list[dict]:
        pip = self._pip_path(name)
        if not pip:
            raise FileNotFoundError(f"Environment '{name}' not found")
        result = subprocess.run([pip, "list", "--format=json"], capture_output=True, text=True, timeout=30)
        try:
            import json
            return json.loads(result.stdout)
        except (json.JSONDecodeError, Exception):
            return []

    def pip_freeze(self, name: str) -> str:
        pip = self._pip_path(name)
        if not pip:
            raise FileNotFoundError(f"Environment '{name}' not found")
        result = subprocess.run([pip, "freeze"], capture_output=True, text=True, timeout=30)
        return result.stdout.strip()

    def run_python(self, name: str, script: str, cwd: Optional[str] = None) -> str:
        python = self._python_path(name)
        if not python:
            raise FileNotFoundError(f"Environment '{name}' not found")
        result = subprocess.run(
            [python, "-c", script],
            capture_output=True, text=True, timeout=60, cwd=cwd,
        )
        out = result.stdout
        if result.stderr:
            out += "\nSTDERR:\n" + result.stderr
        return out

    def _get_venv_info(self, name: str, venv_path: Path) -> VenvInfo:
        python = self._python_path_from_venv(venv_path)
        version = ""
        packages = 0

        if python and python.exists():
            try:
                vresult = subprocess.run([str(python), "--version"], capture_output=True, text=True, timeout=10)
                version = vresult.stdout.strip() or vresult.stderr.strip()
            except Exception:
                version = ""
            try:
                presult = subprocess.run([str(python), "-m", "pip", "list", "--format=json"], capture_output=True, text=True, timeout=30)
                if presult.stdout:
                    import json
                    packages = len(json.loads(presult.stdout))
            except Exception:
                packages = 0

        return VenvInfo(name=name, path=str(venv_path), python_version=version, packages=packages)

    def _python_path(self, name: str) -> Optional[Path]:
        venv_path = self.envs_dir / name
        if not (venv_path / "pyvenv.cfg").exists():
            return None
        return self._python_path_from_venv(venv_path)

    def _python_path_from_venv(self, venv_path: Path) -> Path:
        if sys.platform == "win32":
            return venv_path / "Scripts" / "python.exe"
        return venv_path / "bin" / "python"

    def _pip_path(self, name: str) -> Optional[Path]:
        venv_path = self.envs_dir / name
        if not (venv_path / "pyvenv.cfg").exists():
            return None
        if sys.platform == "win32":
            return venv_path / "Scripts" / "pip.exe"
        return venv_path / "bin" / "pip"

    def summary_text(self, infos: list[VenvInfo]) -> str:
        if not infos:
            return "No virtual environments found."
        lines = [
            f"Virtual Environments ({len(infos)}):",
            f"{'Name':<20} {'Python':<30} {'Packages':<10} {'Path':<40}",
            "-" * 100,
        ]
        for v in infos:
            lines.append(f"{v.name:<20} {v.python_version:<30} {v.packages:<10} {v.path:<40}")
        return "\n".join(lines)
