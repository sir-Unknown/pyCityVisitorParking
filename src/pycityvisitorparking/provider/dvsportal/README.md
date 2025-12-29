# DVS Portal

DVS Portal provider for visitor parking systems using the reverse engineered
DVS Portal API.

## Service name

- Official service name: DVS Portal (reverse engineered).

## Configuration

Home Assistant supplies `base_url` and optional `api_uri`. This provider expects
credentials with the following keys:

- `identifier` (string, required)
- `password` (string, required)
- `permit_media_type_id` (string, optional)

If `permit_media_type_id` is omitted, the provider selects the first entry from
`GET /login`.

Example credential shape:

```python
{
    "identifier": "user-123",
    "password": "secret",
    "permit_media_type_id": "1",
}
```

## Municipalities using DVS Portal

The following municipalities are known to use DVS Portal endpoints with the
listed `base_url` and `api_uri` values:

| Municipality          | base_url                                                                             | api_uri              |
| --------------------- | ------------------------------------------------------------------------------------ | -------------------- |
| Apeldoorn             | [https://parkeren.apeldoorn.nl](https://parkeren.apeldoorn.nl)                       | /DVSWebAPI/api/login |
| Bloemendaal           | [https://parkeren.bloemendaal.nl](https://parkeren.bloemendaal.nl)                   | /DVSWebAPI/api/login |
| Delft                 | [https://vergunningen.parkerendelft.com](https://vergunningen.parkerendelft.com)     | /DVSWebAPI/api/login |
| Den Bosch             | [https://parkeren.s-hertogenbosch.nl](https://parkeren.s-hertogenbosch.nl)           | /DVSWebAPI/api/login |
| Doetinchem (via Buha) | [https://parkeren.buha.nl](https://parkeren.buha.nl)                                 | /DVSWebAPI/api/login |
| Groningen             | [https://aanvraagparkeren.groningen.nl](https://aanvraagparkeren.groningen.nl)       | /DVSWebAPI/api/login |
| Haarlem               | [https://parkeren.haarlem.nl](https://parkeren.haarlem.nl)                           | /DVSWebAPI/api/login |
| Harlingen             | [https://parkeervergunningen.harlingen.nl](https://parkeervergunningen.harlingen.nl) | /DVSWebAPI/api/login |
| Heemstede             | [https://parkeren.heemstede.nl](https://parkeren.heemstede.nl)                       | /DVSWebAPI/api/login |
| Heerenveen            | [https://parkeren.heerenveen.nl](https://parkeren.heerenveen.nl)                     | /DVSWebAPI/api/login |
| Heerlen               | [https://parkeren.heerlen.nl](https://parkeren.heerlen.nl)                           | /DVSWebAPI/api/login |
| Hengelo               | [https://parkeren.hengelo.nl](https://parkeren.hengelo.nl)                           | /DVSWebAPI/api/login |
| Katwijk               | [https://parkeren.katwijk.nl](https://parkeren.katwijk.nl)                           | /DVSWebAPI/api/login |
| Leiden                | [https://parkeren.leiden.nl](https://parkeren.leiden.nl)                             | /DVSWebAPI/api/login |
| Leidschendam-Voorburg | [https://parkeren.lv.nl](https://parkeren.lv.nl)                                     | /DVSWebAPI/api/login |
| Middelburg            | [https://parkeren.middelburg.nl](https://parkeren.middelburg.nl)                     | /DVSWebAPI/api/login |
| Nissewaard            | [https://parkeren.nissewaard.nl](https://parkeren.nissewaard.nl)                     | /DVSWebAPI/api/login |
| Oldenzaal             | [https://parkeren.oldenzaal.nl](https://parkeren.oldenzaal.nl)                       | /DVSWebAPI/api/login |
| Rijswijk              | [https://parkeren.rijswijk.nl](https://parkeren.rijswijk.nl)                         | /DVSWebAPI/api/login |
| Roermond              | [https://parkeren.roermond.nl](https://parkeren.roermond.nl)                         | /DVSWebAPI/api/login |
| Schouwen-Duiveland    | [https://parkeren.schouwen-duiveland.nl](https://parkeren.schouwen-duiveland.nl)     | /DVSWebAPI/api/login |
| Sittard-Geleen        | [https://parkeren.sittard-geleen.nl](https://parkeren.sittard-geleen.nl)             | /DVSWebAPI/api/login |
| Smallingerland        | [https://parkeren.smallingerland.nl](https://parkeren.smallingerland.nl)             | /DVSWebAPI/api/login |
| Súdwest-Fryslân       | [https://parkeren.sudwestfryslan.nl](https://parkeren.sudwestfryslan.nl)             | /DVSWebAPI/api/login |
| Veere                 | [https://parkeren.veere.nl](https://parkeren.veere.nl)                               | /DVSWebAPI/api/login |
| Venlo                 | [https://parkeren.venlo.nl](https://parkeren.venlo.nl)                               | /DVSWebAPI/api/login |
| Vlissingen            | [https://parkeren.vlissingen.nl](https://parkeren.vlissingen.nl)                     | /DVSWebAPI/api/login |
| Waadhoeke             | [https://parkeren.waadhoeke.nl](https://parkeren.waadhoeke.nl)                       | /DVSWebAPI/api/login |
| Waalwijk              | [https://parkeren.waalwijk.nl](https://parkeren.waalwijk.nl)                         | /DVSWebAPI/api/login |
| Weert                 | [https://parkeerloket.weert.nl](https://parkeerloket.weert.nl)                       | /DVSWebAPI/api/login |
| Zaanstad              | [https://parkeren.zaanstad.nl](https://parkeren.zaanstad.nl)                         | /DVSWebAPI/api/login |
| Zevenaar              | [https://parkeren.zevenaar.nl](https://parkeren.zevenaar.nl)                         | /DVSWebAPI/api/login |
| Zutphen               | [https://parkeren.zutphen.nl](https://parkeren.zutphen.nl)                           | /DVSWebAPI/api/login |
| Zwolle                | [https://parkeerloket.zwolle.nl](https://parkeerloket.zwolle.nl)                     | /DVSWebAPI/api/login |

## Supported operations

- `login`
- `get_permit`
- `list_reservations`
- `start_reservation` (requires `start_time` and `end_time`)
- `end_reservation`
- `list_favorites`
- `add_favorite`
- `remove_favorite`

Unsupported:

- Reservation updates (`update_reservation`)
- Native favorite updates (`update_favorite` uses remove + add fallback)

## Migration notes

- Since v0.3.0, `Permit.remaining_time` is renamed to `Permit.remaining_balance`
  (minutes). Update integrations that read the permit balance.

## Mapping notes

- Permit selection uses the first `Permit`/`Permits[0]` and `PermitMedias[0]`.
- `Permit.id` uses `PermitMedias[0].Code` (fallback to `ZoneCode`).
- `Permit.remaining_balance` uses `PermitMedias[0].Balance`.
- `Permit.zone_validity` includes only chargeable `BlockTimes` where
  `IsFree` is not `true`.
- Reservations come from `PermitMedias[0].ActiveReservations`.
- Favorites come from `PermitMedias[0].LicensePlates`.

## Time handling

Provider timestamps are converted to UTC and returned as ISO 8601 with `Z` and
no microseconds. When the API omits timezone offsets, timestamps are interpreted
as Europe/Amsterdam local time before conversion.

## License plate normalization

License plates are normalized to uppercase `A-Z0-9` without spaces or special
characters.

## Limitations

- Only the first permit and permit media are used.
- Reservation updates are not supported.
- Favorite updates rely on the core remove + add fallback.

## Links

No official public documentation is available for this reverse engineered API.
