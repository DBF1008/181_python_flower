import logging

from tornado import web

from . import BaseApiHandler

logger = logging.getLogger(__name__)


class ControlHandler(BaseApiHandler):
    def is_worker(self, workername):
        return bool(workername) and workername in self.application.workers

    def require_worker(self, workername):
        "raises 404 if workername is not a currently known worker"
        if not self.is_worker(workername):
            raise web.HTTPError(404, f"Unknown worker '{workername}'")

    def reply_for_worker(self, response, workername):
        """Extract a single worker's payload from a ``reply=True`` control
        response.

        Returns ``None`` when the response is empty/``None`` or the worker
        did not answer -- this is what no reply, a partial failure, or a
        worker that died after validation all look like in the reply list.
        """
        for reply in response or []:
            if isinstance(reply, dict) and workername in reply:
                return reply[workername]
        return None

    @staticmethod
    def is_ok(payload):
        "a worker payload is successful when it carries an 'ok' marker"
        if isinstance(payload, dict):
            return 'ok' in payload
        return payload == 'ok'

    def error_reason(self, workername, response):
        "extracts the error message a worker returned, with a safe fallback"
        payload = self.reply_for_worker(response, workername)
        if isinstance(payload, dict) and payload.get('error'):
            return payload['error']
        if isinstance(payload, str) and payload not in ('', 'ok'):
            return payload
        logger.error("Failed to extract error reason from '%s'", response)
        return 'Unknown reason'

    def write_control_response(self, response, workername, *,
                               success_message=None, failure_message):
        """Single response-handling path shared by every reply-bearing
        control command, so all entry points behave identically:

        * worker replied ok    -> 200, JSON ``{"message": ...}``
        * worker replied error -> 403, text ``"<failure_message>: '<reason>'"``
        * no reply from worker -> 504, text ``"No response from worker '<name>'"``
          (covers empty/``None`` responses, dead workers, and partial
          failures where this worker is absent from the reply)

        ``success_message`` is the text written on success; when it is
        ``None`` the worker's own ``ok`` message is echoed instead (used by
        add/cancel-consumer and the task time/rate limits).
        """
        payload = self.reply_for_worker(response, workername)
        if payload is None:
            logger.error("No reply from '%s' worker: %s", workername, response)
            self.set_status(504)
            self.write(f"No response from worker '{workername}'")
            return
        if self.is_ok(payload):
            if success_message is None:
                success_message = payload.get('ok', '') if isinstance(payload, dict) else ''
            self.write(dict(message=success_message))
            return
        logger.error("Control command failed for '%s' worker: %s",
                     workername, response)
        self.set_status(403)
        reason = self.error_reason(workername, response)
        self.write(f"{failure_message}: '{reason}'")


class WorkerShutDown(ControlHandler):
    @web.authenticated
    def post(self, workername):
        """
Shut down a worker

**Example request**:

.. sourcecode:: http

  POST /api/worker/shutdown/celery@worker2 HTTP/1.1
  Content-Length: 0
  Host: localhost:5555

**Example response**:

.. sourcecode:: http

  HTTP/1.1 200 OK
  Content-Length: 29
  Content-Type: application/json; charset=UTF-8

  {
      "message": "Shutting down!"
  }

:reqheader Authorization: optional OAuth token to authenticate
:statuscode 200: no error
:statuscode 401: unauthorized request
:statuscode 404: unknown worker
        """
        self.require_worker(workername)

        logger.info("Shutting down '%s' worker", workername)
        self.capp.control.broadcast('shutdown', destination=[workername])
        self.write(dict(message="Shutting down!"))


class WorkerPoolRestart(ControlHandler):
    @web.authenticated
    def post(self, workername):
        """
Restart worker's pool

**Example request**:

.. sourcecode:: http

  POST /api/worker/pool/restart/celery@worker2 HTTP/1.1
  Content-Length: 0
  Host: localhost:5555

**Example response**:

.. sourcecode:: http

  HTTP/1.1 200 OK
  Content-Length: 56
  Content-Type: application/json; charset=UTF-8

  {
      "message": "Restarting 'celery@worker2' worker's pool"
  }

:reqheader Authorization: optional OAuth token to authenticate
:statuscode 200: no error
:statuscode 401: unauthorized request
:statuscode 403: pool restart is not enabled (see CELERYD_POOL_RESTARTS)
:statuscode 404: unknown worker
        """
        self.require_worker(workername)

        logger.info("Restarting '%s' worker's pool", workername)
        response = self.capp.control.broadcast(
            'pool_restart', arguments={'reload': False},
            destination=[workername], reply=True)
        self.write_control_response(
            response, workername,
            success_message=f"Restarting '{workername}' worker's pool",
            failure_message=f"Failed to restart the '{workername}' pool")


