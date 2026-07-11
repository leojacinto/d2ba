#!/usr/bin/env python3
"""
scaffold.py — create a real ServiceNow Fluent app scaffold via the Now SDK CLI,
then merge a docx_to_build_agent.py package into it as a "sidecar":

  - the .md spec goes to <target>/GUIDE_<slug>.md (project root), matching
    ServiceNow's own documented Build Agent grounding-file convention
    ("Place a markdown file, for example named GUIDE_*.md or
    BUILD_AGENT_RULES.md, in your project directory. Build Agent reads these
    grounding files and follows your conventions throughout the session.")
  - images/ and embedded-data/ go to <target>/docs/, with the guide file's
    relative links rewritten to match
  - a README.md is written describing the combined structure

This calls the real `npx @servicenow/sdk` CLI — the scaffold it produces is a
genuine, buildable Fluent project, not a hand-approximated one.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

VALID_TEMPLATES = {"base", "javascript.basic", "javascript.react", "typescript.basic", "typescript.react", "typescript.vue"}


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_sdk():
    result = subprocess.run(["npx", "@servicenow/sdk", "--version"], capture_output=True, text=True)
    if result.returncode != 0:
        die("`npx @servicenow/sdk` is not available. Run `npm install -g @servicenow/sdk` "
            "or ensure it's reachable via npx.")


def register_auth_alias_from_env(env_path: Path, alias: str):
    """Non-interactively register a now-sdk auth alias from a .env file
    (SN_INSTANCE_URL / SN_USERNAME / SN_PASSWORD), per the documented
    --password-stdin pattern. Skips if the alias already exists."""
    existing = subprocess.run(["npx", "now-sdk", "auth", "--list"], capture_output=True, text=True)
    if f"[{alias}]" in existing.stdout:
        print(f"Auth alias '{alias}' already registered — reusing it.")
        return

    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    missing = [k for k in ("SN_INSTANCE_URL", "SN_USERNAME", "SN_PASSWORD") if k not in env]
    if missing:
        die(f"{env_path} is missing {missing} — cannot register an auth alias from it.")

    proc = subprocess.run(
        ["npx", "now-sdk", "auth", "--add", env["SN_INSTANCE_URL"],
         "--type", "basic", "--alias", alias, "--username", env["SN_USERNAME"], "--password-stdin"],
        input=env["SN_PASSWORD"], capture_output=True, text=True,
    )
    if proc.returncode != 0:
        die(f"Failed to register auth alias '{alias}': {proc.stdout}\n{proc.stderr}")
    print(f"Registered new auth alias '{alias}' -> {env['SN_INSTANCE_URL']}")


def create_fluent_scaffold(target_dir: Path, app_name: str, scope_name: str,
                            package_name: str = None, template: str = "typescript.basic",
                            auth_alias: str = None, env_path: Path = None, skip_install: bool = False) -> Path:
    check_sdk()
    if template not in VALID_TEMPLATES:
        die(f"Invalid template {template!r}. Choices: {sorted(VALID_TEMPLATES)}")
    if len(scope_name) > 18:
        die(f"Scope name {scope_name!r} is {len(scope_name)} chars — must be <= 18.")

    target_dir.mkdir(parents=True, exist_ok=True)
    if (target_dir / "now.config.json").exists():
        die(f"{target_dir} already has a now.config.json — refusing to re-init over an existing scaffold.")

    package_name = package_name or re.sub(r"[^a-z0-9-]+", "-", app_name.lower()).strip("-")

    if auth_alias and env_path:
        register_auth_alias_from_env(env_path, auth_alias)

    cmd = ["npx", "@servicenow/sdk", "init",
           "--appName", app_name, "--packageName", package_name,
           "--scopeName", scope_name, "--template", template]
    if auth_alias:
        cmd += ["--auth", auth_alias]

    print(f"Running: {' '.join(cmd)} (cwd={target_dir})")
    proc = subprocess.run(cmd, cwd=target_dir, capture_output=True, text=True)
    print(proc.stdout)
    if proc.returncode != 0:
        die(f"now-sdk init failed:\n{proc.stderr}")

    if not skip_install:
        print("Running npm install...")
        proc = subprocess.run(["npm", "install"], cwd=target_dir, capture_output=True, text=True)
        if proc.returncode != 0:
            die(f"npm install failed:\n{proc.stderr}")

    return target_dir


def verify_build(target_dir: Path) -> bool:
    proc = subprocess.run(["npm", "run", "build"], cwd=target_dir, capture_output=True, text=True)
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode == 0


def assemble_sidecar(package_dir: Path, target_dir: Path, guide_name: str = None) -> Path:
    """Merge a docx_to_build_agent package into a Fluent scaffold as a sidecar."""
    md_files = [f for f in package_dir.glob("*.md") if f.name != "UPLOAD-TO-BUILD-AGENT.md"]
    if not md_files:
        die(f"No spec .md found directly inside {package_dir}.")
    spec_md = md_files[0]

    guide_name = guide_name or f"GUIDE_{re.sub(r'[^A-Za-z0-9]+', '_', spec_md.stem).strip('_')}.md"
    guide_path = target_dir / guide_name

    text = spec_md.read_text(encoding="utf-8")
    text = re.sub(r'\((images/[^)]+)\)', r'(docs/\1)', text)
    text = re.sub(r'`embedded-data/', r'`docs/embedded-data/', text)
    guide_path.write_text(text, encoding="utf-8")

    docs_dir = target_dir / "docs"
    images_src = package_dir / "images"
    data_src = package_dir / "embedded-data"
    if images_src.exists() and any(images_src.iterdir()):
        dest = docs_dir / "images"
        dest.mkdir(parents=True, exist_ok=True)
        for f in images_src.glob("*"):
            shutil.copy2(f, dest / f.name)
    if data_src.exists() and any(data_src.iterdir()):
        dest = docs_dir / "embedded-data"
        dest.mkdir(parents=True, exist_ok=True)
        for f in data_src.glob("*.csv"):
            shutil.copy2(f, dest / f.name)

    print(f"Sidecar assembled: {guide_path.relative_to(target_dir)}, "
          f"docs/images ({len(list((docs_dir/'images').glob('*')) if (docs_dir/'images').exists() else [])} files), "
          f"docs/embedded-data ({len(list((docs_dir/'embedded-data').glob('*')) if (docs_dir/'embedded-data').exists() else [])} files)")
    return guide_path
