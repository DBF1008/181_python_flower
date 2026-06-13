import sys
import logging
import time

from concurrent.futures import ThreadPoolExecutor

import celery
import tornado.web

from tornado import ioloop
from tornado.httpserver import HTTPServer
from tornado.web import url

from .urls import handlers as default_handlers
from .events import Events
from .inspector import Inspector
from .options import default_options


logger = logging.getLogger(__name__)


if sys.version_info[0] == 3 and sys.version_info[1] >= 8 and sys.platform.startswith('win'):
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# pylint: disable=consider-using-f-string
def rewrite_handler(handler, url_prefix):
    if isinstance(handler, url):
        return url("/{}{}".format(url_prefix.strip("/"), handler.regex.pattern),
                   handler.handler_class, handler.kwargs, handler.name)
    return ("/{}{}".format(url_prefix.strip("/"), handler[0]), handler[1])


def worker_fields(worker):
    """Extract the display fields of an events-state worker object."""
    if hasattr(worker, '_fields'):
        return {k: getattr(worker, k) for k in worker._fields}
    _fields = ('hostname', 'pid', 'freq', 'heartbeats', 'clock',
               'active', 'processed', 'loadavg', 'sw_ident',
               'sw_ver', 'sw_sys')
    fields = {}
    for key in _fields:
        value = getattr(worker, key, None)
        if value is not None:
            fields[key] = value
    return fields


class Flower(tornado.web.Application):
    pool_executor_cls = ThreadPoolExecutor
    max_workers = None

    def __init__(self, options=None, capp=None, events=None,
                 io_loop=None, **kwargs):
        handlers = default_handlers
        if options is not None and options.url_prefix:
            handlers = [rewrite_handler(h, options.url_prefix) for h in handlers]
        kwargs.update(handlers=handlers)
        super().__init__(**kwargs)
        self.options = options or default_options
        self.io_loop = io_loop or ioloop.IOLoop.instance()
        self.ssl_options = kwargs.get('ssl_options', None)

        self.capp = capp or celery.Celery()
        self.capp.loader.import_default_modules()

        self.executor = self.pool_executor_cls(max_workers=self.max_workers)
        self.io_loop.set_default_executor(self.executor)

        self.inspector = Inspector(self.io_loop, self.capp, self.options.inspect_timeout / 1000.0)

        self.events = events or Events(
            self.capp,
            db=self.options.db,
            persistent=self.options.persistent,
            state_save_interval=self.options.state_save_interval,
            enable_events=self.options.enable_events,
            io_loop=self.io_loop,
            max_workers_in_memory=self.options.max_workers,
            max_tasks_in_memory=self.options.max_tasks)
        self.started = False

    def start(self):
        self.events.start()

        if not self.options.unix_socket:
            self.listen(self.options.port, address=self.options.address,
                        ssl_options=self.ssl_options,
                        xheaders=self.options.xheaders)
        else:
            from tornado.netutil import bind_unix_socket
            server = HTTPServer(self)
            socket = bind_unix_socket(self.options.unix_socket, mode=0o777)
            server.add_socket(socket)

        self.started = True
        self.io_loop.add_callback(self._safe_initial_update)
        self.io_loop.start()

    def stop(self):
        if self.started:
            self.events.stop()
            logging.debug("Stopping executors...")
            self.executor.shutdown(wait=False)
            logging.debug("Stopping event loop...")
            self.io_loop.stop()
            self.started = False

    @property
    def transport(self):
        return getattr(self.capp.connection().transport, 'driver_type', None)

    @property
    def workers(self):
        return self.inspector.workers

    async def update_workers(self, workername=None):
        return await self.inspector.inspect(workername)

    async def _safe_initial_update(self):
        try:
            await self.update_workers()
        except Exception:
            logger.exception("Initial worker inspection failed")

    def is_worker_alive(self, name):
        worker = self.events.state.workers.get(name)
        return bool(worker and worker.alive)

    def worker_detail(self, name):
        # Inspector detail for a single worker, with aliveness sourced from the
        # events state so the single-worker view and the list view agree on
        # `status`. Returns a copy so the cache is never mutated.
        detail = self.inspector.workers.get(name)
        if detail is None:
            return None
        return dict(detail, status=self.is_worker_alive(name))

    def list_workers(self):
        # Summary rows for the workers list page: per-worker event counters +
        # worker fields + aliveness, with offline-expired workers pruned.
        expired = self.purge_expired_offline()
        state = self.events.state
        workers = {}
        for name, counts in state.counter.items():
            worker = state.workers.get(name)
            if worker is None or name in expired:
                continue
            info = dict(counts)
            info.update(worker_fields(worker))
            info['status'] = worker.alive
            workers[name] = info
        return workers

    def _expired_offline_names(self):
        # The single offline policy, gated on the purge_offline_workers option.
        # A worker is expired when it is not alive and its last heartbeat is
        # older than the configured TTL (or it never sent one).
        ttl = self.options.purge_offline_workers
        if ttl is None:
            return set()
        now = int(time.time())
        state = self.events.state
        expired = set()
        for name in set(self.inspector.workers) | set(state.workers):
            worker = state.workers.get(name)
            if worker is not None and worker.alive:
                continue
            heartbeats = list(getattr(worker, 'heartbeats', None) or [])
            last_heartbeat = int(max(heartbeats)) if heartbeats else None
            if not last_heartbeat or now - last_heartbeat > ttl:
                expired.add(name)
        return expired

    def purge_expired_offline(self):
        # Apply the offline policy to the inspector cache as well, so the API
        # body and the single-worker page stop serving dead workers' stale
        # detail -- not just the list view.
        expired = self._expired_offline_names()
        for name in expired:
            self.inspector.workers.pop(name, None)
        return expired
