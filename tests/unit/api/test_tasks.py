import json
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from unittest.mock import Mock, PropertyMock, patch

import celery.states as states
from celery.events import Event
from celery.result import AsyncResult

from flower.events import EventsState
from tests.unit.utils import task_succeeded_events

from . import BaseApiTestCase


class ApplyTests(BaseApiTestCase):
    def test_apply(self):
        result = 'result'
        with patch('celery.result.AsyncResult.state', new_callable=PropertyMock) as mock_state:
            with patch('celery.result.AsyncResult.result', new_callable=PropertyMock) as mock_result:
                mock_state.return_value = states.SUCCESS
                mock_result.return_value = result

                ar = AsyncResult(123)
                ar.get = Mock(return_value=result)

                task = self._app.capp.tasks['foo'] = Mock()
                task.apply_async = Mock(return_value=ar)

                r = self.post('/api/task/apply/foo', body='')

        self.assertEqual(200, r.code)
        body = bytes.decode(r.body)
        self.assertEqual(result, json.loads(body)['result'])
        task.apply_async.assert_called_once_with(args=[], kwargs={})


class AsyncApplyTests(BaseApiTestCase):
    def test_async_apply(self):
        task = self._app.capp.tasks['foo'] = Mock()
        task.apply_async = Mock(return_value=AsyncResult(123))
        r = self.post('/api/task/async-apply/foo', body={})

        self.assertEqual(200, r.code)
        task.apply_async.assert_called_once_with(args=[], kwargs={})

    def test_async_apply_eta(self):
        task = self._app.capp.tasks['foo'] = Mock()
        task.apply_async = Mock(return_value=AsyncResult(123))
        tomorrow = datetime.utcnow() + timedelta(days=1)
        r = self.post('/api/task/async-apply/foo',
                      body='{"eta": "%s"}' % tomorrow)

        self.assertEqual(200, r.code)
        task.apply_async.assert_called_once_with(
            args=[], kwargs={}, eta=tomorrow)

    def test_async_apply_countdown(self):
        task = self._app.capp.tasks['foo'] = Mock()
        task.apply_async = Mock(return_value=AsyncResult(123))
        r = self.post('/api/task/async-apply/foo',
                      body='{"countdown": "3"}')

        self.assertEqual(200, r.code)
        task.apply_async.assert_called_once_with(
            args=[], kwargs={}, countdown=3)

    def test_async_apply_expires(self):
        task = self._app.capp.tasks['foo'] = Mock()
        task.apply_async = Mock(return_value=AsyncResult(123))
        r = self.post('/api/task/async-apply/foo',
                      body='{"expires": "60"}')

        self.assertEqual(200, r.code)
        task.apply_async.assert_called_once_with(
            args=[], kwargs={}, expires=60)

    def test_async_apply_expires_datetime(self):
        task = self._app.capp.tasks['foo'] = Mock()
        task.apply_async = Mock(return_value=AsyncResult(123))
        tomorrow = datetime.utcnow() + timedelta(days=1)
        r = self.post('/api/task/async-apply/foo',
                      body='{"expires": "%s"}' % tomorrow)

        self.assertEqual(200, r.code)
        task.apply_async.assert_called_once_with(
            args=[], kwargs={}, expires=tomorrow)


class MockTasks:

    @staticmethod
    def get_task_by_id(events, task_id):
        from celery.events.state import Task
        return Task()


