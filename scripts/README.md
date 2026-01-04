# Scripts

Helper scripts for manual checks and local validation. These are not part of the
public library API and should not be used in production integrations.

## Contents

- `provider_live_check.py`: Live check against a selected provider.

## Usage

From the repository root:

```bash
PYTHONPATH=src PROVIDER_ID=the_hague BASE_URL=https://parkerendenhaag.denhaag.nl \
USERNAME=... PASSWORD=... \
python scripts/provider_live_check.py

PYTHONPATH=src PROVIDER_ID=dvsportal BASE_URL=https://parkeren.rijswijk.nl \
USERNAME=... PASSWORD=... \
python scripts/provider_live_check.py
```

CLI flags are also supported:

```bash
PYTHONPATH=src python scripts/provider_live_check.py \
  --provider dvsportal \
  --base-url https://parkeren.rijswijk.nl \
  --username ... \
  --password ...
```

Live reservation/favorite flows (requires a license plate):

```bash
PYTHONPATH=src PROVIDER_ID=dvsportal BASE_URL=https://parkeren.rijswijk.nl \
USERNAME=... PASSWORD=... LICENSE_PLATE=AB12CD \
python scripts/provider_live_check.py --run-all --post-create-wait 5
```

Notes:

- `--start-time` and `--end-time` accept ISO 8601 strings with offset or `Z`.
  If omitted, the script uses next-day 02:00-03:00 in `--timezone`
  (default: `Europe/Amsterdam`).
- Extra credentials can be supplied with `--extra key=value`.
- Credentials can also be supplied via `--credentials-json` or
  `--credentials-file` (or `CREDENTIALS_JSON`/`CREDENTIALS_FILE` env vars).
- The output includes provider capabilities (`favorite_update_fields` and
  `reservation_update_fields`) from `ProviderInfo`.
