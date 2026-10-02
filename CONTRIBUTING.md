# Contributing

Issues, field data, documentation improvements, and pull requests are welcome.

## Development setup

The fuel and control-state logic has dependency-free unit tests:

```bash
python3 -m unittest discover -s tests -v
```

Before opening a pull request, also validate the integration JSON files and
compile the Python sources:

```bash
python3 -m json.tool custom_components/afterburner_helper/manifest.json >/dev/null
python3 -m json.tool custom_components/afterburner_helper/strings.json >/dev/null
python3 -m json.tool custom_components/afterburner_helper/translations/en.json >/dev/null
python3 -m compileall -q custom_components tests
```

Please include the relevant Home Assistant version, Afterburner version,
heater/controller details, and sanitized telemetry when reporting a bug.

See [AI_DISCLOSURE.md](AI_DISCLOSURE.md) for the contribution expectations for
AI-assisted work.

