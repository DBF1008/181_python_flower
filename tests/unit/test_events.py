import os
import pickle
import shelve
import tempfile
import time
import unittest

from celery import Celery
from celery.events import Event
from prometheus_client import REGISTRY
from tornado.ioloop import IOLoop

from flower import command  # noqa: F401  side effect - defines tornado options
from flower.events import Events, EventsState, get_prometheus_metrics
from tests.unit import AsyncHTTPTestCase
from tests.unit.utils import HtmlTableParser, task_succeeded_events


def feed(state, events):
    for i, event in enumerate(events):
        event['clock'] = i
        event['local_received'] = time.time()
        state.event(event)
    return state


def online_worker_with_one_success(worker, task='task1', task_id=None):
    """Build a state with a single online worker that ran one task."""
    state = EventsState()
    state.get_or_create_worker(worker)
    feed(state, [Event('worker-online', hostname=worker)] +
         task_succeeded_events(worker=worker, name=task, id=task_id or f'{worker}-1'))
    return state


def worker_online(name):
    return REGISTRY.get_sample_value('flower_worker_online', {'worker': name})


def worker_executing(name):
    return REGISTRY.get_sample_value(
        'flower_worker_number_of_currently_executing_tasks', {'worker': name})


class EventsStatePersistenceTests(unittest.TestCase):
    """The per-worker ``counter`` must survive a ``--persistent`` restart, and
    the process-local Prometheus metrics must never be carried in the pickle."""

    def test_counter_survives_pickle_round_trip(self):
        state = online_worker_with_one_success('persist-pickle')
        before = {name: dict(c) for name, c in state.counter.items()}
        self.assertTrue(before)  # sanity: there is something to lose

        restored = pickle.loads(pickle.dumps(state))

        after = {name: dict(c) for name, c in restored.counter.items()}
        self.assertEqual(before, after)
        self.assertEqual(1, restored.counter['persist-pickle']['task-succeeded'])

    def test_counter_survives_shelve_round_trip(self):
        # Mirrors Events.save_state() followed by Events.__init__() recovery.
        state = online_worker_with_one_success('persist-shelve')
        before = {name: dict(c) for name, c in state.counter.items()}

        path = os.path.join(tempfile.mkdtemp(), 'flower.db')
        db = shelve.open(path, flag='n')
        db['events'] = state
        db.close()
        db = shelve.open(path)
        restored = db['events']
        db.close()

        after = {name: dict(c) for name, c in restored.counter.items()}
        self.assertEqual(before, after)

    def test_metrics_are_not_pickled(self):
        # The metrics holder is bound to the global registry of the running
        # process; on load it must be re-bound, not restored from the pickle.
        state = online_worker_with_one_success('persist-metrics')
        restored = pickle.loads(pickle.dumps(state))
        self.assertIs(restored.metrics, get_prometheus_metrics())

    def test_empty_counter_round_trip(self):
        # A brand new state (no events yet) must round-trip without errors.
        restored = pickle.loads(pickle.dumps(EventsState()))
        self.assertEqual({}, dict(restored.counter))


class RebuildMetricsTests(unittest.TestCase):
    """``rebuild_metrics`` reseeds the worker gauges from the recovered state."""

    def test_reconciles_worker_online_from_liveness(self):
        online, offline = 'reconcile-online', 'reconcile-offline'
        state = EventsState()
        for name in (online, offline):
            state.get_or_create_worker(name)
        feed(state, [
            Event('worker-online', hostname=online),
            Event('worker-heartbeat', hostname=online, active=4),
            Event('worker-online', hostname=offline),
        ])
        # Force the second worker to look offline (stale heartbeat).
        state.workers[offline].heartbeats[:] = [time.time() - 100000]

        # Simulate a fresh process whose gauges are absent/stale, then sync.
        state.metrics.worker_online.labels(online).set(0)
        state.metrics.worker_online.labels(offline).set(1)
        state.metrics.worker_number_of_currently_executing_tasks.labels(online).set(99)

        state.rebuild_metrics()

        self.assertEqual(1.0, worker_online(online))
        self.assertEqual(0.0, worker_online(offline))
        self.assertEqual(4.0, worker_executing(online))
        self.assertEqual(0.0, worker_executing(offline))


class EventsRecoveryChainTests(unittest.TestCase):
    """End-to-end: a second Events instance recovering from the same db must
    restore the counter and reconcile metrics with the recovered state."""

    def test_recovery_restores_counter_and_reconciles_metrics(self):
        IOLoop.current()  # PeriodicCallback construction needs an ioloop
        capp = Celery()
        path = os.path.join(tempfile.mkdtemp(), 'flower.db')
        worker = 'recovery-chain-worker'

        # Session 1: capture events and persist.
        events1 = Events(capp, IOLoop.current(), db=path, persistent=True)
        feed(events1.state, [
            Event('worker-online', hostname=worker),
            Event('worker-heartbeat', hostname=worker, active=2),
        ] + task_succeeded_events(worker=worker, name='task1', id='rc-1'))
        events1.save_state()

        # Simulate a restart: scramble the live gauge so a successful reseed is
        # observable, then recover with a brand new Events instance.
        get_prometheus_metrics().worker_online.labels(worker).set(0)
        events2 = Events(capp, IOLoop.current(), db=path, persistent=True)

        # Counter restored (was silently wiped before the fix).
        self.assertIn(worker, events2.state.counter)
        self.assertEqual(1, events2.state.counter[worker]['task-succeeded'])
        # Metrics holder re-bound to the global registry.
        self.assertIs(events2.state.metrics, get_prometheus_metrics())
        # Worker still has a fresh heartbeat -> online, and the gauge agrees.
        self.assertTrue(events2.state.workers[worker].alive)
        self.assertEqual(1.0, worker_online(worker))


class WorkersDashboardAfterRecoveryTests(AsyncHTTPTestCase):
    """The dashboard joins ``counter`` with ``workers``; before the fix a
    recovered worker disappeared because the counter was reset to empty."""

    def setUp(self):
        self.app = super().get_app()
        super().setUp()

    def get_app(self, capp=None):
        return self.app

    def test_recovered_worker_with_counts_is_still_shown(self):
        worker = 'dashboard-recovery-worker'
        state = online_worker_with_one_success(worker)

        # Round-trip through pickle to emulate a persistent restart.
        self.app.events.state = pickle.loads(pickle.dumps(state))

        response = self.get('/workers')
        table = HtmlTableParser()
        table.parse(str(response.body))

        self.assertEqual(200, response.code)
        self.assertEqual(
            [worker, 'True', '0', '1', '0', '1', '0', None],
            table.get_row(worker),
            'recovered worker (with its counts) should still appear after restart',
        )
