# Observability and SRE

## Signals

Amaryllis exposes:

- Logs: structured runtime logs with `request_id` and `trace_id`
- Traces: OpenTelemetry spans (if OTel dependencies are installed and enabled)
- Metrics: Prometheus text format at `/service/observability/metrics`
- SLO snapshot: `/service/observability/slo`
- Incident feed: `/service/observability/incidents`

## SLO / SLI

Current targets are configurable via env:

- Request availability target
- Request latency p95 target (ms)
- Run success rate target
- Rolling SLO window

The runtime computes:

- SLI values in-window
- Error budget remaining
- Error budget burn rate

## Incident Detection

Incidents are opened automatically when thresholds are breached (availability, latency p95, run success rate) and recovered automatically when the signal returns within targets.

Key endpoints:

- `GET /service/observability/slo`
- `GET /service/observability/incidents`
- `GET /service/observability/metrics`

## OpenTelemetry

Enable OTel export:

- `AMARYLLIS_OTEL_ENABLED=true`
- `AMARYLLIS_OTEL_OTLP_ENDPOINT=http://collector:4318/v1/traces`

If OTel packages are missing, runtime falls back to local telemetry without crashing.

