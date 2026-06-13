import json
import time
from unittest import mock

from celery.events import Event

from flower.events import EventsState
from flower.inspector import Inspector

from . import BaseApiTestCase

inspect_response = {
    'celery@worker1':  [
        "tasks.add",
        "tasks.sleep"
    ],
}

empty_inspect_response = {
    'celery@worker1': []
}


@mock.patch.object(Inspector, 'methods',
                   new_callable=mock.PropertyMock,
                   return_value=['inspect_method'])
class ListWorkersTest(BaseApiTestCase):

    def test_refresh_cache(self, m_inspect):
        celery = self._app.capp
        celery.control.inspect = mock.Mock()
        celery.control.inspect.return_value.inspect_method = mock.Mock(
            return_value=inspect_response
        )

        r = self.get('/api/workers?refresh=1')
        celery.control.inspect.assert_called_once_with(
            timeout=1,
            destination=None
        )

        body = json.loads(r.body.decode("utf-8"))
        self.assertEqual(
            inspect_response['celery@worker1'],
            body['celery@worker1']['inspect_method']
        )
        self.assertIn('timestamp', body['celery@worker1'])
        self.assertEqual(
            inspect_response['celery@worker1'],
            self._app.workers['celery@worker1']['inspect_method']
        )

    def test_refresh_cache_with_empty_response(self, m_inspect):
        celery = self._app.capp
        celery.control.inspect = mock.Mock()
        celery.control.inspect.return_value.inspect_method = mock.Mock(
            return_value=inspect_response
        )
        r = self.get('/api/workers?refresh=1')

        celery.control.inspect.return_value.inspect_method = mock.Mock(
            return_value=empty_inspect_response
        )

        r = self.get('/api/workers?refresh=1')

        body = json.loads(r.body.decode("utf-8"))
        self.assertEqual(
            [],
            body['celery@worker1']['inspect_method']
        )
        self.assertIn('timestamp', body['celery@worker1'])
        self.assertEqual(
            [],
            self._app.workers['celery@worker1']['inspect_method']
        )

    # ------------------------------------------------------------------
    # Regression tests
    # ------------------------------------------------------------------

    def test_refresh_single_worker(self, m_inspect):
        """Refresh with workername must scope inspect to that worker."""
        celery = self._app.capp
        celery.control.inspect = mock.Mock()
        celery.control.inspect.return_value.inspect_method = mock.Mock(
            return_value=inspect_response
        )

        r = self.get('/api/workers?refresh=1&workername=celery@worker1')
        celery.control.inspect.assert_called_with(
            timeout=1,
            destination=['celery@worker1']
        )

        body = json.loads(r.body.decode("utf-8"))
        self.assertIn('celery@worker1', body)
        self.assertEqual(
            inspect_response['celery@worker1'],
            body['celery@worker1']['inspect_method']
        )

    def test_status_endpoint(self, m_inspect):
        """/api/workers?status=1 must return alive status from event state."""
        state = EventsState()
        state.get_or_create_worker('celery@worker1')
        state.event(Event('worker-online', hostname='celery@worker1',
                          local_received=time.time()))
        self._app.events.state = state

        r = self.get('/api/workers?status=1')
        self.assertEqual(200, r.code)

        body = json.loads(r.body.decode("utf-8"))
        self.assertIn('celery@worker1', body)
        self.assertTrue(body['celery@worker1'])

    def test_unknown_worker_returns_404(self, m_inspect):
        """Requesting an unknown worker by name must return 404."""
        r = self.get('/api/workers?workername=nonexistent@worker')
        self.assertEqual(404, r.code)
