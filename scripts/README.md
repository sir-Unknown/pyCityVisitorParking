# Scripts

Helper scripts for manual checks, troubleshooting, and local validation. These
tools are intended for development and debugging only; they are not part of the
public library API and should not be used in production integrations.

## Contents

- `provider_live_check.py`: Runs end-to-end checks against a selected provider
  (login, permit, reservations, favorites) using real credentials.
- `sanitize.py`: Redacts privacy-sensitive values in JSON files so logs can be
  shared safely with maintainers or in issues.

## Usage

From the repository root, set `PYTHONPATH=src` so the scripts can import the
local package.

Basic login + read-only checks for each provider. These flows authenticate,
fetch the current permit, and list reservations/favorites without modifying
anything.

```bash
PYTHONPATH=src PROVIDER_ID=the_hague BASE_URL=https://parkerendenhaag.denhaag.nl \
USERNAME=... PASSWORD=... \
python scripts/provider_live_check.py

PYTHONPATH=src PROVIDER_ID=dvsportal BASE_URL=https://parkeren.rijswijk.nl \
USERNAME=... PASSWORD=... \
python scripts/provider_live_check.py

PYTHONPATH=src PROVIDER_ID=amsterdam BASE_URL=https://api.parkeervergunningen.egisparkingservices.nl \
USERNAME=... PASSWORD=... CLIENT_PRODUCT_ID=... \
python scripts/provider_live_check.py
```

CLI flags are also supported (equivalent to environment variables):

```bash
PYTHONPATH=src python scripts/provider_live_check.py \
  --provider dvsportal \
  --base-url https://parkeren.rijswijk.nl \
  --username ... \
  --password ...
```

Live reservation/favorite flows (requires a license plate). These flows create
and update real reservations/favorites, so use them carefully:

```bash
# Run full create/update/end flows with a fixed wait between steps.
PYTHONPATH=src PROVIDER_ID=dvsportal BASE_URL=https://parkeren.rijswijk.nl \
USERNAME=... PASSWORD=... LICENSE_PLATE=AB12CD \
python scripts/provider_live_check.py --run-all --post-create-wait 5

# Same flow for Amsterdam (client_product_id required), using a license plate.
PYTHONPATH=src PROVIDER_ID=amsterdam BASE_URL=https://api.parkeervergunningen.egisparkingservices.nl \
USERNAME=... PASSWORD=... CLIENT_PRODUCT_ID=... LICENSE_PLATE=AB12CD \
python scripts/provider_live_check.py --run-all --post-create-wait 5

# Run all flows and capture sanitized HTTP payloads/responses to a run file.
PYTHONPATH=src PROVIDER_ID=amsterdam BASE_URL=https://api.parkeervergunningen.egisparkingservices.nl \
USERNAME=... PASSWORD=... LICENSE_PLATE=AB12CD \
python scripts/provider_live_check.py --run-all --dump-json --dump-dir .tmp/http-trace --sanitize-output
```

Notes and behavior details:

- `--start-time` and `--end-time` accept ISO 8601 strings with offset or `Z`.
  If omitted, the script uses next-day 02:00-03:00 in `--timezone`
  (default: `Europe/Amsterdam`).
- Amsterdam requires `client_product_id` (from the JWT).
- Extra credentials can be supplied with `--extra key=value`.
- Credentials can also be supplied via `--credentials-json` or
  `--credentials-file` (or `CREDENTIALS_JSON`/`CREDENTIALS_FILE` env vars).
- The output includes provider capabilities (`favorite_update_fields` and
  `reservation_update_fields`) from `ProviderInfo` so you can confirm supported
  updates before calling mutation methods.

Debug options (sanitized output). These help troubleshoot failing calls without
leaking secrets:

- `--debug-http` prints request/response summaries (method, URL, status) to help
  diagnose network behavior without dumping full payloads.
- `--dump-json` prints sanitized request/response JSON payloads to the terminal,
  useful when you need to see the exact data returned by the provider.
- `--dump-dir <path>` writes sanitized request/response JSON to a single run file
  inside the given directory, making it easy to share one artifact per run.
- `--traceback` prints full Python tracebacks so you can pinpoint the failing
  call path when an error occurs.
- `--sanitize-output` sanitizes privacy-sensitive values in standard output
  (IDs, names, license plates, and known secrets are redacted).

Sanitize an existing dump file:

```bash
python scripts/sanitize.py .tmp/http-trace/20260123-072555-63631.json \
  --output .tmp/http-trace/20260123-072555-63631.sanitized.json
```

Additional sanitize options:

- `--in-place` overwrites the input file with sanitized output (useful for quick
  cleanup before sharing a file).
- `--indent <n>` sets JSON indentation (default: 2) for easier reading or compact
  output.

## Safety reminders

- Never share raw credentials or full license plates.
- Always review sanitized output before posting it in an issue or chat.
- Prefer `--sanitize-output` and `sanitize.py` when collecting logs for support.
