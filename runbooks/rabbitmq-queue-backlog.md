# RabbitMQ queue backlog

## Symptoms
- Queue depth keeps growing in the RabbitMQ management UI
- Unacknowledged messages climb and consumers fall behind
- Downstream services report delayed processing

## Check
1. Open the RabbitMQ management UI and find the queue with the growing depth.
2. Check the consumer count for that queue. Zero or fewer consumers than usual points to the consumer pods.
3. In Argo CD, open the consumer application and check pod status and restarts.
4. Read the consumer pod logs for errors, timeouts, or a poison message that keeps failing.

## Fix
- If consumer pods are crash-looping, fix the cause from the logs, then let Argo CD sync the healthy version.
- If consumers are healthy but slow, scale the consumer deployment up temporarily.
- If one message keeps failing, move it to the dead-letter queue so the rest can drain.

## Escalate
- Queue depth still rising 15 minutes after mitigation, or messages are being lost.
