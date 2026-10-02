# Climate Control dashboard

`climate-control.yaml` is the complete multi-page Home Assistant dashboard for
Afterburner Helper. It provides a simple climate landing page plus detailed
diesel-heater, thermostat, frost, fuel/mixture, timer, GPIO, and system pages.

Home Assistant does not provide a supported custom-integration API for silently
rewriting a user's dashboard registry or `configuration.yaml`. Consequently the
integration ships the dashboard, but enabling its sidebar entry is an explicit
installation step. This avoids overwriting an existing dashboard with the same
URL and keeps removal predictable.

Copy `climate-control.yaml` to the Home Assistant configuration directory and
add the following to `configuration.yaml`:

```yaml
lovelace:
  dashboards:
    climate-control:
      mode: yaml
      title: Climate Control
      icon: mdi:home-thermometer
      show_in_sidebar: true
      require_admin: false
      filename: climate-control.yaml
```

Restart Home Assistant after validating the configuration.
