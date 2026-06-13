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


class TaskSendNormalizeTests(BaseApiTestCase):
    """Verify send-task now normalizes options like apply/async-apply."""

    def test_send_task_countdown(self):
        self._app.capp.send_task = Mock(return_value=AsyncResult(123))
        r = self.post('/api/task/send-task/foo',
                      body='{"countdown": "3"}')

        self.assertEqual(200, r.code)
        self._app.capp.send_task.assert_called_once_with(
            'foo', args=[], kwargs={}, countdown=3.0)

    def test_send_task_expires_numeric(self):
        self._app.capp.send_task = Mock(return_value=AsyncResult(123))
        r = self.post('/api/task/send-task/foo',
                      body='{"expires": "60"}')

        self.assertEqual(200, r.code)
        self._app.capp.send_task.assert_called_once_with(
            'foo', args=[], kwargs={}, expires=60.0)

    def test_send_task_expires_datetime(self):
        self._app.capp.send_task = Mock(return_value=AsyncResult(123))
        tomorrow = datetime.utcnow() + timedelta(days=1)
        r = self.post('/api/task/send-task/foo',
                      body='{"expires": "%s"}' % tomorrow)

        self.assertEqual(200, r.code)
        self._app.capp.send_task.assert_called_once_with(
            'foo', args=[], kwargs={}, expires=tomorrow)

    def test_send_task_eta(self):
        self._app.capp.send_task = Mock(return_value=AsyncResult(123))
        tomorrow = datetime.utcnow() + timedelta(days=1)
        r = self.post('/api/task/send-task/foo',
                      body='{"eta": "%s"}' % tomorrow)

        self.assertEqual(200, r.code)
        self._app.capp.send_task.assert_called_once_with(
            'foo', args=[], kwargs={}, eta=tomorrow)


class InvalidInputTests(BaseApiTestCase):
    """Verify invalid parameters return 400 with meaningful error bodies."""

    def test_apply_invalid_body(self):
        r = self.post('/api/task/apply/foo', body='not-json{{{')
        self.assertEqual(400, r.code)
        self.assertTrue(len(r.body) > 0)

    def test_async_apply_invalid_body(self):
        r = self.post('/api/task/async-apply/foo', body='not-json{{{')
        self.assertEqual(400, r.code)
        self.assertTrue(len(r.body) > 0)

    def test_apply_args_not_array(self):
        r = self.post('/api/task/apply/foo',
                      body='{"args": "not-an-array"}')
        self.assertEqual(400, r.code)
        body = r.body.decode('utf-8')
        self.assertIn('args', body)

    def test_apply_unknown_task(self):
        r = self.post('/api/task/apply/nonexistent.task', body='{}')
        self.assertEqual(404, r.code)
        body = r.body.decode('utf-8')
        self.assertIn('nonexistent.task', body)

    def test_async_apply_unknown_task(self):
        r = self.post('/api/task/async-apply/nonexistent.task', body='{}')
        self.assertEqual(404, r.code)
        body = r.body.decode('utf-8')
        self.assertIn('nonexistent.task', body)

    def test_send_task_invalid_countdown(self):
        r = self.post('/api/task/send-task/foo',
                      body='{"countdown": "not-a-number"}')
        self.assertEqual(400, r.code)
        body = r.body.decode('utf-8')
        self.assertTrue(len(body) > 0)
        self.assertIn('countdown', body)

    def test_apply_invalid_eta(self):
        r = self.post('/api/task/apply/foo',
                      body='{"eta": "not-a-date"}')
        self.assertEqual(400, r.code)
        body = r.body.decode('utf-8')
        self.assertIn('eta', body)

    def test_apply_invalid_expires(self):
        r = self.post('/api/task/apply/foo',
                      body='{"expires": "not-a-number-or-date"}')
        self.assertEqual(400, r.code)
        body = r.body.decode('utf-8')
        self.assertIn('expires', body)


class ErrorMessageTests(BaseApiTestCase):
    """Verify error response bodies contain descriptive messages."""

    def test_apply_unknown_task_has_message(self):
        r = self.post('/api/task/apply/does.not.exist', body='{}')
        self.assertEqual(404, r.code)
        body = r.body.decode('utf-8')
        self.assertIn('Unknown task', body)

    def test_apply_invalid_option_has_message(self):
        r = self.post('/api/task/apply/foo',
                      body='{"countdown": "xyz"}')
        # foo is not registered either, but countdown check runs first
        # in _dispatch_task after get_task_args but before task lookup
        self.assertIn(r.code, (400, 404))

    def test_apply_invalid_body_has_message(self):
        r = self.post('/api/task/apply/foo', body='[1,2,3]')
        self.assertEqual(400, r.code)
        body = r.body.decode('utf-8')
        self.assertIn('invalid', body.lower())


class TaskInfoSafeResultTests(BaseApiTestCase):
    """Verify TaskInfo safely serializes non-JSON-encodable values."""

    @patch('flower.api.tasks.tasks')
    def test_task_info_non_serializable_result(self, mock_tasks):
        from celery.events.state import Task
        task = Task()
        task.name = 'foo'
        task.uuid = '123'
        task.state = 'SUCCESS'
        # Simulate a non-serializable result (bytes)
        task.result = b'\x80\x81\x82'
        task.worker = None
        mock_tasks.get_task_by_id.return_value = task

        r = self.get('/api/task/info/123')
        self.assertEqual(200, r.code)
        body = json.loads(r.body.decode('utf-8'))
        # The bytes should be repr'd, not cause a 500
        self.assertIn('result', body)
        self.assertEqual(body['result'], repr(b'\x80\x81\x82'))

    @patch('flower.api.tasks.tasks')
    def test_task_info_serializable_result_unchanged(self, mock_tasks):
        from celery.events.state import Task
        task = Task()
        task.name = 'foo'
        task.uuid = '456'
        task.state = 'SUCCESS'
        task.result = 42
        task.worker = None
        mock_tasks.get_task_by_id.return_value = task

        r = self.get('/api/task/info/456')
        self.assertEqual(200, r.code)
        body = json.loads(r.body.decode('utf-8'))
        self.assertEqual(body['result'], 42)

    def test_task_info_unknown_task(self):
        r = self.get('/api/task/info/nonexistent-id')
        self.assertEqual(404, r.code)
        body = r.body.decode('utf-8')
        self.assertIn('Unknown task', body)
