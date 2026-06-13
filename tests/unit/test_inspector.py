from collections import defaultdict
from unittest.mock import Mock

from flower.inspector import Inspector
from tests.unit import AsyncHTTPTestCase


def _make_inspector(test_case):
    """Create an Inspector wired to the test's IOLoop with a mocked Celery app."""
    capp = Mock()
    return Inspector(test_case.io_loop, capp, timeout=1), capp


class InspectorUnitTest(AsyncHTTPTestCase):
    """Tests for Inspector internals (atomic updates, dict type, error handling)."""

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _setup_mock(self, capp, response):
        """Configure *capp* so every inspect method returns *response*."""
        inspect_mock = Mock()
        for method in Inspector.methods:
            if method == 'active':
                inspect_mock.active = Mock(return_value=response)
            else:
                setattr(inspect_mock, method, Mock(return_value=response))
        capp.control.inspect = Mock(return_value=inspect_mock)

    # ------------------------------------------------------------------
    # tests
    # ------------------------------------------------------------------
    def test_workers_is_plain_dict(self):
        inspector, _ = _make_inspector(self)
        self.assertIsInstance(inspector.workers, dict)
        self.assertNotIsInstance(inspector.workers, defaultdict)
        # Accessing a non-existent key must not create an entry
        self.assertNotIn('nonexistent', inspector.workers)

    def test_apply_updates_creates_worker(self):
        inspector, _ = _make_inspector(self)
        inspector._apply_updates({'worker1': {'stats': {'pid': 123}}})
        self.assertIn('worker1', inspector.workers)
        self.assertEqual({'pid': 123}, inspector.workers['worker1']['stats'])
        self.assertIn('timestamp', inspector.workers['worker1'])

    def test_apply_updates_merges_into_existing(self):
        inspector, _ = _make_inspector(self)
        inspector.workers['worker1'] = {'stats': {'pid': 123}}
        inspector._apply_updates({'worker1': {'registered': ['tasks.add']}})
        self.assertEqual({'pid': 123}, inspector.workers['worker1']['stats'])
        self.assertEqual(['tasks.add'], inspector.workers['worker1']['registered'])

    def test_apply_updates_multiple_workers(self):
        inspector, _ = _make_inspector(self)
        inspector._apply_updates({
            'worker1': {'stats': {'pid': 1}},
            'worker2': {'stats': {'pid': 2}},
        })
        self.assertIn('worker1', inspector.workers)
        self.assertIn('worker2', inspector.workers)
        self.assertEqual(1, inspector.workers['worker1']['stats']['pid'])
        self.assertEqual(2, inspector.workers['worker2']['stats']['pid'])

    def test_inspect_atomic_updates(self):
        """After a full inspect cycle all methods must be visible at once."""
        inspector, capp = _make_inspector(self)
        response = {'worker1': {'pid': 123, 'total': {}}}
        self._setup_mock(capp, response)

        self.io_loop.run_sync(lambda: inspector.inspect())

        info = inspector.workers['worker1']
        self.assertIn('stats', info)
        self.assertIn('registered', info)
        self.assertIn('active_queues', info)
        self.assertIn('timestamp', info)

    def test_inspect_single_worker(self):
        """Passing *workername* must scope the inspect to that worker."""
        inspector, capp = _make_inspector(self)
        response = {'worker1': {'pid': 123}}
        self._setup_mock(capp, response)

        self.io_loop.run_sync(lambda: inspector.inspect(workername='worker1'))

        capp.control.inspect.assert_called_with(
            timeout=1, destination=['worker1'])
        self.assertIn('worker1', inspector.workers)

    def test_inspect_handles_none_response(self):
        """A None response from an inspect method must not corrupt state."""
        inspector, capp = _make_inspector(self)
        inspect_mock = Mock()
        for method in Inspector.methods:
            setattr(inspect_mock, method, Mock(return_value=None))
        capp.control.inspect = Mock(return_value=inspect_mock)

        self.io_loop.run_sync(lambda: inspector.inspect())

        self.assertEqual({}, inspector.workers)

    def test_inspect_handles_error_response(self):
        """An error response must be silently skipped."""
        inspector, capp = _make_inspector(self)
        inspect_mock = Mock()
        error_result = {'error': 'connection refused'}
        for method in Inspector.methods:
            setattr(inspect_mock, method, Mock(return_value=error_result))
        capp.control.inspect = Mock(return_value=inspect_mock)

        self.io_loop.run_sync(lambda: inspector.inspect())

        self.assertEqual({}, inspector.workers)
