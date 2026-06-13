import os
from unittest.mock import MagicMock, patch

from tornado.options import options

from flower.api.control import ControlHandler

from . import BaseApiTestCase


class UnknownWorkerControlTests(BaseApiTestCase):
    def test_unknown_worker_shutdown(self):
        r = self.post('/api/worker/shutdown/test', body={})
        self.assertEqual(404, r.code)

    def test_unknown_worker_pool_restart(self):
        r = self.post('/api/worker/pool/restart/test', body={})
        self.assertEqual(404, r.code)

    def test_unknown_worker_pool_grow(self):
        r = self.post('/api/worker/pool/grow/test', body={'n': 1})
        self.assertEqual(404, r.code)

    def test_unknown_worker_pool_shrink(self):
        r = self.post('/api/worker/pool/shrink/test', body={})
        self.assertEqual(404, r.code)

    def test_unknown_worker_pool_autoscale(self):
        r = self.post('/api/worker/pool/autoscale/test',
                      body={'min': 1, 'max': 5})
        self.assertEqual(404, r.code)

    def test_unknown_worker_add_consumer(self):
        r = self.post('/api/worker/queue/add-consumer/test',
                      body={'queue': 'foo'})
        self.assertEqual(404, r.code)

    def test_unknown_worker_cancel_consumer(self):
        r = self.post('/api/worker/queue/cancel-consumer/test',
                      body={'queue': 'foo'})
        self.assertEqual(404, r.code)


