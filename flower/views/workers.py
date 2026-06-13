import logging

from tornado import web

from ..options import options
from ..views import BaseHandler

logger = logging.getLogger(__name__)


class WorkerView(BaseHandler):
    @web.authenticated
    async def get(self, name):
        try:
            await self.application.update_workers(workername=name)
        except Exception as e:
            logger.error(e)

        worker = self.application.workers.get(name)

        if worker is None:
            raise web.HTTPError(404, f"Unknown worker '{name}'")
        if 'stats' not in worker:
            raise web.HTTPError(404, f"Unable to get stats for '{name}' worker")

        self.render("worker.html", worker=dict(worker, name=name))


class WorkersView(BaseHandler):
    @web.authenticated
    async def get(self):
        refresh = self.get_argument('refresh', default=False, type=bool)
        json = self.get_argument('json', default=False, type=bool)

        if refresh:
            try:
                await self.application.update_workers()
            except Exception as e:
                logger.exception('Failed to update workers: %s', e)

        workers = self.application.get_workers(
            purge_offline=options.purge_offline_workers
        )

        if json:
            self.write(dict(data=list(workers.values())))
        else:
            self.render("workers.html",
                        workers=workers,
                        broker=self.application.capp.connection().as_uri(),
                        autorefresh=1 if self.application.options.auto_refresh else 0)
