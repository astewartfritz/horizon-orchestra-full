"""Deploy script — Helm upgrade or ArgoCD sync to staging/production."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def run(cmd: list[str], cwd: str | None = None) -> bool:
    print(f"[deploy] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout[-300:])
    if result.stderr:
        print(f"[deploy] STDERR: {result.stderr[-300:]}")
    return result.returncode == 0


def helm_deploy(env: str, tag: str, namespace: str) -> bool:
    """Deploy via Helm upgrade."""
    values_file = f"ci-cd/helm/values-{env}.yaml"
    if not os.path.exists(values_file):
        values_file = "charts/orchestra/values.yaml"

    return run([
        "helm", "upgrade", "--install", f"orchestra-{env}",
        "charts/orchestra/",
        "--namespace", namespace,
        "--create-namespace",
        "-f", values_file,
        "--set", f"image.tag={tag}",
        "--set", f"image.repository={os.environ.get('DOCKER_REGISTRY', 'docker.io/orchestra')}",
        "--wait", "--timeout", "5m",
    ])


def argocd_sync(env: str, tag: str) -> bool:
    """Trigger ArgoCD sync via CLI."""
    app_name = f"orchestra-{env}"
    server = os.environ.get("ARGOCD_SERVER", "")
    token = os.environ.get("ARGOCD_TOKEN", "")

    if server and token:
        run(["argocd", "login", server, "--grpc-web", "--auth-token", token])
        run(["argocd", "app", "set", app_name, "--helm-set", f"image.tag={tag}"])
        return run(["argocd", "app", "sync", app_name, "--grpc-web", "--async"])
    else:
        print("[deploy] ARGOCD_SERVER not set, falling back to Helm")
        return helm_deploy(env, tag, f"orchestra-{env}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy Orchestra to an environment")
    parser.add_argument("--env", choices=["staging", "production"], required=True)
    parser.add_argument("--tag", default="latest")
    parser.add_argument("--method", choices=["helm", "argocd"], default="")
    args = parser.parse_args()

    print("=" * 60)
    print(f"Deploy Stage — {args.env} (tag: {args.tag})")
    print("=" * 60)

    method = args.method or os.environ.get("DEPLOY_METHOD", "argocd")

    if method == "argocd":
        ok = argocd_sync(args.env, args.tag)
    else:
        ok = helm_deploy(args.env, args.tag, f"orchestra-{args.env}")

    if ok:
        print(f"[deploy] Successfully deployed {args.env}")
        return 0
    else:
        print(f"[deploy] FAILED: deploy to {args.env}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