class WorkerControlTests(BaseApiTestCase):
    def setUp(self):
        BaseApiTestCase.setUp(self)
        self.is_worker = ControlHandler.is_worker
        ControlHandler.is_worker = lambda *args: True

    def tearDown(self):
        BaseApiTestCase.tearDown(self)
        ControlHandler.is_worker = self.is_worker

    def test_shutdown(self):
        celery = self._app.capp
        celery.control.broadcast = MagicMock()
        r = self.post('/api/worker/shutdown/test', body={})
        self.assertEqual(200, r.code)
        celery.control.broadcast.assert_called_once_with('shutdown',
                                                         destination=['test'])

    def test_pool_restart(self):
        celery = self._app.capp
        celery.control.broadcast = MagicMock(
            return_value=[{'test': {'ok': 'pool restarted'}}])
        r = self.post('/api/worker/pool/restart/test', body={})
        self.assertEqual(200, r.code)
        celery.control.broadcast.assert_called_once_with(
            'pool_restart',
            arguments={'reload': False},
            destination=['test'],
            reply=True,
        )

    def test_pool_restart_failure(self):
        celery = self._app.capp
        celery.control.broadcast = MagicMock(
            return_value=[{'test': {'error': 'pool restart not enabled'}}])
        r = self.post('/api/worker/pool/restart/test', body={})
        self.assertEqual(403, r.code)
        self.assertIn(b'pool restart not enabled', r.body)

    def test_pool_grow(self):
        celery = self._app.capp
        celery.control.pool_grow = MagicMock(
            return_value=[{'test': {'ok': 'pool grew by 3'}}])
        r = self.post('/api/worker/pool/grow/test', body={'n': 3})
        self.assertEqual(200, r.code)
        celery.control.pool_grow.assert_called_once_with(
            n=3, reply=True, destination=['test'])

    def test_pool_grow_failure(self):
        celery = self._app.capp
        celery.control.pool_grow = MagicMock(
            return_value=[{'test': {'error': 'cannot grow'}}])
        r = self.post('/api/worker/pool/grow/test', body={'n': 3})
        self.assertEqual(403, r.code)
        self.assertIn(b'cannot grow', r.body)

    def test_pool_shrink(self):
        celery = self._app.capp
        celery.control.pool_shrink = MagicMock(
            return_value=[{'test': {'ok': 'pool shrunk by 1'}}])
        r = self.post('/api/worker/pool/shrink/test', body={})
        self.assertEqual(200, r.code)
        celery.control.pool_shrink.assert_called_once_with(
            n=1, reply=True, destination=['test'])

    def test_pool_shrink_failure(self):
        celery = self._app.capp
        celery.control.pool_shrink = MagicMock(
            return_value=[{'test': {'error': 'cannot shrink below 1'}}])
        r = self.post('/api/worker/pool/shrink/test', body={})
        self.assertEqual(403, r.code)
        self.assertIn(b'cannot shrink below 1', r.body)

    def test_pool_autoscale(self):
        celery = self._app.capp
        celery.control.broadcast = MagicMock(
            return_value=[{'test': {'ok': 'autoscale set'}}])
        r = self.post('/api/worker/pool/autoscale/test',
                      body={'min': 2, 'max': 5})
        self.assertEqual(200, r.code)
        celery.control.broadcast.assert_called_once_with(
            'autoscale',
            reply=True, destination=['test'],
            arguments={'min': 2, 'max': 5})

    def test_pool_autoscale_failure(self):
        celery = self._app.capp
        celery.control.broadcast = MagicMock(
            return_value=[{'test': {'error': 'autoscaler not configured'}}])
        r = self.post('/api/worker/pool/autoscale/test',
                      body={'min': 2, 'max': 5})
        self.assertEqual(403, r.code)
        self.assertIn(b'autoscaler not configured', r.body)

    def test_add_consumer(self):
        celery = self._app.capp
        celery.control.broadcast = MagicMock(
            return_value=[{'test': {'ok': 'add consumer foo'}}])
        r = self.post('/api/worker/queue/add-consumer/test',
                      body={'queue': 'foo'})
        self.assertEqual(200, r.code)
        celery.control.broadcast.assert_called_once_with(
            'add_consumer',
            reply=True, destination=['test'],
            arguments={'queue': 'foo'})

    def test_add_consumer_failure(self):
        celery = self._app.capp
        celery.control.broadcast = MagicMock(
            return_value=[{'test': {'error': 'queue not found'}}])
        r = self.post('/api/worker/queue/add-consumer/test',
                      body={'queue': 'foo'})
        self.assertEqual(403, r.code)
        self.assertIn(b'queue not found', r.body)

    def test_cancel_consumer(self):
        celery = self._app.capp
        celery.control.broadcast = MagicMock(
            return_value=[{'test': {'ok': 'no longer consuming from foo'}}])
        r = self.post('/api/worker/queue/cancel-consumer/test',
                      body={'queue': 'foo'})
        self.assertEqual(200, r.code)
        celery.control.broadcast.assert_called_once_with(
            'cancel_consumer',
            reply=True, destination=['test'],
            arguments={'queue': 'foo'})

    def test_cancel_consumer_failure(self):
        celery = self._app.capp
        celery.control.broadcast = MagicMock(
            return_value=[{'test': {'error': 'not consuming from foo'}}])
        r = self.post('/api/worker/queue/cancel-consumer/test',
                      body={'queue': 'foo'})
        self.assertEqual(403, r.code)
        self.assertIn(b'not consuming from foo', r.body)

    def test_task_timeout(self):
        celery = self._app.capp
        celery.control.time_limit = MagicMock(
            return_value=[{'foo': {'ok': 'time limits set'}}])

        r = self.post(
            '/api/task/timeout/celery.map',
            body={'workername': 'foo', 'hard': 3.1, 'soft': 1.2}
        )
        self.assertEqual(200, r.code)
        celery.control.time_limit.assert_called_once_with(
            'celery.map', hard=3.1, soft=1.2, destination=['foo'],
            reply=True)

    def test_task_timeout_failure(self):
        celery = self._app.capp
        celery.control.time_limit = MagicMock(
            return_value=[{'foo': {'error': 'time limits not supported'}}])

        r = self.post(
            '/api/task/timeout/celery.map',
            body={'workername': 'foo', 'hard': 3.1, 'soft': 1.2}
        )
        self.assertEqual(403, r.code)
        self.assertIn(b'time limits not supported', r.body)

    def test_task_ratelimit(self):
        celery = self._app.capp
        celery.control.rate_limit = MagicMock(
            return_value=[{'foo': {'ok': 'rate limit set'}}])

        r = self.post('/api/task/rate-limit/celery.map',
                      body={'workername': 'foo', 'ratelimit': 20})
        self.assertEqual(200, r.code)
        celery.control.rate_limit.assert_called_once_with(
            'celery.map', '20', destination=['foo'], reply=True)

    def test_task_ratelimit_non_integer(self):
        celery = self._app.capp
        celery.control.rate_limit = MagicMock(
            return_value=[{'foo': {'ok': 'rate limit set'}}])

        r = self.post('/api/task/rate-limit/celery.map',
                      body={'workername': 'foo', 'ratelimit': '11/m'})
        self.assertEqual(200, r.code)
        celery.control.rate_limit.assert_called_once_with(
            'celery.map', '11/m', destination=['foo'], reply=True)

    def test_task_ratelimit_failure(self):
        celery = self._app.capp
        celery.control.rate_limit = MagicMock(
            return_value=[{'foo': {'error': 'Invalid rate limit string'}}])

        r = self.post('/api/task/rate-limit/celery.map',
                      body={'workername': 'foo', 'ratelimit': 'garbage'})
        self.assertEqual(403, r.code)
        self.assertIn(b'Invalid rate limit string', r.body)

    def test_param_escape(self):
        app = self._app.capp
        app.control.broadcast = MagicMock(
            return_value=[{'test': {'ok': 'add consumer foo&amp;bar'}}])
        r = self.post('/api/worker/queue/add-consumer/test',
                      body={'queue': 'foo&bar'})
        self.assertEqual(200, r.code)
        app.control.broadcast.assert_called_once_with(
            'add_consumer',
            reply=True, destination=['test'],
            arguments={'queue': 'foo&amp;bar'})


