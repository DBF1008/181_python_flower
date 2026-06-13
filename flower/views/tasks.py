import copy
import logging

from tornado import web

from ..utils.tasks import as_dict, get_task_by_id, iter_tasks
from ..views import BaseHandler

logger = logging.getLogger(__name__)


class TaskView(BaseHandler):
    @web.authenticated
    def get(self, task_id):
        task = get_task_by_id(self.application.events, task_id)

        if task is None:
            raise web.HTTPError(404, f"Unknown task '{task_id}'")
        task = self.format_task(task)
        self.render("task.html", task=task)


class TasksDataTable(BaseHandler):
    @web.authenticated
    def get(self):
        app = self.application
        draw = self.get_argument('draw', type=int)
        start = self.get_argument('start', type=int)
        length = self.get_argument('length', type=int)
        search = self.get_argument('search[value]', type=str)

        column = self.get_argument('order[0][column]', type=int)
        column_name = self.get_argument(f'columns[{column}][data]', type=str)
        descending = self.get_argument('order[0][dir]', type=str) == 'desc'
        sort_by = ('-' if descending else '') + column_name

        # Funnel filtering + sorting through the shared iter_tasks so the page
        # and /api/tasks stay semantically identical. Materialise the full
        # filtered+sorted list once, then paginate it locally.
        filtered_tasks = list(iter_tasks(app.events, sort_by=sort_by, search=search))

        # recordsTotal must be counted from the same source that produces the
        # rows (tasks_by_timestamp), NOT len(state.tasks): those are different
        # containers with different eviction bounds, which would desync the
        # "filtered from N total" counter even with an empty search. A state
        # filter expressed via the search box (e.g. "state:SUCCESS") counts as
        # filtering, so recordsFiltered < recordsTotal is the correct result.
        records_total = sum(1 for _ in app.events.state.tasks_by_timestamp())

        data = []
        for task in filtered_tasks[start:start + length]:
            task_dict = as_dict(self.format_task(task)[1])
            if task_dict.get('worker'):
                task_dict['worker'] = task_dict['worker'].hostname
            data.append(task_dict)

        self.write(dict(draw=draw, data=data,
                        recordsTotal=records_total,
                        recordsFiltered=len(filtered_tasks)))

    @web.authenticated
    def post(self):
        return self.get()

    def format_task(self, task):
        uuid, args = task
        custom_format_task = self.application.options.format_task

        if custom_format_task:
            try:
                args = custom_format_task(copy.copy(args))
            except Exception:
                logger.exception("Failed to format '%s' task", uuid)
        return uuid, args


class TasksView(BaseHandler):
    @web.authenticated
    def get(self):
        app = self.application
        capp = self.application.capp

        time = 'natural-time' if app.options.natural_time else 'time'
        if capp.conf.timezone:
            time += '-' + str(capp.conf.timezone)

        self.render(
            "tasks.html",
            tasks=[],
            columns=app.options.tasks_columns,
            time=time,
        )
