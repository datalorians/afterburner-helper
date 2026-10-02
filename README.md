<div align="center">
  <img src="assets/afterburner-helper.svg" alt="Afterburner Helper logo" width="150">

  # Afterburner Helper

  **Fuel intelligence, flameout detection, and automatic climate control for an Afterburner-equipped diesel heater.**

  [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-custom%20integration-18BCF2?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
  [![Validate](https://github.com/datalorians/afterburner-helper/actions/workflows/validate.yml/badge.svg)](https://github.com/datalorians/afterburner-helper/actions/workflows/validate.yml)
  [![HACS](https://img.shields.io/badge/HACS-custom_repository-41BDF5?logo=homeassistantcommunitystore&logoColor=white)](https://hacs.xyz/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-f5c542.svg)](LICENSE)
  [![AI assisted](https://img.shields.io/badge/development-AI%20assisted-7C3AED)](AI_DISCLOSURE.md)
</div>

> [!NOTE]
> This project complements the community [Afterburner diesel-heater
> controller](https://gitlab.com/mrjones.id.au/bluetoothheater). It is not an
> official Afterburner or Home Assistant project.

## ✨ What it does

- ⛽ Calculates a canonical fuel rate and remaining fuel from pump frequency.
- 💸 Records fuel cost incrementally at the diesel price that applied when the
  fuel was burned, so later price changes do not rewrite history.
- 📐 Supports tank size, pump displacement, calibration correction, and a
  refill-calibration model.
- 🔥 Detects ignition-ramp collapse and low-fire flameout signatures from live
  heater telemetry.
- 🛟 Can perform one bounded low-fire recovery attempt, then restore the prior
  demand or request a normal shutdown.
- 🌡️ Provides automatic stop/start cycling around the desired temperature with
  configurable offsets, hold times, minimum run/off times, and cooldown checks.
- 🛑 Preserves an intentional manual stop until a later setpoint change enters
  the configured start range.
- 🏠 Includes an optional phone-presence Home/Away climate package with a guest
  override and departure delay.
- 📊 Exposes Home Assistant sensors suitable for Recorder, InfluxDB, and Grafana.

## 🧭 Project status

The integration is actively developed against a real Afterburner V3.5.2 setup.
Its dependency-free control and fuel suite currently contains 23 tests,
including recorded failed-start, flameout, and successful overnight-run cases.

This is an early public release. Entity names and configuration options may
change while the migration from older YAML helpers is completed.

## 🚀 Installation

### HACS custom repository

1. Open HACS in Home Assistant.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add `https://github.com/datalorians/afterburner-helper` as an
   **Integration** repository.
4. Install **Afterburner Helper** and restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration**, search for
   **Afterburner Helper**, and complete the configuration flow.

### Manual installation

Copy `custom_components/afterburner_helper` into your Home Assistant
`/config/custom_components/` directory, then restart Home Assistant and add the
integration from **Settings → Devices & services**.

## 🔌 Expected data sources

Afterburner Helper reads entities exposed by Afterburner's MQTT discovery,
including room temperature, requested temperature, heat-exchanger temperature,
pump frequency, fan speed, run state, error state, input voltage, fuel usage,
and the Afterburner climate entity.

The configuration flow allows the relevant source entities and control limits
to be selected. Do not assume another installation uses the same entity IDs as
the included examples.

## 🧠 Control behaviour

The optional active controller works with the stock heater ECU and normal
Afterburner commands:

```text
room reaches setpoint + stop offset
              │
              ▼
minimum-fire hold ──► normal ECU shutdown ──► full cooldown
                                                 │
room reaches setpoint - start offset             │
              └──────────────────────────────────┘
                              │
                              ▼
                       normal ECU start
```

Active control is configurable and can be disabled. The integration never
automatically primes the fuel pump and does not replace the stock ECU shutdown
sequence.

## 🏠 Optional occupancy control

[`examples/diesel_heater_occupancy.yaml`](examples/diesel_heater_occupancy.yaml)
provides an example Home Assistant package that:

- restores the Home temperature immediately when a tracked `person` arrives;
- applies an Away temperature after a configurable delay;
- provides enable and guest-mode switches; and
- exposes Home, Away, and delay settings for a dashboard card.

Change `person.your_name` and any entity IDs to match your installation before
using the example.

## 📊 Dashboards and analytics

Starter Lovelace configuration is available in
[`examples/dashboard_cards.yaml`](examples/dashboard_cards.yaml). The exposed
measurements can also be retained by Home Assistant Recorder or exported to
InfluxDB for Grafana dashboards and long-range analysis.

## 🧪 Development

Run the core test suite without a Home Assistant development environment:

```bash
python3 -m unittest discover -s tests -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for validation commands and contribution
guidelines.

## 🤖 AI disclosure

This project has been developed with substantial generative-AI assistance under
human direction and hardware supervision. The full disclosure and expectations
for AI-assisted contributions are documented in
[AI_DISCLOSURE.md](AI_DISCLOSURE.md).

## ⚖️ License

Afterburner Helper is open source under the permissive [MIT License](LICENSE).

## 🙏 Acknowledgements

- [Afterburner / Bluetooth Heater](https://gitlab.com/mrjones.id.au/bluetoothheater)
  by Ray Jones and contributors.
- The Home Assistant, HACS, InfluxDB, and Grafana communities.
- Operators who contribute sanitized heater telemetry and real-world test
  results.
