# General investigation notes

## What evidence is available
Request metrics per endpoint, request logs (including the error message of failed requests), request traces (one record per request),
the deployment and configuration change history, and database query statistics. Anything else (another service's internal health,
network captures, source code) is not available and should not be requested.

## Weighing evidence
Prefer explanations that fit every source. A claim supported by one source only is weak. Note the time a problem started and check
whether anything else changed at that moment. Say plainly when the evidence is thin instead of naming a cause.
