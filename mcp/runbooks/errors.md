# Error-rate runbook

## A burst of 5xx errors after a release
Check the change history first. Errors that start at the time of a deployment and affect only the code paths the release touched
point to a regression in that release. A partial error rate (some requests succeed, some fail) suggests a bug that depends on the input.
Rolling back to the previous known-good version is the usual remedy.

## Every request fails the same way, immediately
Failures that are fast, identical and affect every request look like a configuration problem: an invalid setting, a missing value, or a
value out of range. The error text normally names the setting. There is usually no recent code deployment, because the configuration
changed on its own.

## Errors only on requests that call another service
If only endpoints that depend on another service fail, and they fail slowly (a timeout near a fixed value such as 1.5 s) with a message
about that service being unreachable, the dependency is the problem. Local endpoints stay healthy. Restarting this service does not
fix a dependency that is down; check the dependency or fail over.
