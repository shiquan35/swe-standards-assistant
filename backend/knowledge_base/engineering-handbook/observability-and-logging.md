# Observability and Logging Standards

## 1. Observability goals

Production services SHOULD provide enough telemetry to determine:

- whether the service is available;
- whether users are experiencing errors;
- whether latency is abnormal;
- which requests or operations are failing;
- whether important dependencies are unhealthy.

## 2. Structured logging

Services SHOULD use structured logs for machine-readable operational events.

A log event SHOULD include useful context such as:

- timestamp;
- severity;
- service name;
- environment;
- request or correlation identifier;
- relevant operation name.

## 3. Log levels

Teams SHOULD use log levels consistently.

Typical interpretation:

- `DEBUG` — detailed diagnostic information, normally disabled or limited in production.
- `INFO` — normal significant application events.
- `WARNING` — unexpected condition that does not currently prevent the operation.
- `ERROR` — operation failed and may require investigation.
- `CRITICAL` — severe failure requiring urgent attention.

## 4. Sensitive information

Logs MUST NOT contain passwords, private keys, complete access tokens, or other secrets.

Personal and sensitive data SHOULD be excluded unless there is a justified and approved operational need.

## 5. Correlation identifiers

Distributed applications SHOULD propagate a correlation or trace identifier across service boundaries where supported.

Client-facing error responses MAY include a request identifier that allows support teams to locate corresponding server logs.

## 6. Metrics

Production services SHOULD expose or publish metrics appropriate to their behavior.

Useful service metrics commonly include:

- request rate;
- error rate;
- latency;
- resource saturation;
- queue depth;
- dependency failures.

Business metrics MAY also be monitored where useful.

## 7. Health checks

Long-running services SHOULD expose health information suitable for the hosting platform.

A liveness check SHOULD indicate whether the process needs to be restarted.

A readiness check SHOULD indicate whether the instance is ready to receive traffic.

Health endpoints MUST NOT expose secrets or unnecessary internal details.

## 8. Alerting

Alerts SHOULD correspond to conditions that require human attention or an automated response.

Teams SHOULD avoid alerts that are routinely ignored.

Critical production alerts MUST have an identifiable response owner or escalation path.

## 9. Retention

Log and telemetry retention SHOULD reflect operational, security, compliance, and cost requirements.

There is no single organization-wide log retention period defined by this handbook.
