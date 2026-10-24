# Resource-pressure runbook

## Latency rises everywhere and some requests are refused
When many unrelated endpoints slow down together and some requests are refused with resource or memory errors, the process is short of
resources. Look at error messages that mention memory or capacity, and at whether the problem grows with traffic. Remedies are adding
capacity or restarting to clear a leak; neither is a code rollback unless a recent release introduced the leak.

## Memory errors without a latency step
Occasional memory errors in a short burst may be a spike rather than a sustained shortage. Confirm with repeated measurements before
concluding; a single burst is weak evidence.
