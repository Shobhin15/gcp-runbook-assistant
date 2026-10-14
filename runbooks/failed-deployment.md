# Failed deployment

## Symptoms
- CI/CD pipeline fails at the deploy step, or Argo CD shows the app Degraded or OutOfSync
- New pods never become ready

## Check
1. Open the failed pipeline run and read the first error, not the last one.
2. In Argo CD, compare the live and desired manifests to see what changed.
3. Check whether the image tag exists in the container registry.
4. Check readiness probe failures in the new pods' events.

## Fix
- Roll back to the last healthy revision in Argo CD, then fix forward in a new pull request.
- Missing image: rerun the build job that pushes the image.
- Failing probe: confirm the probe path and port match the app.

## Escalate
- Rollback also fails, or the previous revision is unhealthy.
