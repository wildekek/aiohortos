# aiohortos

Async Python client for the **Ridder HortOS Automation API**, the cloud API
behind [HortiMaX](https://www.ridder.com/) greenhouse process controllers.

> **This is a community-built library. It is not an official Ridder product,
> it is not certified by Ridder, and Ridder does not support it.** Ridder's
> support covers the HortOS Automation API itself; anything about this
> library belongs on its
> [issue tracker](https://github.com/wildekek/aiohortos/issues).
>
> The API is still evolving and Ridder does not guarantee backward
> compatibility for community integrations, so a future API change can alter
> or remove what this library returns. Pin a version.

The library is **read-only**: it authenticates with an API key and reads
controllers, their health, and their readouts. It never writes setpoints.

```bash
pip install aiohortos
```

## Usage

```python
import asyncio

from aiohortos import HortosClient


async def main() -> None:
    async with HortosClient("your-api-key") as client:
        for device in await client.get_devices():
            print(device.name, device.label)
            for readout in await client.get_latest_readouts(device.name):
                print(
                    f"  {readout.source.display_name}: "
                    f"{readout.identifier} = {readout.value} {readout.unit or ''}"
                )


asyncio.run(main())
```

Pass an existing session to share a connection pool — which is what you want
inside an application that already has one:

```python
async with aiohttp.ClientSession() as session:
    client = HortosClient("your-api-key", session=session)
```

The client also accepts a `base_url`, for on-premise HortOS installations that
serve the same API from your own network.

## API surface

| Method | Returns |
| --- | --- |
| `authenticate()` | `TokenPair` — normally not needed; every call authenticates on demand |
| `get_device_names()` | `list[str]` of controller identifiers |
| `get_devices()` | `list[Device]` with the friendly label |
| `get_devices_health()` | `list[DeviceHealth]` — online state, sync state |
| `get_readout_definitions(device)` | `list[ReadoutDefinition]` |
| `get_latest_readouts(device)` | `list[Readout]` with the newest value each |
| `get_readout_history(...)` | `list[ReadoutValue]` over a window of ≤ 24 hours |

Errors all derive from `HortosError`:

- `HortosAuthenticationError` — the API key or token was rejected (HTTP 401/403)
- `HortosConnectionError` — the API could not be reached, or timed out
- `HortosResponseError` — an unexpected status or payload, with `.status`

## Notes on the API

- Tokens live 15 minutes and are renewed with a refresh token valid 7 days.
  The client handles both, and re-authenticates when a token is rejected.
- The API allows **100 requests per 15 seconds** per key. The library does not
  throttle; pace your own polling.
- A controller publishes its changed readouts in a batch about once a minute;
  a readout whose value does not change keeps its old timestamp for up to 5
  minutes. Polling faster than once a minute gains nothing, polling slower
  drops updates. (Measured on a Multima: ~55–65 of 621 readouts carried a new
  value in each 60s batch, the rest were unchanged over 5 minutes.)
- Readout identifiers follow `<CamelCaseSubject>-<Kind>`, e.g.
  `VentPositionLeewardSide-Measured`. One upstream typo exists in the wild:
  `IrrigationVolume-Measuered`.
- Some readouts have `unitIdentifier: "Scalar"` and a numeric value that is
  really an enumeration member id from a table the API does not expose. They
  are returned as-is. `CardinalWindDirection` is the one decoded so far:

  ```python
  from aiohortos import decode_cardinal_wind_direction

  decode_cardinal_wind_direction(8783)  # 247.5, i.e. WSW
  decode_cardinal_wind_direction(1234)  # None — not a member of the table
  ```

  The 16 compass points occupy contiguous ids 8772–8787 on a HortiMaX
  controller, clockwise in 22.5° steps, confirmed over a day of history and
  cross-checked against the official app. Anything outside that block, or
  not a whole number, decodes to `None` rather than to a plausible bearing.
- `Readout.name` embeds the source's user-defined name and is a poor label on
  its own — build names from `identifier` and `source` instead.

Ridder's Swagger UI documents the API at
<https://hortos.ridder.com/api/process-control/index.html>. The OpenAPI
document lives at `{base_url}/v1/swagger.json` and needs a bearer token.

## Development

```bash
uv venv && uv pip install -e . --group dev
pytest
ruff check . && ruff format --check . && mypy src
```

## Disclaimer

This library is not affiliated with, endorsed by, or certified by Ridder, and
carries no warranty. "Ridder", "HortOS" and "HortiMaX" are used only to name
the API and the products this library talks to; they are trademarks of their
respective owner.
