#!/usr/bin/env bash
# d2ba setup: installs everything that CAN be installed unattended, and kicks
# off the two things that can't (gh OAuth login, ServiceNow credentials) at
# the right point instead of leaving them as prose you have to piece together.
set -e

echo "== d2ba setup =="
echo ""

if ! command -v brew &>/dev/null; then
    echo "Homebrew not found. Install it from https://brew.sh, then re-run this script."
    exit 1
fi

if ! command -v pandoc &>/dev/null; then
    echo "Installing pandoc..."
    brew install pandoc
else
    echo "pandoc already installed."
fi

if ! command -v gh &>/dev/null; then
    echo "Installing GitHub CLI..."
    brew install gh
else
    echo "GitHub CLI already installed."
fi

echo "Installing Python dependencies (openpyxl, Pillow)..."
python3 -m pip install --quiet openpyxl Pillow

if ! command -v node &>/dev/null; then
    echo "Node not found. Install Node 20 or later (brew install node, or nvm), then re-run this script."
    exit 1
fi
NODE_MAJOR=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_MAJOR" -lt 20 ]; then
    echo "Node $NODE_MAJOR found, need 20 or later. Upgrade Node, then re-run this script."
    exit 1
fi
echo "Node OK ($(node -v))."

echo ""
echo "-- GitHub login (needs you to authorize in a browser, this can't be automated) --"
if gh auth status &>/dev/null; then
    echo "Already logged in as $(gh api user --jq .login 2>/dev/null)."
else
    gh auth login
fi

echo ""
echo "-- ServiceNow auth --"
echo "Existing now-sdk auth aliases:"
npx --yes @servicenow/sdk auth --list 2>/dev/null || echo "  (none yet)"
echo ""
echo "If the instance you need isn't listed above, either:"
echo "  a) run: npx @servicenow/sdk auth --add <instance-url> --type basic --alias <name> --username <user> --password-stdin"
echo "  b) or skip this step entirely: pass --auth <new-alias-name> --env path/to/.env to d2ba.py scaffold/pipeline"
echo "     and it registers the alias for you from SN_INSTANCE_URL/SN_USERNAME/SN_PASSWORD in that .env"

echo ""
echo "Setup complete. Example run:"
echo '  python3 d2ba.py pipeline BRD.docx --target-dir ./my-app --app-name "My App" \'
echo '      --scope-name x_snc_my_app --auth <alias> --verify-build \'
echo '      --publish --repo my-app --owner <your-github-username>'
