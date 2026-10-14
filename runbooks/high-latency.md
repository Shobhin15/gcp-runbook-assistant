# High API latency

## Symptoms
- p95 latency alert fires in Cloud Monitoring or Grafana
- Users report slow pages while the error rate stays normal

## Check
1. Compare latency against traffic. A traffic spike points to capacity; flat traffic points to a slow dependency.
2. Check CPU and memory for the service. Sustained CPU above 80% means it needs more replicas.
3. Check database latency and slow queries on Cloud SQL.
4. Check recent deployments for a change that matches the start of the slowdown.

## Fix
- Capacity: scale out or raise the autoscaler maximum.
- Slow queries: add the missing index or roll back the query change.
- Bad release: roll back to the previous revision.

## Escalate
- Latency above SLO for 30 minutes, or error budget burn rate alert fires.
