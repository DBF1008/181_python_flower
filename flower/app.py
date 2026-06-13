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


_WORKER_FIELDS = ('hostname', 'pid', 'freq', 'heartbeats', 'clock',
                  'active', 'processed', 'loadavg', 'sw_ident',
                  'sw_ver', 'sw_sys')


def _worker_as_dict(worker):
    """Convert a Celery State Worker object to a plain dict."""
    if hasattr(worker, '_fields'):
        return {k: getattr(worker, k) for k in worker._fields}
    result = {}
    for key in _WORKER_FIELDS:
        value = getattr(worker, key, None)
        if value is not None:
            result[key] = value
    return result


def _purge_offline_workers(workers, threshold, inspector_cache):
    """Remove offline workers whose last heartbeat exceeds *threshold* seconds.

    Also cleans up stale entries in *inspector_cache* for purged workers.
    """
    now = int(time.time())
    to_remove = []
    for name, info in workers.items():
        if info.get('status', True):
            continue
        heartbeats = info.get('heartbeats', [])
        last_heartbeat = int(max(heartbeats)) if heartbeats else None
        if not last_heartbeat or now - last_heartbeat > threshold:
            to_remove.append(name)
    for name in to_remove:
        workers.pop(name)
        inspector_cache.pop(name, None)
        logger.debug("Purged offline worker '%s'", name)


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
        self.io_loop.spawn_callback(self.update_workers)
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

    def get_workers(self, purge_offline=None):
        """Unified worker read: merge event state + inspector cache, with
        centralised offline-worker purging.

        Parameters
        ----------
        purge_offline : int or None
            If not None, purge workers whose last heartbeat is older than
            this many seconds.
        """
        events = self.events.state
        workers = {}
        for name, values in events.counter.items():
            if name not in events.workers:
                continue
            worker = events.workers[name]
            info = dict(values)
            info.update(_worker_as_dict(worker))
            info.update(status=worker.alive)
            if name in self.inspector.workers:
                for key, value in self.inspector.workers[name].items():
                    info.setdefault(key, value)
            workers[name] = info

        if purge_offline is not None:
            _purge_offline_workers(workers, purge_offline,
                                   self.inspector.workers)
        return workers
