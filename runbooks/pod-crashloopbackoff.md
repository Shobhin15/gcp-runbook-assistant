# Pod in CrashLoopBackOff

## Symptoms
- kubectl get pods shows CrashLoopBackOff and a rising restart count
- Readiness probe failures and alerts for unavailable replicas

## Check
1. kubectl describe pod <pod> -n <namespace> and read the Events section.
2. kubectl logs <pod> -n <namespace> --previous to see why the last container exited.
3. Look for OOMKilled in the last state. That means the memory limit is too low or there is a leak.
4. Check whether a new image or config change was deployed just before the crashes started.

## Fix
- Bad release: roll back to the previous revision in Argo CD (or kubectl rollout undo).
- OOMKilled: raise the memory limit in the Helm values and redeploy, then investigate the leak.
- Missing config or secret: restore it, then restart the deployment.

## Escalate
- More than one service crash-looping at once, which may mean a cluster or node problem.
