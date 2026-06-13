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

    def test_status_consistent_single_and_full(self, m_inspect):
        # The same worker reports the same `status` whether read singly or in bulk.
        state = EventsState()
        state.get_or_create_worker('w1')
        state.event(Event('worker-online', hostname='w1', local_received=time.time()))
        state.get_or_create_worker('w2')
        state.event(Event('worker-online', hostname='w2', local_received=time.time()))
        state.event(Event('worker-offline', hostname='w2', local_received=time.time()))
        self._app.events.state = state
        self._app.inspector.workers['w1'] = {'stats': {}}
        self._app.inspector.workers['w2'] = {'stats': {}}

        full = json.loads(self.get('/api/workers').body)
        single1 = json.loads(self.get('/api/workers?workername=w1').body)
        single2 = json.loads(self.get('/api/workers?workername=w2').body)

        self.assertEqual(full['w1']['status'], single1['w1']['status'])
        self.assertEqual(full['w2']['status'], single2['w2']['status'])
        self.assertTrue(full['w1']['status'])
        self.assertFalse(full['w2']['status'])

    def test_offline_worker_purged_from_api_body(self, m_inspect):
        state = EventsState()
        state.get_or_create_worker('w2')
        state.event(Event('worker-online', hostname='w2', local_received=time.time()))
        state.event(Event('worker-offline', hostname='w2', local_received=time.time()))
        self._app.events.state = state
        self._app.inspector.workers['w2'] = {'stats': {}}

        # default: offline worker retained in the body
        body = json.loads(self.get('/api/workers').body)
        self.assertIn('w2', body)

        # purge enabled: dropped from the body and the inspector cache
        with self.mock_option('purge_offline_workers', 0):
            body = json.loads(self.get('/api/workers').body)
        self.assertNotIn('w2', body)
        self.assertNotIn('w2', self._app.workers)

    def test_update_workers_populates_cache_after_await(self, m_inspect):
        # The cache write happens inside the awaited coroutine, not via a deferred
        # ioloop callback -- so it is populated the instant the await returns.
        celery = self._app.capp
        celery.control.inspect = mock.Mock()
        celery.control.inspect.return_value.inspect_method = mock.Mock(
            return_value=inspect_response
        )

        self.io_loop.run_sync(self._app.update_workers)

        self.assertIn('inspect_method', self._app.workers['celery@worker1'])