class TaskTests(BaseApiTestCase):
    def setUp(self):
        self.app = super().get_app()
        super().setUp()

    def get_app(self, capp=None):
        return self.app

    @patch('flower.api.tasks.tasks', new=MockTasks)
    def test_task_info(self):
        self.get('/api/task/info/123')

    def test_tasks_pagination(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='123')
        events += task_succeeded_events(worker='worker1', name='task2',
                                        id='456')
        events += task_succeeded_events(worker='worker1', name='task3',
                                        id='789')
        events += task_succeeded_events(worker='worker1', name='task4',
                                        id='666')

        # for i, e in enumerate(sorted(events, key=lambda event: event['uuid'])):

        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self.app.events.state = state

        # Test limit 4 and offset 0
        params = dict(limit=4, offset=0, sort_by='name')

        r = self.get('/api/tasks?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"), object_pairs_hook=OrderedDict)

        self.assertEqual(200, r.code)
        self.assertEqual(4, len(table))
        firstFetchedTaskName = table[list(table)[0]]['name']
        lastFetchedTaskName = table[list(table)[-1]]['name']
        self.assertEqual("task1", firstFetchedTaskName)
        self.assertEqual("task4", lastFetchedTaskName)

        # Test limit 4 and offset 1
        params = dict(limit=4, offset=1, sort_by='name')

        r = self.get('/api/tasks?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"), object_pairs_hook=OrderedDict)

        self.assertEqual(200, r.code)
        self.assertEqual(3, len(table))
        firstFetchedTaskName = table[list(table)[0]]['name']
        lastFetchedTaskName = table[list(table)[-1]]['name']
        self.assertEqual("task2", firstFetchedTaskName)
        self.assertEqual("task4", lastFetchedTaskName)

        # Test limit 4 and offset -1 (-1 should act as 0)
        params = dict(limit=4, offset=-1, sort_by="name")

        r = self.get('/api/tasks?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"), object_pairs_hook=OrderedDict)

        self.assertEqual(200, r.code)
        self.assertEqual(4, len(table))
        firstFetchedTaskName = table[list(table)[0]]['name']
        lastFetchedTaskName = table[list(table)[-1]]['name']
        self.assertEqual("task1", firstFetchedTaskName)
        self.assertEqual("task4", lastFetchedTaskName)

        # Test limit 2 and offset 1
        params = dict(limit=2, offset=1, sort_by='name')

        r = self.get('/api/tasks?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"), object_pairs_hook=OrderedDict)

        self.assertEqual(200, r.code)
        self.assertEqual(2, len(table))
        firstFetchedTaskName = table[list(table)[0]]['name']
        lastFetchedTaskName = table[list(table)[-1]]['name']
        self.assertEqual("task2", firstFetchedTaskName)
        self.assertEqual("task3", lastFetchedTaskName)

        # Test limit 4 with search
        params = dict(limit=4, offset=0, sort_by='name', search='task')

        r = self.get('/api/tasks?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"), object_pairs_hook=OrderedDict)

        self.assertEqual(200, r.code)
        self.assertEqual(4, len(table))
        firstFetchedTaskName = table[list(table)[0]]['name']
        lastFetchedTaskName = table[list(table)[-1]]['name']
        self.assertEqual("task1", firstFetchedTaskName)
        self.assertEqual("task4", lastFetchedTaskName)

        # Test limit 4 with search
        params = dict(limit=4, offset=0, sort_by='name', search='task1')

        r = self.get('/api/tasks?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"), object_pairs_hook=OrderedDict)

        self.assertEqual(200, r.code)
        self.assertEqual(1, len(table))
        firstFetchedTaskName = table[list(table)[0]]['name']
        self.assertEqual("task1", firstFetchedTaskName)


class DispatchValidationTests(BaseApiTestCase):
    """Malformed input must be rejected identically (HTTP 400) across every
    task-dispatch entry point, instead of one endpoint 400ing and another
    leaking a 500."""

    DISPATCH_ENDPOINTS = (
        '/api/task/apply/foo',
        '/api/task/async-apply/foo',
        '/api/task/send-task/foo',
    )

    def _register_mock_task(self):
        task = self._app.capp.tasks['foo'] = Mock()
        task.apply_async = Mock(return_value=AsyncResult(123))
        self._app.capp.send_task = Mock(return_value=AsyncResult(123))
        return task

    def test_invalid_option_type_returns_400(self):
        # Non-string eta/countdown/expires used to leak a TypeError as a 500.
        bad_bodies = (
            '{"eta": 123}',
            '{"countdown": [1, 2]}',
            '{"expires": null}',
            '{"eta": "not-a-date"}',
        )
        for url in self.DISPATCH_ENDPOINTS:
            for body in bad_bodies:
                task = self._register_mock_task()
                r = self.post(url, body=body)
                self.assertEqual(
                    400, r.code,
                    msg=f'POST {url} body={body} returned {r.code}')
                # Rejected before the task was ever dispatched.
                task.apply_async.assert_not_called()
                self._app.capp.send_task.assert_not_called()

    def test_args_must_be_an_array(self):
        for url in self.DISPATCH_ENDPOINTS:
            self._register_mock_task()
            r = self.post(url, body='{"args": {"not": "a list"}}')
            self.assertEqual(400, r.code, msg=f'POST {url} returned {r.code}')

    def test_kwargs_must_be_an_object(self):
        # kwargs was never validated and a non-dict crashed apply_async (500).
        for url in self.DISPATCH_ENDPOINTS:
            self._register_mock_task()
            r = self.post(url, body='{"kwargs": [1, 2]}')
            self.assertEqual(400, r.code, msg=f'POST {url} returned {r.code}')

    def test_invalid_json_body_returns_400(self):
        for url in self.DISPATCH_ENDPOINTS:
            self._register_mock_task()
            r = self.post(url, body='{not valid json')
            self.assertEqual(400, r.code, msg=f'POST {url} returned {r.code}')


class SendTaskTests(BaseApiTestCase):
    """send-task must normalize apply_async options exactly like apply and
    async-apply (it previously forwarded raw strings)."""

    def _mock_send_task(self):
        send_task = self._app.capp.send_task = Mock(return_value=AsyncResult(123))
        return send_task

    def test_send_task(self):
        send_task = self._mock_send_task()
        r = self.post('/api/task/send-task/foo', body={})

        self.assertEqual(200, r.code)
        send_task.assert_called_once_with('foo', args=[], kwargs={})

    def test_send_task_normalizes_eta(self):
        send_task = self._mock_send_task()
        tomorrow = datetime.utcnow() + timedelta(days=1)
        r = self.post('/api/task/send-task/foo', body='{"eta": "%s"}' % tomorrow)

        self.assertEqual(200, r.code)
        send_task.assert_called_once_with('foo', args=[], kwargs={}, eta=tomorrow)

    def test_send_task_normalizes_countdown(self):
        send_task = self._mock_send_task()
        r = self.post('/api/task/send-task/foo', body='{"countdown": "3"}')

        self.assertEqual(200, r.code)
        send_task.assert_called_once_with('foo', args=[], kwargs={}, countdown=3)

    def test_send_task_normalizes_expires(self):
        send_task = self._mock_send_task()
        r = self.post('/api/task/send-task/foo', body='{"expires": "60"}')

        self.assertEqual(200, r.code)
        send_task.assert_called_once_with('foo', args=[], kwargs={}, expires=60)


class ApplyBackendTests(BaseApiTestCase):
    @patch('flower.api.tasks.BaseTaskHandler.backend_configured',
           return_value=True)
    def test_apply_includes_state(self, _backend):
        with patch('celery.result.AsyncResult.state', new_callable=PropertyMock) as mock_state, \
                patch('celery.result.AsyncResult.result', new_callable=PropertyMock) as mock_result:
            mock_state.return_value = states.SUCCESS
            mock_result.return_value = 'result'

            ar = AsyncResult(123)
            ar.get = Mock(return_value='result')

            task = self._app.capp.tasks['foo'] = Mock()
            task.apply_async = Mock(return_value=ar)

            r = self.post('/api/task/apply/foo', body='')

        self.assertEqual(200, r.code)
        body = json.loads(r.body.decode())
        self.assertEqual(states.SUCCESS, body['state'])
        self.assertEqual('result', body['result'])

    @patch('flower.api.tasks.BaseTaskHandler.backend_configured',
           return_value=False)
    def test_apply_without_backend_returns_503(self, _backend):
        # apply blocks for a result; without a backend that is impossible, so it
        # must 503 (like /result and /abort) instead of crashing in result.get().
        task = self._app.capp.tasks['foo'] = Mock()
        task.apply_async = Mock(return_value=AsyncResult(123))

        r = self.post('/api/task/apply/foo', body='')

        self.assertEqual(503, r.code)
        task.apply_async.assert_not_called()


class TaskResultTests(BaseApiTestCase):
    @patch('flower.api.tasks.BaseTaskHandler.backend_configured',
           return_value=False)
    def test_result_without_backend_returns_503(self, _backend):
        r = self.get('/api/task/result/123')
        self.assertEqual(503, r.code)

    def test_result_invalid_timeout_returns_400(self):
        # A non-numeric timeout used to surface as a 500.
        r = self.get('/api/task/result/123?timeout=not-a-number')
        self.assertEqual(400, r.code)

    @patch('flower.api.tasks.BaseTaskHandler.backend_configured',
           return_value=True)
    def test_result_non_encodable_result_is_repr(self, _backend):
        # A result that json cannot encode (here a circular reference) must fall
        # back to repr() rather than raising inside json.dumps (500).
        circular = {}
        circular['self'] = circular

        with patch('celery.result.AsyncResult.state', new_callable=PropertyMock) as mock_state, \
                patch('celery.result.AsyncResult.result', new_callable=PropertyMock) as mock_result, \
                patch('celery.result.AsyncResult.ready', return_value=True):
            mock_state.return_value = states.SUCCESS
            mock_result.return_value = circular

            r = self.get('/api/task/result/123')

        self.assertEqual(200, r.code)
        body = json.loads(r.body.decode())
        self.assertEqual(repr(circular), body['result'])