class WorkerPoolGrow(ControlHandler):
    @web.authenticated
    def post(self, workername):
        """
Grow worker's pool

**Example request**:

.. sourcecode:: http

  POST /api/worker/pool/grow/celery@worker2?n=3 HTTP/1.1
  Content-Length: 0
  Host: localhost:5555

**Example response**:

.. sourcecode:: http

  HTTP/1.1 200 OK
  Content-Length: 58
  Content-Type: application/json; charset=UTF-8

  {
      "message": "Growing 'celery@worker2' worker's pool by 3"
  }

:query n: number of pool processes to grow, default is 1
:reqheader Authorization: optional OAuth token to authenticate
:statuscode 200: no error
:statuscode 401: unauthorized request
:statuscode 403: failed to grow
:statuscode 404: unknown worker
        """

        self.require_worker(workername)

        n = self.get_argument('n', default=1, type=int)

        logger.info("Growing '%s' worker's pool by '%s'", workername, n)
        response = self.capp.control.pool_grow(
            n=n, reply=True, destination=[workername])
        self.write_control_response(
            response, workername,
            success_message=f"Growing '{workername}' worker's pool by {n}",
            failure_message=f"Failed to grow '{workername}' worker's pool")


class WorkerPoolShrink(ControlHandler):
    @web.authenticated
    def post(self, workername):
        """
Shrink worker's pool

**Example request**:

.. sourcecode:: http

  POST /api/worker/pool/shrink/celery@worker2 HTTP/1.1
  Content-Length: 0
  Host: localhost:5555

**Example response**:

.. sourcecode:: http

  HTTP/1.1 200 OK
  Content-Length: 60
  Content-Type: application/json; charset=UTF-8

  {
      "message": "Shrinking 'celery@worker2' worker's pool by 1"
  }

:query n: number of pool processes to shrink, default is 1
:reqheader Authorization: optional OAuth token to authenticate
:statuscode 200: no error
:statuscode 401: unauthorized request
:statuscode 403: failed to shrink
:statuscode 404: unknown worker
        """

        self.require_worker(workername)

        n = self.get_argument('n', default=1, type=int)

        logger.info("Shrinking '%s' worker's pool by '%s'", workername, n)
        response = self.capp.control.pool_shrink(
            n=n, reply=True, destination=[workername])
        self.write_control_response(
            response, workername,
            success_message=f"Shrinking '{workername}' worker's pool by {n}",
            failure_message=f"Failed to shrink '{workername}' worker's pool")


class WorkerPoolAutoscale(ControlHandler):
    @web.authenticated
    def post(self, workername):
        """
Autoscale worker pool

**Example request**:

.. sourcecode:: http

  POST /api/worker/pool/autoscale/celery@worker2?min=3&max=10 HTTP/1.1
  Content-Length: 0
  Content-Type: application/x-www-form-urlencoded; charset=utf-8
  Host: localhost:5555

**Example response**:

.. sourcecode:: http

  HTTP/1.1 200 OK
  Content-Length: 66
  Content-Type: application/json; charset=UTF-8

  {
      "message": "Autoscaling 'celery@worker2' worker (min=3, max=10)"
  }

:query min: minimum number of pool processes
:query max: maximum number of pool processes
:reqheader Authorization: optional OAuth token to authenticate
:statuscode 200: no error
:statuscode 401: unauthorized request
:statuscode 403: autoscaling is not enabled (see CELERYD_AUTOSCALER)
:statuscode 404: unknown worker
        """

        self.require_worker(workername)

        min = self.get_argument('min', type=int)
        max = self.get_argument('max', type=int)

        logger.info("Autoscaling '%s' worker by '%s'",
                    workername, (min, max))
        response = self.capp.control.broadcast(
            'autoscale', arguments={'min': min, 'max': max},
            destination=[workername], reply=True)
        self.write_control_response(
            response, workername,
            success_message=f"Autoscaling '{workername}' worker (min={min}, max={max})",
            failure_message=f"Failed to autoscale '{workername}' worker")


class WorkerQueueAddConsumer(ControlHandler):
    @web.authenticated
    def post(self, workername):
        """
Start consuming from a queue

**Example request**:

.. sourcecode:: http

  POST /api/worker/queue/add-consumer/celery@worker2?queue=sample-queue
  Content-Length: 0
  Content-Type: application/x-www-form-urlencoded; charset=utf-8
  Host: localhost:5555

**Example response**:

.. sourcecode:: http

  HTTP/1.1 200 OK
  Content-Length: 40
  Content-Type: application/json; charset=UTF-8

  {
      "message": "add consumer sample-queue"
  }

:query queue: the name of a new queue
:reqheader Authorization: optional OAuth token to authenticate
:statuscode 200: no error
:statuscode 401: unauthorized request
:statuscode 403: failed to add consumer
:statuscode 404: unknown worker
        """
        self.require_worker(workername)

        queue = self.get_argument('queue')

        logger.info("Adding consumer '%s' to worker '%s'",
                    queue, workername)
        response = self.capp.control.broadcast(
            'add_consumer', arguments={'queue': queue},
            destination=[workername], reply=True)
        self.write_control_response(
            response, workername,
            failure_message=f"Failed to add '{queue}' consumer to '{workername}' worker")


