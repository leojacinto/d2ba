#!/usr/bin/env python3
"""
publish.py — commit a local directory and push it to a GitHub repo via `gh`.

Deliberately conservative: never force-pushes, never overwrites diverged
history. If the remote already has commits this local repo doesn't, it fails
with a clear message instead of guessing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, cwd=None, check=True):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        die(f"`{' '.join(cmd)}` failed:\n{proc.stdout}\n{proc.stderr}")
    return proc


def check_gh_auth():
    """Fail fast, before doing any real work, if gh isn't authenticated yet."""
    proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if proc.returncode != 0:
        die("`gh` is not authenticated. Run `./install.sh` or `gh auth login` first, "
            "then re-run this command. (Checked upfront on purpose, so you don't wait "
            "through the whole conversion/scaffold step first.)")


def repo_exists(full_name: str) -> bool:
    proc = subprocess.run(["gh", "repo", "view", full_name, "--json", "name"], capture_output=True, text=True)
    return proc.returncode == 0


def resolve_owner(owner: str = None) -> str:
    if owner:
        return owner
    whoami = run(["gh", "api", "user", "--jq", ".login"], check=True)
    return whoami.stdout.strip()


def clone_if_repo_exists(target_dir: Path, repo_name: str, owner: str = None) -> bool:
    """If repo_name already exists on GitHub, clone it into target_dir before any
    scaffolding happens, so the eventual push shares history and fast-forwards
    instead of getting rejected. Returns True if cloned, False if the repo
    doesn't exist yet (nothing to do, fresh-scaffold path applies as normal).
    """
    owner = resolve_owner(owner)
    full_name = f"{owner}/{repo_name}"
    if not repo_exists(full_name):
        return False
    if target_dir.exists() and any(target_dir.iterdir()):
        die(f"{target_dir} already has files in it, refusing to clone {full_name} into a "
            f"non-empty directory. Remove it or pick a different --target-dir.")
    print(f"Repo {full_name} already exists, cloning it into {target_dir} first "
          f"to keep shared history for the push.")
    run(["gh", "repo", "clone", full_name, str(target_dir)])
    return True


def publish(target_dir: Path, repo_name: str, owner: str = None, private: bool = True,
            message: str = "Initial commit"):
    check_gh_auth()

    if not (target_dir / ".git").exists():
        run(["git", "init"], cwd=target_dir)
        run(["git", "branch", "-M", "main"], cwd=target_dir)

    run(["git", "add", "-A"], cwd=target_dir)
    status = run(["git", "status", "--porcelain"], cwd=target_dir, check=False)
    if status.stdout.strip():
        run(["git", "commit", "-m", message], cwd=target_dir)
        print("Committed changes.")
    else:
        print("Nothing new to commit.")

    owner = resolve_owner(owner)
    target = f"{owner}/{repo_name}"
    exists = repo_exists(target)

    if not exists:
        visibility = "--private" if private else "--public"
        print(f"Creating new repo {target} ({visibility})...")
        run(["gh", "repo", "create", target, visibility, "--source", str(target_dir), "--remote", "origin", "--push"],
            cwd=target_dir)
        print(f"Created and pushed: https://github.com/{target}")
        return f"https://github.com/{target}"

    print(f"Repo {target} already exists — pushing to it.")
    remotes = run(["git", "remote"], cwd=target_dir, check=False).stdout.split()
    repo_url = f"https://github.com/{target}.git"
    if "origin" not in remotes:
        run(["git", "remote", "add", "origin", repo_url], cwd=target_dir)
    else:
        run(["git", "remote", "set-url", "origin", repo_url], cwd=target_dir)

    push = run(["git", "push", "-u", "origin", "main"], cwd=target_dir, check=False)
    if push.returncode != 0:
        die(
            "Push rejected — the remote likely has commits this local repo doesn't "
            "(e.g. it already has content). Resolve manually (pull/rebase or merge) "
            "rather than force-pushing.\n" + push.stdout + push.stderr
        )
    print(f"Pushed: https://github.com/{target}")
    return f"https://github.com/{target}"
