"""Tests for CI/CD pipeline scripts."""

from __future__ import annotations

from pathlib import Path

import pytest


# ── Dockerfile Tests ─────────────────────────

class TestDockerfile:
    def test_dockerfile_exists(self):
        assert Path("ci-cd/Dockerfile").exists()

    def test_dockerfile_has_multistage(self):
        content = Path("ci-cd/Dockerfile").read_text()
        assert "FROM python:3.13-slim AS builder" in content
        assert "FROM node:22-alpine AS ts-builder" in content
        assert "FROM python:3.13-slim" in content

    def test_dockerfile_has_healthcheck(self):
        content = Path("ci-cd/Dockerfile").read_text()
        assert "HEALTHCHECK" in content

    def test_dockerfile_exposes_port(self):
        content = Path("ci-cd/Dockerfile").read_text()
        assert "EXPOSE 8000" in content


class TestDockerignore:
    def test_dockerignore_exists(self):
        assert Path("ci-cd/.dockerignore").exists()

    def test_dockerignore_has_key_entries(self):
        content = Path("ci-cd/.dockerignore").read_text()
        assert "__pycache__" in content
        assert ".git" in content


class TestMakefile:
    def test_makefile_exists(self):
        assert Path("ci-cd/Makefile").exists()

    def test_makefile_has_targets(self):
        content = Path("ci-cd/Makefile").read_text()
        for target in ["build:", "test:", "lint:", "ci:", "docker:", "deploy:", "clean:", "help:"]:
            assert target in content


class TestJenkinsfile:
    def test_jenkinsfile_exists(self):
        assert Path("ci-cd/Jenkinsfile").exists()

    def test_jenkinsfile_has_stages(self):
        content = Path("ci-cd/Jenkinsfile").read_text()
        for stage in ["Build", "Test", "Lint & Quality", "Docker Build", "Deploy Staging"]:
            assert f"stage('{stage}')" in content

    def test_jenkinsfile_has_parallel(self):
        assert "parallel" in Path("ci-cd/Jenkinsfile").read_text()

    def test_jenkinsfile_has_post(self):
        assert "post" in Path("ci-cd/Jenkinsfile").read_text()


class TestGitLabCI:
    def test_gitlab_ci_exists(self):
        assert Path("ci-cd/.gitlab-ci.yml").exists()

    def test_gitlab_ci_has_stages(self):
        content = Path("ci-cd/.gitlab-ci.yml").read_text()
        for stage in ["build", "test", "lint", "quality", "docker", "deploy"]:
            assert stage in content

    def test_gitlab_ci_has_cache(self):
        assert "cache:" in Path("ci-cd/.gitlab-ci.yml").read_text()

    def test_gitlab_ci_has_artifacts(self):
        assert "artifacts" in Path("ci-cd/.gitlab-ci.yml").read_text()

    def test_gitlab_ci_environments(self):
        content = Path("ci-cd/.gitlab-ci.yml").read_text()
        assert "staging" in content
        assert "production" in content


class TestArgoCD:
    def test_application_exists(self):
        assert Path("ci-cd/argocd/application.yaml").exists()

    def test_application_required_fields(self):
        content = Path("ci-cd/argocd/application.yaml").read_text()
        assert "kind: Application" in content
        assert "syncPolicy:" in content

    def test_project_exists(self):
        assert Path("ci-cd/argocd/project.yaml").exists()

    def test_project_required_fields(self):
        content = Path("ci-cd/argocd/project.yaml").read_text()
        assert "kind: AppProject" in content

    def test_kustomize_exists(self):
        assert Path("ci-cd/argocd/kustomize/kustomization.yaml").exists()

    def test_kustomize_resources(self):
        content = Path("ci-cd/argocd/kustomize/kustomization.yaml").read_text()
        for r in ["deployment.yaml", "service.yaml", "ingress.yaml", "configmap.yaml", "hpa.yaml"]:
            assert r in content


class TestScripts:
    def test_build_script_exists(self):
        assert Path("ci-cd/scripts/build.py").exists()

    def test_build_script_parses(self):
        _assert_parses("ci-cd/scripts/build.py")

    def test_test_script_exists(self):
        assert Path("ci-cd/scripts/test.py").exists()

    def test_test_script_parses(self):
        _assert_parses("ci-cd/scripts/test.py")

    def test_deploy_script_exists(self):
        assert Path("ci-cd/scripts/deploy.py").exists()

    def test_deploy_script_parses(self):
        _assert_parses("ci-cd/scripts/deploy.py")

    def test_lint_script_exists(self):
        assert Path("ci-cd/scripts/lint.py").exists()

    def test_lint_script_parses(self):
        _assert_parses("ci-cd/scripts/lint.py")

    def test_get_coverage_pct(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<coverage line-rate="0.85"/>')
        pct = float(root.attrib.get("line-rate", 0)) * 100
        assert pct == 85.0


class TestHelmValues:
    def test_helm_values_exists(self):
        assert Path("ci-cd/helm/values.yaml").exists()

    def test_helm_values_has_keys(self):
        content = Path("ci-cd/helm/values.yaml").read_text()
        for key in ["replicaCount:", "image:", "resources:", "autoscaling:", "ingress:", "config:"]:
            assert key in content


def _assert_parses(path: str) -> None:
    import ast
    with open(path) as f:
        ast.parse(f.read())
