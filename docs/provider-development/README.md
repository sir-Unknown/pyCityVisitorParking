# Provider Development: Running Live Checks in GitHub Codespaces

This guide shows how to run `scripts/provider_live_check.py` from a GitHub
Codespace and share the sanitized output for debugging.

## Prerequisites

- Access to the repository on GitHub.
- Valid provider credentials (do not share them).

## 1) Create a Codespace

Start a new Codespace from the repository.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/sir-Unknown/pyCityVisitorParking/)

## 2) Select the branch

If you need to test a feature branch, select it after the Codespace is running.

![Select branch](images/select-branch.png)

## 3) Open the repository in the browser (optional)

If you need a quick link back to the repository, open it in the browser.

![Open in browser](images/open-in-browser.png)

## 4) Run the live check script

Open the terminal inside the Codespace and run the script with your provider
inputs. This example uses the Amsterdam provider and writes a sanitized dump
file.

```bash
PYTHONPATH=src PROVIDER_ID=amsterdam \
BASE_URL=https://api.parkeervergunningen.egisparkingservices.nl \
USERNAME=... PASSWORD=... LICENSE_PLATE=AB12CD \
python scripts/provider_live_check.py \
  --run-all \
  --dump-json \
  --dump-dir .tmp/http-trace \
  --sanitize-output
```

![Paste command](images/paste-command.png)

## 5) Share the results safely

The script writes a single run file in `.tmp/http-trace/` with a name like
`YYYYMMDD-HHMMSS-PID.json`.

To share results:

1) Open the `.tmp/http-trace/` folder in the Codespace file explorer.
2) Open the newest run file and **confirm it contains no secrets** (the contents
   should be sanitized, but check yourself for tokens, passwords, names, and full
   license plates).
3) Copy the file contents or download the file and attach it to your issue.

![Copy dump](images/copy-dump.png)

## 6) Record a browser session (optional)

A recording of the provider's own web portal shows every API call and response
the portal makes, including steps the live check script does not cover yet.

1) Open the portal in Chrome, Edge, or Firefox and open the developer tools
   (`F12`), tab **Network**.
2) Enable **Preserve log** (Chrome/Edge) or **Persist Logs** (Firefox, gear
   menu), then reload the page.
3) Log in and perform the steps you want to share, for example start a session,
   change its end time, stop it, add or remove a favorite.
4) Export the recording: **Export HAR** (download icon, Chrome/Edge) or
   **Save All As HAR** (gear menu, Firefox).
5) Log out of the portal, so the token in the recording stops working.
6) Drag the `.har` file into the Codespace file explorer and sanitize it:

```bash
python scripts/sanitize.py session.har --output .tmp/session.sanitized.json
rm session.har
```

The raw `.har` file contains your password, login token, and cookies. **Never
share it.** `sanitize.py` keeps only API calls, masks headers such as
`Authorization` and `Cookie`, masks IDs in URLs, and sanitizes JSON bodies the
same way as the live check dumps. HTML pages, scripts, and images are dropped.
Check the sanitized file as described above before you share it.

## Tips

- Add `--debug-http` if you need request/response summaries in the terminal.
- Add `--traceback` to include full error tracebacks when debugging failures.