class WorkerQueueCancelConsumer(ControlHandler):
    @web.authenticated
    def post(self, workername):
        """
Stop consuming from a queue

**Example request**:

.. sourcecode:: http

  POST /api/worker/queue/cancel-consumer/celery@worker2?queue=sample-queue
  Content-Length: 0
  Content-Type: application/x-www-form-urlencoded; charset=utf-8
  Host: localhost:5555

**Example response**:

.. sourcecode:: http

  HTTP/1.1 200 OK
  Content-Length: 52
  Content-Type: application/json; charset=UTF-8

  {
      "message": "no longer consuming from sample-queue"
  }

:query queue: the name of queue
:reqheader Authorization: optional OAuth token to authenticate
:statuscode 200: no error
:statuscode 401: unauthorized request
:statuscode 403: failed to cancel consumer
:statuscode 404: unknown worker
        """
        self.require_worker(workername)

        queue = self.get_argument('queue')

        logger.info("Canceling consumer '%s' from worker '%s'",
                    queue, workername)
        response = self.capp.control.broadcast(
            'cancel_consumer', arguments={'queue': queue},
            destination=[workername], reply=True)
        self.write_control_response(
            response, workername,
            failure_message=f"Failed to cancel '{queue}' consumer from '{workername}' worker")


class TaskRevoke(ControlHandler):
    @web.authenticated
    def post(self, taskid):
        """
Revoke a task

**Example request**:

.. sourcecode:: http

  POST /api/task/revoke/1480b55c-b8b2-462c-985e-24af3e9158f9?terminate=true
  Content-Length: 0
  Content-Type: application/x-www-form-urlencoded; charset=utf-8
  Host: localhost:5555

**Example response**:

.. sourcecode:: http

  HTTP/1.1 200 OK
  Content-Length: 61
  Content-Type: application/json; charset=UTF-8

  {
      "message": "Revoked '1480b55c-b8b2-462c-985e-24af3e9158f9'"
  }

:query terminate: terminate the task if it is running
:query signal: name of signal to send to process if terminate (default: 'SIGTERM')
:reqheader Authorization: optional OAuth token to authenticate
:statuscode 200: no error
:statuscode 401: unauthorized request
        """
        logger.info("Revoking task '%s'", taskid)
        terminate = self.get_argument('terminate', default=False, type=bool)
        signal = self.get_argument('signal', default='SIGTERM', type=str)
        self.capp.control.revoke(taskid, terminate=terminate, signal=signal)
        self.write(dict(message=f"Revoked '{taskid}'"))


class TaskTimout(ControlHandler):
    @web.authenticated
    def post(self, taskname):
        """
Change soft and hard time limits for a task

**Example request**:

.. sourcecode:: http

    POST /api/task/timeout/tasks.sleep HTTP/1.1
    Content-Length: 44
    Content-Type: application/x-www-form-urlencoded; charset=utf-8
    Host: localhost:5555

    soft=30&hard=100&workername=celery%40worker1

**Example response**:

.. sourcecode:: http

    HTTP/1.1 200 OK
    Content-Length: 46
    Content-Type: application/json; charset=UTF-8

    {
        "message": "time limits set successfully"
    }

:query workername: worker name
:reqheader Authorization: optional OAuth token to authenticate
:statuscode 200: no error
:statuscode 401: unauthorized request
:statuscode 404: unknown task/worker
        """
        workername = self.get_argument('workername')
        hard = self.get_argument('hard', default=None, type=float)
        soft = self.get_argument('soft', default=None, type=float)

        if taskname not in self.capp.tasks:
            raise web.HTTPError(404, f"Unknown task '{taskname}'")
        self.require_worker(workername)

        logger.info("Setting timeouts for '%s' task (%s, %s)",
                    taskname, soft, hard)
        response = self.capp.control.time_limit(
            taskname, reply=True, hard=hard, soft=soft,
            destination=[workername])
        self.write_control_response(
            response, workername,
            failure_message="Failed to set timeouts")


class TaskRateLimit(ControlHandler):
    @web.authenticated
    def post(self, taskname):
        """
Change rate limit for a task

**Example request**:

.. sourcecode:: http

    POST /api/task/rate-limit/tasks.sleep HTTP/1.1
    Content-Length: 41
    Content-Type: application/x-www-form-urlencoded; charset=utf-8
    Host: localhost:5555

    ratelimit=200&workername=celery%40worker1

**Example response**:

.. sourcecode:: http

  HTTP/1.1 200 OK
  Content-Length: 61
  Content-Type: application/json; charset=UTF-8

  {
      "message": "new rate limit set successfully"
  }

:query workername: worker name
:reqheader Authorization: optional OAuth token to authenticate
:statuscode 200: no error
:statuscode 401: unauthorized request
:statuscode 404: unknown task/worker
        """
        workername = self.get_argument('workername')
        ratelimit = self.get_argument('ratelimit')

        if taskname not in self.capp.tasks:
            raise web.HTTPError(404, f"Unknown task '{taskname}'")
        self.require_worker(workername)

        logger.info("Setting '%s' rate limit for '%s' task",
                    ratelimit, taskname)
        response = self.capp.control.rate_limit(
            taskname, ratelimit, reply=True, destination=[workername])
        self.write_control_response(
            response, workername,
            failure_message="Failed to set rate limit")
