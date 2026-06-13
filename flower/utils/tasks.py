import datetime
import time
from functools import total_ordering

from .search import parse_search_terms, satisfies_search_terms


@total_ordering
class Comparable:
    """
    Compare two objects, one or more of which may be None.  If one of the
    values is None, the other will be deemed greater.  This makes sorting by
    task attributes robust to missing/None values and to mixed types instead
    of raising ``TypeError``.
    """

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return self.value == other.value

    def __lt__(self, other):
        try:
            return self.value < other.value
        except TypeError:
            return self.value is None


# pylint: disable=too-many-branches,too-many-locals,too-many-arguments
def iter_tasks(events, limit=None, offset=0, type=None, worker=None, state=None,
               sort_by=None, received_start=None, received_end=None,
               started_start=None, started_end=None, search=None):
    i = 0
    tasks = events.state.tasks_by_timestamp()
    if sort_by is not None:
        tasks = sort_tasks(tasks, sort_by)

    def convert(x):
        return time.mktime(datetime.datetime.strptime(x, '%Y-%m-%d %H:%M').timetuple())

    search_terms = parse_search_terms(search or {})

    for uuid, task in tasks:
        if type and task.name != type:
            continue
        if worker and task.worker and task.worker.hostname != worker:
            continue
        if state and task.state != state:
            continue
        if received_start and task.received and\
                task.received < convert(received_start):
            continue
        if received_end and task.received and\
                task.received > convert(received_end):
            continue
        if started_start and task.started and\
                task.started < convert(started_start):
            continue
        if started_end and task.started and\
                task.started > convert(started_end):
            continue
        if not satisfies_search_terms(task, search_terms):
            continue
        if i >= offset:
            yield uuid, task
        i += 1
        if limit is not None:
            if i == limit + offset:
                break


def sort_tasks(tasks, sort_by):
    """Sort ``(uuid, task)`` pairs by any task attribute.

    A leading ``-`` reverses the order (e.g. ``-received``).  Sorting uses
    :class:`Comparable`, so ``None`` values and unknown/non-orderable
    attributes degrade gracefully (stable order) rather than raising.  This is
    the single sort implementation shared by the ``/tasks`` page and the
    ``/api/tasks`` endpoint.
    """
    reverse = sort_by.startswith('-')
    field = sort_by[1:] if reverse else sort_by
    return sorted(
        tasks,
        key=lambda task: Comparable(getattr(task[1], field, None)),
        reverse=reverse)


def get_task_by_id(events, task_id):
    return events.state.tasks.get(task_id)


def as_dict(task):
    return task.as_dict()
