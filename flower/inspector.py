import asyncio
import logging
import time
from functools import partial

logger = logging.getLogger(__name__)


class Inspector:
    methods = ('stats', 'active_queues', 'registered', 'scheduled',
               'active', 'reserved', 'revoked', 'conf')

    def __init__(self, io_loop, capp, timeout):
        self.io_loop = io_loop
        self.capp = capp
        self.timeout = timeout
        self.workers = {}

    async def inspect(self, workername=None):
        futures = []
        for method in self.methods:
            futures.append(
                self.io_loop.run_in_executor(
                    None, partial(self._inspect, method, workername)))
        await asyncio.wait(futures)
        updates = {}
        for future in futures:
            result = future.result()
            if result:
                for worker, methods in result.items():
                    updates.setdefault(worker, {}).update(methods)
        self._apply_updates(updates)

    def _apply_updates(self, updates):
        now = time.time()
        for worker, methods in updates.items():
            if worker not in self.workers:
                self.workers[worker] = {}
            self.workers[worker].update(methods)
            self.workers[worker]['timestamp'] = now

    def _inspect(self, method, workername):
        destination = [workername] if workername else None
        inspect = self.capp.control.inspect(timeout=self.timeout, destination=destination)

        logger.debug('Sending %s inspect command', method)
        start = time.time()
        result = (
            getattr(inspect, method)()
            if method != 'active'
            else getattr(inspect, method)(safe=True)
        )
        logger.debug("Inspect command %s took %.2fs to complete", method, time.time() - start)

        if result is None or 'error' in result:
            logger.warning("Inspect method %s failed", method)
            return {}
        return {w: {method: resp} for w, resp in result.items() if resp is not None}
