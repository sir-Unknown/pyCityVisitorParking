# Scripts

Helper scripts for manual checks and local validation. These are not part of the
public library API and should not be used in production integrations.

## Contents

- `provider_live_check.py`: Live check against a selected provider.

## Usage

From the repository root:

```bash
API_URI=api USERNAME=... PASSWORD=... \
PYTHONPATH=src PROVIDER_ID=the_hague BASE_URL=https://parkerendenhaag.denhaag.nl \
python scripts/provider_live_check.py

USERNAME=... PASSWORD=... \
PYTHONPATH=src PROVIDER_ID=dvsportal BASE_URL=https://parkeren.rijswijk.nl \
python scripts/provider_live_check.py
```
