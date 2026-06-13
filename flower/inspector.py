import asyncio
import collections
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
        self.workers = collections.defaultdict(dict)

    async def inspect(self, workername=None):
        # Run every inspect method concurrently in the executor, then write the
        # results back here. This coroutine resumes on the ioloop thread, so the
        # cache is mutated only from that thread (as documented in events.py) and
        # is guaranteed to be populated before we return to the caller -- no
        # add_callback indirection, no read-before-write race.
        futures = [
            self.io_loop.run_in_executor(None, partial(self._inspect, method, workername))
            for method in self.methods
        ]
        results = await asyncio.gather(*futures)

        for method, mapping in results:
            for worker, response in mapping.items():
                if response is not None:
                    info = self.workers[worker]
                    info[method] = response
                    info['timestamp'] = time.time()
        return self.workers

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
            return method, {}
        return method, result
