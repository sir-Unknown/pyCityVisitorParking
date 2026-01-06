# DVS Portal

DVS Portal provider for visitor parking systems using the reverse engineered
DVS Portal API.

## Service name

- Official service name: DVS Portal (reverse engineered).

## Configuration

Home Assistant supplies `base_url` and optional `api_uri`. This provider expects
credentials with the following keys:

- `username` (string, required)
- `password` (string, required)
- `permit_media_type_id` (string, optional)

If `api_uri` is omitted, the provider defaults to `/DVSWebAPI/api`.
If `permit_media_type_id` is omitted, the provider selects the first entry from
`GET /login`.

Example credential shape:

```python
{
    "username": "user-123",
    "password": "secret",
    "permit_media_type_id": "1",
}
```

## Municipalities using DVS Portal

The following municipalities are known to use DVS Portal endpoints with the
listed `base_url` and `api_uri` values:

| Municipality          | base_url                                                                             | api_uri              |
| --------------------- | ------------------------------------------------------------------------------------ | -------------------- |
| Apeldoorn             | [https://parkeren.apeldoorn.nl](https://parkeren.apeldoorn.nl)                       | /DVSWebAPI/api |
| Bloemendaal           | [https://parkeren.bloemendaal.nl](https://parkeren.bloemendaal.nl)                   | /DVSWebAPI/api |
| Delft                 | [https://vergunningen.parkerendelft.com](https://vergunningen.parkerendelft.com)     | /DVSWebAPI/api |
| Den Bosch             | [https://parkeren.s-hertogenbosch.nl](https://parkeren.s-hertogenbosch.nl)           | /DVSWebAPI/api |
| Doetinchem (via Buha) | [https://parkeren.buha.nl](https://parkeren.buha.nl)                                 | /DVSWebAPI/api |
| Groningen             | [https://aanvraagparkeren.groningen.nl](https://aanvraagparkeren.groningen.nl)       | /DVSWebAPI/api |
| Haarlem               | [https://parkeren.haarlem.nl](https://parkeren.haarlem.nl)                           | /DVSWebAPI/api |
| Harlingen             | [https://parkeervergunningen.harlingen.nl](https://parkeervergunningen.harlingen.nl) | /DVSWebAPI/api |
| Heemstede             | [https://parkeren.heemstede.nl](https://parkeren.heemstede.nl)                       | /DVSWebAPI/api |
| Heerenveen            | [https://parkeren.heerenveen.nl](https://parkeren.heerenveen.nl)                     | /DVSWebAPI/api |
| Heerlen               | [https://parkeren.heerlen.nl](https://parkeren.heerlen.nl)                           | /DVSWebAPI/api |
| Hengelo               | [https://parkeren.hengelo.nl](https://parkeren.hengelo.nl)                           | /DVSWebAPI/api |
| Katwijk               | [https://parkeren.katwijk.nl](https://parkeren.katwijk.nl)                           | /DVSWebAPI/api |
| Leiden                | [https://parkeren.leiden.nl](https://parkeren.leiden.nl)                             | /DVSWebAPI/api |
| Leidschendam-Voorburg | [https://parkeren.lv.nl](https://parkeren.lv.nl)                                     | /DVSWebAPI/api |
| Middelburg            | [https://parkeren.middelburg.nl](https://parkeren.middelburg.nl)                     | /DVSWebAPI/api |
| Nissewaard            | [https://parkeren.nissewaard.nl](https://parkeren.nissewaard.nl)                     | /DVSWebAPI/api |
| Oldenzaal             | [https://parkeren.oldenzaal.nl](https://parkeren.oldenzaal.nl)                       | /DVSWebAPI/api |
| Rijswijk              | [https://parkeren.rijswijk.nl](https://parkeren.rijswijk.nl)                         | /DVSWebAPI/api |
| Roermond              | [https://parkeren.roermond.nl](https://parkeren.roermond.nl)                         | /DVSWebAPI/api |
| Schouwen-Duiveland    | [https://parkeren.schouwen-duiveland.nl](https://parkeren.schouwen-duiveland.nl)     | /DVSWebAPI/api |
| Sittard-Geleen        | [https://parkeren.sittard-geleen.nl](https://parkeren.sittard-geleen.nl)             | /DVSWebAPI/api |
| Smallingerland        | [https://parkeren.smallingerland.nl](https://parkeren.smallingerland.nl)             | /DVSWebAPI/api |
| Súdwest-Fryslân       | [https://parkeren.sudwestfryslan.nl](https://parkeren.sudwestfryslan.nl)             | /DVSWebAPI/api |
| Veere                 | [https://parkeren.veere.nl](https://parkeren.veere.nl)                               | /DVSWebAPI/api |
| Venlo                 | [https://parkeren.venlo.nl](https://parkeren.venlo.nl)                               | /DVSWebAPI/api |
| Vlissingen            | [https://parkeren.vlissingen.nl](https://parkeren.vlissingen.nl)                     | /DVSWebAPI/api |
| Waadhoeke             | [https://parkeren.waadhoeke.nl](https://parkeren.waadhoeke.nl)                       | /DVSWebAPI/api |
| Waalwijk              | [https://parkeren.waalwijk.nl](https://parkeren.waalwijk.nl)                         | /DVSWebAPI/api |
| Weert                 | [https://parkeerloket.weert.nl](https://parkeerloket.weert.nl)                       | /DVSWebAPI/api |
| Zaanstad              | [https://parkeren.zaanstad.nl](https://parkeren.zaanstad.nl)                         | /DVSWebAPI/api |
| Zevenaar              | [https://parkeren.zevenaar.nl](https://parkeren.zevenaar.nl)                         | /DVSWebAPI/api |
| Zutphen               | [https://parkeren.zutphen.nl](https://parkeren.zutphen.nl)                           | /DVSWebAPI/api |
| Zwolle                | [https://parkeerloket.zwolle.nl](https://parkeerloket.zwolle.nl)                     | /DVSWebAPI/api |

## Supported operations

- `login`
- `get_permit`
- `list_reservations`
- `start_reservation` (requires `start_time` and `end_time`)
- `update_reservation` (end time only)
- `end_reservation`
- `list_favorites`
- `add_favorite`
- `remove_favorite`

Unsupported:

- Favorite updates (`update_favorite`)

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

## Favorite payloads

- Upsert sends `permitMediaTypeID`, `permitMediaCode`, `licensePlate` object, and `name`.
- Remove sends `permitMediaTypeID`, `permitMediaCode`, `licensePlate` string, and `name`.
  The client uses the stored favorite name when available and falls back to the
  normalized license plate when no name is available.

## Reservation update payloads

- Updates use `reservation/update` with `Minutes` (delta from the current end time),
  `ReservationID`, `permitMediaTypeID`, and `permitMediaCode`.
- The provider calculates `Minutes` by comparing the requested `end_time` with the
  existing reservation end time. Positive values extend the reservation and
  negative values shorten it.
- `end_time` must align to whole minutes; second-level precision is rejected.

## Time handling

Provider timestamps are converted to UTC and returned as ISO 8601 with `Z` and
no microseconds. When the API omits timezone offsets, timestamps are interpreted
as Europe/Amsterdam local time before conversion. DST transitions are resolved
deterministically using fold=0 for ambiguous or non-existent local times.
Reservation creation payloads must use Europe/Amsterdam local time with
milliseconds and an explicit offset (for example,
`2026-01-02T23:57:00.000+01:00`); the public API accepts timezone-aware
`datetime` values and returns UTC strings.

Outbound format contract (`reservation/create`):
- `DateFrom` and `DateUntil` must be strings in `YYYY-MM-DDTHH:mm:ss.SSS±HH:MM`.
- The offset must reflect Europe/Amsterdam (`+01:00` or `+02:00` in DST).
- Other required fields in the same payload: `LicensePlate`, `permitMediaTypeID`,
  and `permitMediaCode`.

Inbound parsing contract (base model):
- `ActiveReservations.ValidFrom`/`ValidUntil` and `BlockTimes.ValidFrom`/`ValidUntil`
  may include offsets; if present, respect them.
- If no offset is present, interpret the timestamp as Europe/Amsterdam local time.

## License plate normalization

License plates are normalized to uppercase `A-Z0-9` without spaces or special
characters.

## Limitations

- Only the first permit and permit media are used.
- Reservation updates can adjust the end time only.
- Favorite updates are not supported.

## Links

No official public documentation is available for this reverse engineered API.
