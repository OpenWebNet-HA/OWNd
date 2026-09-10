# OWNd

This package provides asynchronous event listening, command sessions and message
parsing for the OpenWebNet protocol.

It is mainly intended for use by Home Assistant integrations and other local
OpenWebNet clients.

At this point most events are understood.
WHO = 5 (Burglar Alarm) event support is limited and needs further development.
Many commands are implemented, mostly within the requirements of Home Assistant.

OWNd supports TCP gateways through separate event and command sessions. An
optional serial transport is available for the Legrand 3578 interface. Gateway
profiles expose conservative queue, pacing and session limits for known models.

Python 3.11 or newer is required.

## Testing OWNd

Testing OWNd is pretty simple. 
Clone this repository and then:

```bash
cd <OWNd checkout folder>
pip3 install .
python3 -m OWNd --help    # to visualize possible options
```

Install the optional serial transport with `pip3 install ".[serial]"`.

To attempt connection to the first available OpenWebNet gateway in the local area network you 
can run:

```bash
python3 -m OWNd
```

This will use [SSDP](https://en.wikipedia.org/wiki/Simple_Service_Discovery_Protocol) to discover
all supported gateways and pick the first one.

Alternatively, if you want to skip the SSDP discovery step, you can provide the IP address, port 
and MAC address of the gateway from command-line:

```bash
python3 -m OWNd --address <IP address> --port <PORT> --password <PASS> --mac <MAC address>
```

These details can be retrieved using the BTicino Home+Project application.

## Development

Install the test dependencies and run the same checks used by CI:

```bash
pip3 install -e ".[test]" ruff mypy types-python-dateutil types-pytz
ruff check OWNd tests setup.py
mypy OWNd
python3 -m pytest -q
```
