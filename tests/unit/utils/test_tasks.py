import datetime
import time
import unittest
from types import SimpleNamespace

from celery.events import Event

from flower.events import EventsState
from flower.utils.tasks import iter_tasks
from tests.unit.utils import task_succeeded_events


def _epoch(value):
    # Mirror iter_tasks' own conversion so thresholds are timezone-consistent
    # with how the production code parses received/started boundaries.
    return time.mktime(datetime.datetime.strptime(value, '%Y-%m-%d %H:%M').timetuple())


def _build_state(specs):
    """specs: list of (uuid, runtime) tuples -> populated EventsState wrapper."""
    state = EventsState()
    state.get_or_create_worker('worker1')
    events = [Event('worker-online', hostname='worker1')]
    for task_id, runtime in specs:
        events += task_succeeded_events(worker='worker1', name='task',
                                        id=task_id, runtime=runtime)
    for i, e in enumerate(events):
        e['clock'] = i
        e['local_received'] = time.time()
        state.event(e)
    return SimpleNamespace(state=state)


class IterTasksSortTests(unittest.TestCase):
    """The single shared sort path used by both the page and /api/tasks."""

    def test_sort_by_runtime_does_not_raise(self):
        # Regression: the old utils sort whitelist asserted on 'runtime', so
        # GET /api/tasks?sort_by=runtime raised AssertionError -> HTTP 500.
        events = _build_state([('2', 10.0), ('4', 10000000.0),
                               ('3', 20.0), ('1', 2.0)])
        order = [uuid for uuid, _ in iter_tasks(events, sort_by='runtime')]
        self.assertEqual(['1', '2', '3', '4'], order)

    def test_none_sorts_first_ascending_last_descending(self):
        events = _build_state([('has', 5.0), ('none', None)])
        asc = [uuid for uuid, _ in iter_tasks(events, sort_by='runtime')]
        desc = [uuid for uuid, _ in iter_tasks(events, sort_by='-runtime')]
        self.assertEqual(['none', 'has'], asc)
        self.assertEqual(['has', 'none'], desc)

    def test_unknown_or_dunder_sort_field_is_graceful(self):
        # Dropping the whitelist must not crash (or execute the attribute) for
        # unknown / non-scalar fields; getattr(..., None) + Comparable handle it.
        events = _build_state([('1', 1.0), ('2', 2.0)])
        for field in ('does_not_exist', '__class__'):
            result = list(iter_tasks(events, sort_by=field))
            self.assertEqual(2, len(result))


class IterTasksTimeRangeTests(unittest.TestCase):
    """received_*/started_* are handled by the one shared implementation."""

    def _state_with_times(self):
        events = _build_state([('early', 0.1), ('mid', 0.1), ('late', 0.1)])
        times = {
            'early': ('2020-01-01 10:00', '2020-01-01 10:30'),
            'mid': ('2020-01-01 12:00', '2020-01-01 12:30'),
            'late': ('2020-01-01 14:00', '2020-01-01 14:30'),
        }
        for task_id, (received, started) in times.items():
            task = events.state.tasks[task_id]
            task.received = _epoch(received)
            task.started = _epoch(started)
        return events

    def test_received_range_filters(self):
        events = self._state_with_times()
        result = {uuid for uuid, _ in iter_tasks(
            events, received_start='2020-01-01 11:00',
            received_end='2020-01-01 13:00')}
        self.assertEqual({'mid'}, result)

    def test_started_range_filters(self):
        events = self._state_with_times()
        result = {uuid for uuid, _ in iter_tasks(
            events, started_start='2020-01-01 11:00',
            started_end='2020-01-01 13:00')}
        self.assertEqual({'mid'}, result)


if __name__ == '__main__':
    unittest.main()
