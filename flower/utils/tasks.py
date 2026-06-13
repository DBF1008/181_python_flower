import datetime
import time
from functools import total_ordering

from .search import parse_search_terms, satisfies_search_terms


@total_ordering
class Comparable:
    """
    Compare two objects, one or more of which may be None.
    None values are always considered less than non-None values.
    """
    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        if not isinstance(other, Comparable):
            return NotImplemented
        return self.value == other.value

    def __lt__(self, other):
        if not isinstance(other, Comparable):
            return NotImplemented
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


sort_keys = {
    'name': str,
    'state': str,
    'received': float,
    'started': float,
    'runtime': float,
}


def sort_tasks(tasks, sort_by):
    """Sort tasks by a given field.

    Args:
        tasks: iterable of (uuid, task) tuples
        sort_by: field name, optionally prefixed with '-' for descending

    Raises:
        ValueError: if sort_by field is not in sort_keys
    """
    reverse = False
    if sort_by.startswith('-'):
        sort_by = sort_by[1:]
        reverse = True

    if sort_by not in sort_keys:
        raise ValueError(
            f"Invalid sort field '{sort_by}'. "
            f"Must be one of: {', '.join(sorted(sort_keys.keys()))}"
        )

    yield from sorted(
        tasks,
        key=lambda x: Comparable(getattr(x[1], sort_by, None)),
        reverse=reverse,
    )


def get_task_by_id(events, task_id):
    return events.state.tasks.get(task_id)


def as_dict(task):
    return task.as_dict()


def query_tasks(events, sort_by=None, search=None, type=None, worker=None,
                state=None, received_start=None, received_end=None,
                started_start=None, started_end=None,
                offset=0, limit=None):
    """Query tasks with filtering, sorting, and pagination.

    This is the single source of truth for both the API and DataTable endpoints.

    Returns a dict with:
        - data: list of (uuid, task) for the requested page
        - records_total: total number of tasks (unfiltered)
        - records_filtered: number of tasks matching all filters (before pagination)
    """
    all_tasks = list(events.state.tasks_by_timestamp())
    records_total = len(all_tasks)

    def convert(x):
        return time.mktime(
            datetime.datetime.strptime(x, '%Y-%m-%d %H:%M').timetuple())

    search_terms = parse_search_terms(search or {})

    # Filter
    filtered = []
    for uuid, task in all_tasks:
        if type and task.name != type:
            continue
        if worker and task.worker and task.worker.hostname != worker:
            continue
        if state and task.state != state:
            continue
        if received_start and task.received and \
                task.received < convert(received_start):
            continue
        if received_end and task.received and \
                task.received > convert(received_end):
            continue
        if started_start and task.started and \
                task.started < convert(started_start):
            continue
        if started_end and task.started and \
                task.started > convert(started_end):
            continue
        if not satisfies_search_terms(task, search_terms):
            continue
        filtered.append((uuid, task))

    records_filtered = len(filtered)

    # Sort
    if sort_by is not None:
        filtered = list(sort_tasks(filtered, sort_by))

    # Paginate
    if offset:
        filtered = filtered[offset:]
    if limit is not None:
        filtered = filtered[:limit]

    return {
        'data': filtered,
        'records_total': records_total,
        'records_filtered': records_filtered,
    }
