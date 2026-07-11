# d2ba: docx to Build Agent pipeline

CLI for the pipeline: **Word doc to Markdown spec with real images and embedded-spreadsheet
data to real Fluent app scaffold to git repo**, ready to hand to ServiceNow Build Agent.

Build Agent has no upload API at the moment so this approach allows creating a repo that has the needed text files and tables that will be used by Build Agent. 

This is especially useful if the technical/functional specifications or business requirement document is in a document format that is too large to be consumed (Build Agent can query content up to 100K characters).

> **Disclaimer: images are not solved by this tool.** Extracting screenshots to `images/` and
> pushing them to git does **not** make Build Agent able to read them. No path exists through git,
> the workspace file tree, MCP, or a table query that lets Build Agent decode an image file into
> something it can see. The only thing that works is literally attaching the image in the chat
> panel during that session. This tool gets the images into a convenient, organized location
> (`docs/images/`) so a human can grab them and attach them. It does not make them machine-readable
> by any automated means. If you need Build Agent to see a diagram, attach it by hand, every
> session, no exceptions.

## Why this exists

Feeding Build Agent a complex spec doc has real constraints, confirmed against ServiceNow's own
docs and direct testing:
- Build Agent's chat accepts `.txt/.md/.csv/.log`, code files, and images
  (`.png/.jpg/.jpeg/.gif/.svg/.webp`), but not `.docx`/`.pdf`
  ([`ba-supported-file-types.md`](https://www.servicenow.com/docs/r/application-development/ba-supported-file-types.html)).
  For images specifically, this is **only** true via the chat panel's attach/upload control.
  There's no evidence that Build Agent's other access paths (workspace file reading, table
  queries, MCP tool results) ever decode an image file into something it can actually see. Text
  files are different: the `GUIDE_*.md` grounding-file convention below works by the file just
  sitting in the workspace, no upload needed, and that distinction does not extend to images.
  Always attach images directly in chat, regardless of whether they're also sitting in
  `docs/images/`.
- It **can** query instance tables directly, including Knowledge Base articles. This is a
  documented tool ([`build-agent-tools.md`](https://www.servicenow.com/docs/r/application-development/build-agent-tools.html):
  "Build Agent can use the run query tool to query a specific table within your instance and
  return the top five records or derive specific insights"), and it was confirmed by direct
  testing: pointed at a KB article, Build Agent read it and reported an exact character count of
  the record.
- The catch is size, not access. That same query is capped at roughly 100,000 characters with no
  documented override. A full BRD easily exceeds that (confirmed at 238,535 characters in one
  test), so Build Agent gets a silently truncated fragment, not the real content, if you just
  point it at a large record instead of uploading files directly.

So the only reliable path is to convert the doc mechanically (no AI rewriting) into small files
Build Agent actually accepts, and place them somewhere Build Agent's documented grounding-file
convention picks them up if you're working in a Fluent workspace.

## Pipeline: docx to Build Agent

```
┌─────────────────────────────────┐
│   BRD_something.docx            │  your source Word doc
└───────────────┬─────────────────┘
                │  d2ba.py convert
                │  (pandoc + python, no AI rewriting)
                ▼
┌─────────────────────────────────┐
│  Build Agent package (local)    │
│  |- SPEC_NAME.md                │  verbatim text/tables
│  |- images/*.png                │  real screenshots
│  `- embedded-data/*.csv         │  data from OLE objects
└───────────────┬─────────────────┘
                │  d2ba.py scaffold
                │  (npx @servicenow/sdk init + sidecar merge)
                ▼
┌─────────────────────────────────┐
│  Fluent app scaffold (local)    │
│  |- now.config.json             │
│  |- src/fluent/, src/server/    │
│  |- GUIDE_NAME.md               │  spec, renamed, at root
│  `- docs/images/,               │
│     docs/embedded-data/         │
└───────────────┬─────────────────┘
                │  d2ba.py publish
                │  (git init/commit + gh repo create/push)
                ▼
┌─────────────────────────────────┐
│  GitHub repo (private)          │
└───────────────┬─────────────────┘
                │  MANUAL - log in to GitHub in the
                │  IDE's Source Control view (OAuth or
                │  basic auth), then clone. One login,
                │  not a multi-step integration.
                ▼
┌─────────────────────────────────┐
│  ServiceNow IDE workspace       │
│  (Build Agent chat panel        │
│   lives here)                   │
└───────────────┬─────────────────┘
                │  MANUAL - attach files directly
                │  in the Build Agent chat panel,
                │  one message, every session
                ▼
┌─────────────────────────────────┐
│  Build Agent                    │
│  [x] GUIDE_NAME.md              │  - chat attach OR sits
│                                 │    in workspace tree
│  [ ] images/*.png               │  - chat attach ONLY.
│                                 │    Being in the repo/workspace
│                                 │    does NOT count.
│  [x] *.csv                      │  - unverified: plausibly same
│                                 │    as .md, not confirmed
└─────────────────────────────────┘
                ▼
       Build Agent builds the app
```

Note on the `*.csv` row: unlike the `.md` grounding-file convention, which ServiceNow explicitly
documents, there's no equivalent documented or tested confirmation that CSVs sitting in the
workspace (rather than being chat-attached) get read the same way. It's plausible since both are
plain text, but it hasn't actually been verified the way the `.md` behavior and the image
restriction have. Don't treat it as confirmed.

Boxes above the GitHub repo are what `d2ba.py` automates. Everything from "MANUAL" down is a
human clicking in a browser. There's no API for either step, so this tool can't do them for you.

## Prerequisites

Things only you can provide, that `install.sh` can't get for you:

- **A GitHub account.** `d2ba.py publish` pushes the scaffold+sidecar repo there. You then log in
  with the same account to the ServiceNow IDE's Source Control view to clone that same repo into
  the Fluent workspace.
- **A ServiceNow instance with Build Agent installed and enabled**, with required roles assigned.
  See Build Agent documentation in SN docs for more details.

Everything else (pandoc, `gh` CLI, Node/Python versions, the packages) is handled by `install.sh`
below. You don't need to know or install any of it yourself.

## Setup (run once, in this order)

```bash
./install.sh
```

That one command installs whatever's missing (pandoc, GitHub CLI, Python packages, checks
Node is 20+), then runs `gh auth login` if you're not already logged in (this is the one step
that needs you personally, it's an OAuth authorization in a browser, nothing can click that
button for you), then lists your existing ServiceNow `now-sdk` auth aliases and tells you how to
add one if you need to.

Do this before running any `d2ba.py` command. `publish` will fail without GitHub login, and
`scaffold`/`pipeline` will fail without a ServiceNow auth alias. Getting both sorted first means
the actual pipeline run below goes straight through without stopping partway.

## Usage: your first run

Say you have `Acme_Widget_Catalog.docx` (a generic placeholder, substitute your own file) and
want it turned into a Fluent app scaffold pushed to `github.com/yourname/widget-catalog-app`.

1. **Run setup once** (skip if already done): `./install.sh`.
2. **Pick your values:**
   - `--app-name` is just a display name, e.g. `"Widget Catalog"`.
   - `--scope-name` must start with your instance's company code and be under 18 characters, e.g.
     `x_snc_widget_catalog` (check the code with a query against `glide.appcreator.company.code`
     on your instance if you don't know it).
   - `--auth` is a `now-sdk auth` alias for your ServiceNow instance. Run
     `npx now-sdk auth --list` to see what you already have, or add `--env path/to/.env` (with
     `SN_INSTANCE_URL`/`SN_USERNAME`/`SN_PASSWORD` in it) to register a new one automatically.
   - `--repo` and `--owner` are the GitHub repo name and your GitHub username.
3. **Run the whole pipeline in one command:**
   ```bash
   python3 d2ba.py pipeline Acme_Widget_Catalog.docx \
       --target-dir ./widget-catalog-app \
       --app-name "Widget Catalog" \
       --scope-name x_snc_widget_catalog \
       --auth my-instance --verify-build \
       --publish --repo widget-catalog-app --owner yourname
   ```
4. **What happens, in order:** it converts the docx (prints how many images/CSVs it found), scaffolds
   a real Fluent app and runs `npm run build` to confirm it's valid, merges the spec and images in
   as `./widget-catalog-app/GUIDE_Acme_Widget_Catalog.md` and `./widget-catalog-app/docs/`, then
   pushes all of it to `github.com/yourname/widget-catalog-app`. The last line it prints is the
   repo URL.
5. **What you do next, manually** (see the "Manual step" section below): open that repo's URL,
   confirm it looks right, then go log in to it from the ServiceNow IDE and attach the files to
   Build Agent's chat.

## Subcommands

Reference for running the steps individually instead of as one `pipeline` call.

```bash
# 1. Convert a Word doc into a Build Agent upload package
python3 d2ba.py convert BRD.docx --out ./package

# 2. Scaffold a real Fluent app and merge the package into it as a sidecar
python3 d2ba.py scaffold ./package ./my-app \
    --app-name "My App" --scope-name x_snc_my_app \
    --auth my-instance --verify-build

# 3. Commit and push to GitHub (private by default)
python3 d2ba.py publish ./my-app --repo my-app --owner yourname

# All three in one shot
python3 d2ba.py pipeline BRD.docx --target-dir ./my-app \
    --app-name "My App" --scope-name x_snc_my_app \
    --auth my-instance --verify-build \
    --publish --repo my-app --owner yourname
```

`--auth` refers to a `now-sdk auth` alias (`npx now-sdk auth --list` to see yours). If you'd
rather point at a project's `.env` (`SN_INSTANCE_URL`/`SN_USERNAME`/`SN_PASSWORD`) and have the
alias registered automatically the first time, pass `--auth <new-alias-name> --env path/to/.env`.

## What `scaffold` actually does

1. Runs `npx @servicenow/sdk init --template typescript.basic` (or whichever template you pick).
   This is a real scaffold, verified buildable, not hand-approximated.
2. Renames the package's spec `.md` to `GUIDE_<name>.md` at the project root. This follows
   ServiceNow's own documented Build Agent grounding-file convention
   ([`build-agent-general-guidelines.md`](https://www.servicenow.com/docs/r/application-development/build-agent-general-guidelines.html)):
   *"Place a markdown file, for example named `GUIDE_*.md` or `BUILD_AGENT_RULES.md`, in your
   project directory. Build Agent reads these grounding files..."*
3. Moves `images/` and `embedded-data/` under `docs/`, rewriting the guide's relative links to
   match.
4. `--verify-build` runs `npm run build` and fails loudly if it doesn't pass.

## Targeting an existing repo (kept history)

If `--repo` already exists on GitHub when you run `pipeline`, it's cloned into `--target-dir`
automatically before anything is scaffolded, so the final push shares history and lands as a
normal fast-forward instead of getting rejected. You don't need to clone it yourself first. This
only works if `--target-dir` doesn't already have files in it (the clone needs an empty
directory to clone into).

## What `publish` deliberately does NOT do

No force-push, no auto-resolving diverged history. This is what the auto-clone above exists to
avoid, but if you're running `scaffold` and `publish` as separate steps (not `pipeline`) against
an existing repo, you're responsible for putting the scaffold inside a clone of that repo
yourself first. `publish` alone won't do it for you: by the time it runs, `scaffold` has already
written files into `--target-dir`, too late to clone into it safely.

## Known side effect

Every `scaffold`/`pipeline` run registers a new scope name on the target instance via
`now-sdk init` (that's inherent to the SDK, not this tool). Test runs leave behind an unused
scope registration. It's harmless, but clean it up on the instance if you're testing repeatedly
with throwaway scope names.

## Manual step after this tool runs

Open ServiceNow Studio, go to the Build Agent chat panel, attach the `GUIDE_*.md` plus everything
in `docs/images/` and `docs/embedded-data/` together in one message, then prompt Build Agent to
build from the spec, referencing filenames directly.
