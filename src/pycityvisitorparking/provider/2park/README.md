# 2park Provider

Provider for the [2park](https://mijn.2park.nl) visitor parking platform used by Dutch municipalities.

## Supported municipalities

2park is used by a number of Dutch municipalities. The provider auto-detects the
parking product and location from the account after login. All municipalities use
`https://mijn.2park.nl` as the base URL.

Known municipalities (non-exhaustive):

Amstelveen, Assen, Bergen op Zoom, Breda, Deventer, Dordrecht, Eindhoven, Emmen,
Etten-Leur, Hardenberg, Harderwijk, Hilversum, Maastricht, Oosterhout, Oss,
Roosendaal, Terneuzen, Tiel, Veenendaal, Vlaardingen

Check [mijn.2park.nl](https://mijn.2park.nl) for the current list of supported municipalities.

## Configuration

| Field          | Required | Description |
|----------------|----------|-------------|
| `base_url`     | Yes      | Always `https://mijn.2park.nl` |
| `username`     | Yes      | Your 2park account email address |
| `password`     | Yes      | Your 2park account password |
| `product_id`   | No       | Product ID to use (auto-detected if omitted) |
| `location`     | No       | Parking location code (auto-detected if omitted) |

When you have a single parking product on your account, `product_id` and `location`
can be omitted and are detected automatically at login. If you have multiple products,
pass the `product_id` of the product you want to use.

## Capabilities

| Operation              | Supported |
|------------------------|-----------|
| `get_permit`           | Yes       |
| `list_reservations`    | Yes       |
| `start_reservation`    | Yes       |
| `update_reservation`   | No        |
| `end_reservation`      | Yes       |
| `list_favorites`       | Yes (read-only) |
| `add_favorite`         | No        |
| `update_favorite`      | No        |
| `remove_favorite`      | No        |

`zone_validity` is not provided by this API and is always an empty list.

`remaining_balance` reflects the raw AMOUNT value from the balance response
(typically in minutes for visitor parking products).

## Example

```python
import asyncio
from pycityvisitorparking import Client

async def main() -> None:
    async with Client(base_url="https://mijn.2park.nl") as client:
        provider = await client.get_provider("2park")
        await provider.login(credentials={"username": "user@example.com", "password": "secret"})
        permit = await provider.get_permit()
        print(permit.id, permit.remaining_balance)

asyncio.run(main())
```

## Reference

API behaviour was derived from [hrietman/2park](https://github.com/hrietman/2park),
an open-source Home Assistant integration for 2park (no license declared).
