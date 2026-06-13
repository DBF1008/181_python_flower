import logging

from tornado import web

from ..utils.tasks import as_dict, get_task_by_id, query_tasks
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
        sort_by = self.get_argument(f'columns[{column}][data]', type=str)
        sort_dir = self.get_argument('order[0][dir]', type=str)

        # Map DataTable sort direction to sort_tasks convention
        if sort_dir == 'desc':
            sort_by = f'-{sort_by}'

        result = query_tasks(
            app.events,
            sort_by=sort_by,
            search=search,
            offset=start,
            limit=length,
        )

        data = []
        for uuid, task in result['data']:
            task = self.format_task(task)
            task_dict = as_dict(task)
            if task_dict.get('worker'):
                task_dict['worker'] = task_dict['worker'].hostname
            data.append(task_dict)

        self.write(dict(
            draw=draw,
            data=data,
            recordsTotal=result['records_total'],
            recordsFiltered=result['records_filtered'],
        ))

    @web.authenticated
    def post(self):
        return self.get()


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