class TaskControlTests(BaseApiTestCase):
    def test_revoke(self):
        celery = self._app.capp
        celery.control.revoke = MagicMock()
        r = self.post('/api/task/revoke/test', body={})
        self.assertEqual(200, r.code)
        celery.control.revoke.assert_called_once_with('test',
                                                      terminate=False,
                                                      signal='SIGTERM')

    def test_terminate(self):
        celery = self._app.capp
        celery.control.revoke = MagicMock()
        r = self.post('/api/task/revoke/test', body={'terminate': True})
        self.assertEqual(200, r.code)
        celery.control.revoke.assert_called_once_with('test',
                                                      terminate=True,
                                                      signal='SIGTERM')

    def test_terminate_signal(self):
        celery = self._app.capp
        celery.control.revoke = MagicMock()
        r = self.post('/api/task/revoke/test',
                      body={'terminate': True, 'signal': 'SIGUSR1'})
        self.assertEqual(200, r.code)
        celery.control.revoke.assert_called_once_with('test',
                                                      terminate=True,
                                                      signal='SIGUSR1')


class ControlAuthTests(WorkerControlTests):
    def test_auth(self):
        with patch.object(options.mockable(), 'basic_auth', ['user1:password1']):
            app = self._app.capp
            app.control.broadcast = MagicMock()
            r = self.post('/api/worker/shutdown/test', body={})
            self.assertEqual(401, r.code)

    @patch.dict(os.environ, {'FLOWER_UNAUTHENTICATED_API': ''})
    def test_auth_without_env_var(self):
        app = self._app.capp
        app.control.broadcast = MagicMock()
        r = self.post('/api/worker/shutdown/test', body={})
        self.assertEqual(401, r.code)


