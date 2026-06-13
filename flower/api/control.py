import logging

from tornado import web

from . import BaseApiHandler

logger = logging.getLogger(__name__)


class ControlHandler(BaseApiHandler):
    def is_worker(self, workername):
        return workername and workername in self.application.workers

    def error_reason(self, workername, response):
        """Safely extract error message from a Celery control response."""
        if not response:
            return 'No response from worker'
        if not isinstance(response, list):
            return f'Unexpected response: {response}'
        for res in response:
            if not isinstance(res, dict):
                continue
            # Try exact workername match
            if workername and workername in res:
                entry = res[workername]
                if isinstance(entry, dict):
                    return entry.get('error', 'Unknown reason')
                return str(entry)
            # Fallback: first available entry
            for entry in res.values():
                if isinstance(entry, dict):
                    return entry.get('error', 'Unknown reason')
                return str(entry)
        return 'Unknown reason'

    def _is_success_response(self, workername, response):
        """Check if a Celery control response indicates success."""
        if not response or not isinstance(response, list):
            return False
        for res in response:
            if not isinstance(res, dict):
                continue
            if workername:
                if workername in res:
                    return isinstance(res[workername], dict) and 'ok' in res[workername]
                # Specific worker not found in response — treat as failure
                return False
            # workername is None (broadcast without destination)
            for v in res.values():
                return isinstance(v, dict) and 'ok' in v
        return False

    def _get_ok_message(self, workername, response):
        """Extract the 'ok' message from a successful response."""
        if not response or not isinstance(response, list):
            return ''
        for res in response:
            if not isinstance(res, dict):
                continue
            if workername and workername in res:
                return res[workername].get('ok', '')
            for v in res.values():
                if isinstance(v, dict):
                    return v.get('ok', '')
        return ''

    def _execute_control(self, workername, command_fn, success_msg):
        """
        Execute a Celery control command and write the HTTP response.

        Args:
            workername: target worker (can be None for broadcast)
            command_fn: zero-arg callable that invokes the Celery control
                        and returns the response
            success_msg: str or callable(response) -> str
        """
        try:
            response = command_fn()
        except Exception as exc:
            logger.error("Control command failed: %s", exc)
            self.set_status(500)
            self.write(f"Control command failed: {exc}")
            return

        if self._is_success_response(workername, response):
            if callable(success_msg):
                self.write(dict(message=success_msg(response)))
            else:
                self.write(dict(message=success_msg))
        else:
            logger.error("Control command failed, response: %s", response)
            self.set_status(403)
            reason = self.error_reason(workername, response)
            self.write(f"Failed: {reason}")


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
        if not self.is_worker(workername):
            raise web.HTTPError(404, f"Unknown worker '{workername}'")

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
        if not self.is_worker(workername):
            raise web.HTTPError(404, f"Unknown worker '{workername}'")

        logger.info("Restarting '%s' worker's pool", workername)
        self._execute_control(
            workername,
            lambda: self.capp.control.broadcast(
                'pool_restart', arguments={'reload': False},
                destination=[workername], reply=True),
            f"Restarting '{workername}' worker's pool")


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

        if not self.is_worker(workername):
            raise web.HTTPError(404, f"Unknown worker '{workername}'")

        n = self.get_argument('n', default=1, type=int)

        logger.info("Growing '%s' worker's pool by '%s'", workername, n)
        self._execute_control(
            workername,
            lambda: self.capp.control.pool_grow(
                n=n, reply=True, destination=[workername]),
            f"Growing '{workername}' worker's pool by {n}")


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

        if not self.is_worker(workername):
            raise web.HTTPError(404, f"Unknown worker '{workername}'")

        n = self.get_argument('n', default=1, type=int)

        logger.info("Shrinking '%s' worker's pool by '%s'", workername, n)
        self._execute_control(
            workername,
            lambda: self.capp.control.pool_shrink(
                n=n, reply=True, destination=[workername]),
            f"Shrinking '{workername}' worker's pool by {n}")


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

        if not self.is_worker(workername):
            raise web.HTTPError(404, f"Unknown worker '{workername}'")

        min = self.get_argument('min', type=int)
        max = self.get_argument('max', type=int)

        logger.info("Autoscaling '%s' worker by '%s'",
                    workername, (min, max))
        self._execute_control(
            workername,
            lambda: self.capp.control.broadcast(
                'autoscale', arguments={'min': min, 'max': max},
                destination=[workername], reply=True),
            f"Autoscaling '{workername}' worker (min={min}, max={max})")


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
        if not self.is_worker(workername):
            raise web.HTTPError(404, f"Unknown worker '{workername}'")

        queue = self.get_argument('queue')

        logger.info("Adding consumer '%s' to worker '%s'",
                    queue, workername)
        self._execute_control(
            workername,
            lambda: self.capp.control.broadcast(
                'add_consumer', arguments={'queue': queue},
                destination=[workername], reply=True),
            lambda resp: self._get_ok_message(workername, resp))


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
        if not self.is_worker(workername):
            raise web.HTTPError(404, f"Unknown worker '{workername}'")

        queue = self.get_argument('queue')

        logger.info("Canceling consumer '%s' from worker '%s'",
                    queue, workername)
        self._execute_control(
            workername,
            lambda: self.capp.control.broadcast(
                'cancel_consumer', arguments={'queue': queue},
                destination=[workername], reply=True),
            lambda resp: self._get_ok_message(workername, resp))


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
        if workername is not None and not self.is_worker(workername):
            raise web.HTTPError(404, f"Unknown worker '{workername}'")

        logger.info("Setting timeouts for '%s' task (%s, %s)",
                    taskname, soft, hard)
        destination = [workername] if workername else None
        self._execute_control(
            workername or None,
            lambda: self.capp.control.time_limit(
                taskname, reply=True, hard=hard, soft=soft,
                destination=destination),
            lambda resp: self._get_ok_message(workername, resp))


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
        if workername is not None and not self.is_worker(workername):
            raise web.HTTPError(404, f"Unknown worker '{workername}'")

        logger.info("Setting '%s' rate limit for '%s' task",
                    ratelimit, taskname)
        destination = [workername] if workername else None
        self._execute_control(
            workername or None,
            lambda: self.capp.control.rate_limit(
                taskname, ratelimit, reply=True, destination=destination),
            lambda resp: self._get_ok_message(workername, resp))
