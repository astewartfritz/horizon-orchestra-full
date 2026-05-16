from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LICENSE_NAMES = {
    "mit": "MIT License",
    "apache": "Apache License 2.0",
    "gpl": "GNU General Public License",
    "lgpl": "GNU Lesser General Public License",
    "bsd": "BSD License",
    "mpl": "Mozilla Public License 2.0",
    "unlicense": "The Unlicense",
    "cc0": "CC0 1.0 Universal",
    "proprietary": "Proprietary",
}


@dataclass
class DependencyLicense:
    name: str = ""
    version: str = ""
    license_name: str = "unknown"
    license_type: str = "unknown"
    source: str = "pip"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version,
                "license": self.license_name, "type": self.license_type}


class LicenseScanner:
    def scan_python(self, requirements_path: str = "") -> list[DependencyLicense]:
        results = []

        if not requirements_path:
            for candidate in ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"]:
                if Path(candidate).exists():
                    requirements_path = candidate
                    break

        if not requirements_path:
            return results

        if "pyproject" in requirements_path:
            try:
                data = json.loads(Path(requirements_path).read_text())
                deps = []
                project = data.get("project", {})
                deps.extend(project.get("dependencies", []))
                deps.extend(project.get("optional-dependencies", {}).get("all", []))
                for dep in deps:
                    m = re.match(r'^([\w-]+)(?:[>=<~!]+\s*[\d.*]+)?', dep)
                    if m:
                        results.append(DependencyLicense(
                            name=m.group(1), source="pip",
                            license_type="unknown",
                        ))
            except (json.JSONDecodeError, OSError):
                pass
        elif "requirements" in requirements_path:
            for line in Path(requirements_path).read_text().split("\n"):
                line = line.strip()
                if line and not line.startswith(("#", "-", "git+")):
                    m = re.match(r'^([\w-]+)([>=<~!]+\s*[\d.*]+)?', line)
                    if m:
                        results.append(DependencyLicense(
                            name=m.group(1), version=(m.group(2) or "").strip(">=<~!"),
                            source="pip", license_type="unknown",
                        ))

        return results

    def scan_npm(self, package_path: str = "package.json") -> list[DependencyLicense]:
        results = []
        p = Path(package_path)
        if not p.exists():
            return results
        try:
            data = json.loads(p.read_text())
            for section in ["dependencies", "devDependencies"]:
                for name, version in data.get(section, {}).items():
                    results.append(DependencyLicense(
                        name=name, version=version.strip("^~"),
                        source="npm", license_type="unknown",
                    ))
        except (json.JSONDecodeError, OSError):
            pass
        return results

    def scan_directory(self, path: str = ".") -> list[DependencyLicense]:
        results = []
        results.extend(self.scan_python())
        results.extend(self.scan_npm())
        return results

    def summary(self, deps: list[DependencyLicense]) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for d in deps:
            by_type[d.license_type] = by_type.get(d.license_type, 0) + 1
        return {
            "total_dependencies": len(deps),
            "by_license_type": by_type,
            "unknown_licenses": sum(1 for d in deps if d.license_type == "unknown"),
        }