class ErrorResponseTests(BaseApiTestCase):
    """Test error_reason(), _is_success_response(), and _get_ok_message()
    edge cases directly on the ControlHandler methods."""

    def _make_handler(self):
        """Create a minimal ControlHandler for unit testing helper methods."""
        from unittest.mock import MagicMock as Mock
        handler = object.__new__(ControlHandler)
        handler.application = Mock()
        handler.request = Mock()
        return handler

    # --- error_reason ---

    def test_error_reason_none_response(self):
        handler = self._make_handler()
        self.assertEqual(handler.error_reason('w', None),
                         'No response from worker')

    def test_error_reason_empty_list(self):
        handler = self._make_handler()
        self.assertEqual(handler.error_reason('w', []),
                         'No response from worker')

    def test_error_reason_non_list(self):
        handler = self._make_handler()
        self.assertEqual(handler.error_reason('w', 'garbage'),
                         'Unexpected response: garbage')

    def test_error_reason_non_dict_entry(self):
        handler = self._make_handler()
        # Non-dict entries in the response list are skipped
        self.assertEqual(handler.error_reason('w', ['bad']),
                         'Unknown reason')

    def test_error_reason_missing_worker_key_with_fallback(self):
        handler = self._make_handler()
        response = [{'other_worker': {'error': 'something broke'}}]
        self.assertEqual(handler.error_reason('my_worker', response),
                         'something broke')

    def test_error_reason_string_value_for_worker(self):
        handler = self._make_handler()
        response = [{'w': 'some error string'}]
        self.assertEqual(handler.error_reason('w', response),
                         'some error string')

    def test_error_reason_correct_extraction(self):
        handler = self._make_handler()
        response = [{'w': {'error': 'pool restart not enabled'}}]
        self.assertEqual(handler.error_reason('w', response),
                         'pool restart not enabled')

    def test_error_reason_no_error_key(self):
        handler = self._make_handler()
        response = [{'w': {'ok': 'done'}}]
        self.assertEqual(handler.error_reason('w', response),
                         'Unknown reason')

    # --- _is_success_response ---

    def test_is_success_none(self):
        handler = self._make_handler()
        self.assertFalse(handler._is_success_response('w', None))

    def test_is_success_empty_list(self):
        handler = self._make_handler()
        self.assertFalse(handler._is_success_response('w', []))

    def test_is_success_non_list(self):
        handler = self._make_handler()
        self.assertFalse(handler._is_success_response('w', 'bad'))

    def test_is_success_non_dict_entry(self):
        handler = self._make_handler()
        self.assertFalse(handler._is_success_response('w', ['bad']))

    def test_is_success_with_ok_key(self):
        handler = self._make_handler()
        response = [{'w': {'ok': 'done'}}]
        self.assertTrue(handler._is_success_response('w', response))

    def test_is_success_with_error_key(self):
        handler = self._make_handler()
        response = [{'w': {'error': 'failed'}}]
        self.assertFalse(handler._is_success_response('w', response))

    def test_is_success_missing_worker_key(self):
        handler = self._make_handler()
        response = [{'other_worker': {'ok': 'done'}}]
        self.assertFalse(handler._is_success_response('my_worker', response))

    def test_is_success_string_value_not_dict(self):
        """Old test mock format — string value should NOT be success."""
        handler = self._make_handler()
        response = [{'w': 'ok'}]
        self.assertFalse(handler._is_success_response('w', response))

    def test_is_success_none_workername_broadcast(self):
        """When workername is None, check first entry in response."""
        handler = self._make_handler()
        response = [{'some_worker': {'ok': 'done'}}]
        self.assertTrue(handler._is_success_response(None, response))

    def test_is_success_none_workername_error(self):
        handler = self._make_handler()
        response = [{'some_worker': {'error': 'failed'}}]
        self.assertFalse(handler._is_success_response(None, response))

    # --- _get_ok_message ---

    def test_get_ok_message_with_workername(self):
        handler = self._make_handler()
        response = [{'w': {'ok': 'pool grew by 3'}}]
        self.assertEqual(handler._get_ok_message('w', response),
                         'pool grew by 3')

    def test_get_ok_message_fallback(self):
        handler = self._make_handler()
        response = [{'other': {'ok': 'done'}}]
        self.assertEqual(handler._get_ok_message('w', response),
                         'done')

    def test_get_ok_message_none_workername(self):
        handler = self._make_handler()
        response = [{'some_worker': {'ok': 'limits set'}}]
        self.assertEqual(handler._get_ok_message(None, response),
                         'limits set')

    def test_get_ok_message_empty_response(self):
        handler = self._make_handler()
        self.assertEqual(handler._get_ok_message('w', []), '')
        self.assertEqual(handler._get_ok_message('w', None), '')

    # --- None response through HTTP ---

    def test_pool_restart_no_response(self):
        """Simulate worker unreachable (None response)."""
        celery = self._app.capp
        celery.control.broadcast = MagicMock(return_value=None)
        # Need is_worker to return True
        ControlHandler.is_worker = lambda *args: True
        try:
            r = self.post('/api/worker/pool/restart/test', body={})
            self.assertEqual(403, r.code)
            self.assertIn(b'No response from worker', r.body)
        finally:
            del ControlHandler.is_worker

    def test_pool_grow_empty_response(self):
        """Simulate empty response list."""
        celery = self._app.capp
        celery.control.pool_grow = MagicMock(return_value=[])
        ControlHandler.is_worker = lambda *args: True
        try:
            r = self.post('/api/worker/pool/grow/test', body={'n': 1})
            self.assertEqual(403, r.code)
            self.assertIn(b'No response from worker', r.body)
        finally:
            del ControlHandler.is_worker
