#!/usr/bin/env python3
"""
d2ba — docx to Build Agent pipeline CLI.

Pipeline: Word doc -> Markdown spec (verbatim, no AI) with real images and
embedded-spreadsheet CSVs -> real Fluent app scaffold -> sidecar merge ->
git commit/push. The last step (uploading into Build Agent's chat and
prompting it to build) stays manual — Build Agent has no upload API, only a
chat-panel attach control.

Subcommands:
    convert   <docx> [--out DIR]
    scaffold  <package_dir> <target_dir> --app-name NAME --scope-name SCOPE
              [--package-name NAME] [--template T] [--skip-install] [--verify-build]
    publish   <target_dir> --repo NAME [--owner OWNER] [--public] [--message MSG]
    pipeline  <docx> --target-dir DIR --app-name NAME --scope-name SCOPE
              [package/scaffold/publish options...] [--publish --repo NAME]

The scaffold is a hand-written dummy (locally generated scopeId, never
registered on any ServiceNow instance) -- see lib/scaffold.py's module
docstring for why. No ServiceNow credentials are needed to run this tool.

Examples:
    python3 d2ba.py convert BRD.docx --out ./package
    python3 d2ba.py scaffold ./package ./my-app --app-name "My App" \\
        --scope-name x_snc_my_app
    python3 d2ba.py pipeline BRD.docx --target-dir ./my-app \\
        --app-name "My App" --scope-name x_snc_my_app \\
        --publish --repo my-app --owner yourname
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import convert as convert_lib
import scaffold as scaffold_lib
import publish as publish_lib


def cmd_convert(args):
    docx_path = Path(args.docx).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve() if args.out else Path.cwd() / f"{docx_path.stem}_build_agent_package"
    convert_lib.convert(docx_path, out_dir)
    print(f"\nPackage ready at: {out_dir}")


def cmd_scaffold(args):
    package_dir = Path(args.package_dir).expanduser().resolve()
    target_dir = Path(args.target_dir).expanduser().resolve()

    scaffold_lib.create_fluent_scaffold(
        target_dir, args.app_name, args.scope_name,
        package_name=args.package_name, template=args.template,
        skip_install=args.skip_install,
    )
    scaffold_lib.assemble_sidecar(package_dir, target_dir, guide_name=args.guide_name)

    if args.verify_build:
        ok = scaffold_lib.verify_build(target_dir)
        print("Build check:", "PASSED" if ok else "FAILED")
        if not ok:
            sys.exit(1)

    print(f"\nScaffold ready at: {target_dir}")


def cmd_publish(args):
    target_dir = Path(args.target_dir).expanduser().resolve()
    url = publish_lib.publish(
        target_dir, args.repo, owner=args.owner,
        private=not args.public, message=args.message,
    )
    print(f"\n{url}")


def cmd_pipeline(args):
    docx_path = Path(args.docx).expanduser().resolve()
    target_dir = Path(args.target_dir).expanduser().resolve()

    if args.publish:
        if not args.repo:
            print("ERROR: --publish requires --repo", file=sys.stderr)
            sys.exit(1)
        publish_lib.check_gh_auth()  # fail now, not after conversion + scaffold + npm install
        # If --repo already exists, clone it into target_dir *before* scaffolding anything,
        # so the eventual push shares history and fast-forwards instead of getting rejected.
        publish_lib.clone_if_repo_exists(target_dir, args.repo, owner=args.owner)

    package_dir = target_dir.parent / f"_{target_dir.name}_package_tmp"
    convert_lib.convert(docx_path, package_dir)

    scaffold_lib.create_fluent_scaffold(
        target_dir, args.app_name, args.scope_name,
        package_name=args.package_name, template=args.template,
        skip_install=args.skip_install,
    )
    scaffold_lib.assemble_sidecar(package_dir, target_dir, guide_name=args.guide_name)

    if args.verify_build:
        ok = scaffold_lib.verify_build(target_dir)
        print("Build check:", "PASSED" if ok else "FAILED")
        if not ok:
            sys.exit(1)

    import shutil
    shutil.rmtree(package_dir, ignore_errors=True)

    if args.publish:
        url = publish_lib.publish(
            target_dir, args.repo, owner=args.owner,
            private=not args.public, message=args.message,
        )
        print(f"\nDone: {url}")
    else:
        print(f"\nScaffold ready at: {target_dir} (not published — pass --publish --repo NAME to push)")

    print("\nManual step remaining: open ServiceNow Studio -> Build Agent chat panel, "
          "attach the GUIDE_*.md plus docs/images/* and docs/embedded-data/*.csv together, "
          "and prompt Build Agent to build from the spec.")


def build_parser():
    p = argparse.ArgumentParser(prog="d2ba", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("convert", help="Convert a .docx into a Build Agent upload package")
    c.add_argument("docx")
    c.add_argument("--out")
    c.set_defaults(func=cmd_convert)

    s = sub.add_parser("scaffold", help="Create a Fluent scaffold and merge a package into it as a sidecar")
    s.add_argument("package_dir")
    s.add_argument("target_dir")
    s.add_argument("--app-name", required=True)
    s.add_argument("--scope-name", required=True)
    s.add_argument("--package-name")
    s.add_argument("--template", default="typescript.basic", choices=sorted(scaffold_lib.VALID_TEMPLATES))
    s.add_argument("--auth", help="now-sdk auth alias to use")
    s.add_argument("--env", help="Path to a .env with SN_INSTANCE_URL/SN_USERNAME/SN_PASSWORD to auto-register --auth alias if missing")
    s.add_argument("--guide-name", help="Filename for the sidecar guide .md (default: GUIDE_<spec-name>.md)")
    s.add_argument("--skip-install", action="store_true")
    s.add_argument("--verify-build", action="store_true", help="Run `npm run build` after assembling and fail if it doesn't pass")
    s.set_defaults(func=cmd_scaffold)

    pub = sub.add_parser("publish", help="Commit and push a directory to a GitHub repo")
    pub.add_argument("target_dir")
    pub.add_argument("--repo", required=True)
    pub.add_argument("--owner")
    pub.add_argument("--public", action="store_true", help="Create as public (default: private)")
    pub.add_argument("--message", default="Initial commit")
    pub.set_defaults(func=cmd_publish)

    pl = sub.add_parser("pipeline", help="Run convert -> scaffold -> (optional) publish end to end")
    pl.add_argument("docx")
    pl.add_argument("--target-dir", required=True)
    pl.add_argument("--app-name", required=True)
    pl.add_argument("--scope-name", required=True)
    pl.add_argument("--package-name")
    pl.add_argument("--template", default="typescript.basic", choices=sorted(scaffold_lib.VALID_TEMPLATES))
    pl.add_argument("--auth")
    pl.add_argument("--env")
    pl.add_argument("--guide-name")
    pl.add_argument("--skip-install", action="store_true")
    pl.add_argument("--verify-build", action="store_true")
    pl.add_argument("--publish", action="store_true")
    pl.add_argument("--repo")
    pl.add_argument("--owner")
    pl.add_argument("--public", action="store_true")
    pl.add_argument("--message", default="Initial commit")
    pl.set_defaults(func=cmd_pipeline)

    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
