# Latency runbook

## Requests are slow but nothing is failing
Slow responses with a normal error rate usually mean extra work on the request path, not a crash. Compare latency before and after a
clear step: a sudden step change (for example from about 1 ms to a few hundred ms) that stays constant points to a new fixed cost,
such as a slower data store, a lock, or a new synchronous call. A slow drift points to growth in data or load. Check the database
statistics for per-query time, then the recent change history for anything that landed around the onset time.

## One endpoint is slow, others are fine
Look at what only that endpoint does differently: a particular query, a call to another service, or a code path touched by a recent release.
Slow health and metrics endpoints at the same time suggest the whole process is struggling, not one dependency.

## Every endpoint is slower together
A uniform slowdown across unrelated endpoints suggests shared resource pressure: CPU, memory, the connection pool, or a noisy neighbour.
Look for requests that are refused or fail with resource errors, and for latency growing with traffic.
