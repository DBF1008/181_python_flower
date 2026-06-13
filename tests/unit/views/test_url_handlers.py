import os
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from tornado.web import url

from flower.app import rewrite_handler
from flower.urls import settings
from tests.unit import AsyncHTTPTestCase


class UrlsTests(AsyncHTTPTestCase):
    def test_workers_url(self):
        r = self.get('/workers')
        self.assertEqual(200, r.code)

    def test_root_url(self):
        r = self.get('/')
        self.assertEqual(200, r.code)

    def test_tasks_api_url(self):
        with patch.dict(os.environ, {"FLOWER_UNAUTHENTICATED_API": "true"}):
            r = self.get('/api/tasks')
            self.assertEqual(200, r.code)


class URLPrefixTests(AsyncHTTPTestCase):
    def setUp(self):
        self.url_prefix = '/test_root'
        with self.mock_option('url_prefix', self.url_prefix):
            super().setUp()

    def test_tuple_handler_rewrite(self):
        r = self.get(self.url_prefix + '/workers')
        self.assertEqual(200, r.code)

    def test_root_url(self):
        r = self.get(self.url_prefix + '/')
        self.assertEqual(200, r.code)

    def test_tasks_api_url(self):
        with patch.dict(os.environ, {'FLOWER_UNAUTHENTICATED_API': 'true'}):
            r = self.get(self.url_prefix + '/api/tasks')
            self.assertEqual(200, r.code)

    def test_base_url_no_longer_working(self):
        r = self.get('/')
        self.assertEqual(404, r.code)


class RewriteHandlerTests(AsyncHTTPTestCase):
    def target(self):
        return None

    def test_url_rewrite_using_URLSpec(self):
        old_handler = url(r"/", self.target, name='test')
        new_handler = rewrite_handler(old_handler, 'test_root')
        self.assertIsInstance(new_handler, url)
        self.assertTrue(new_handler.regex.match('/test_root/'))
        self.assertFalse(new_handler.regex.match('/'))
        self.assertFalse(new_handler.regex.match('/'))

    def test_url_rewrite_using_tuple(self):
        old_handler = (r"/", self.target)
        new_handler = rewrite_handler(old_handler, 'test_root')
        self.assertIsInstance(new_handler, tuple)
        self.assertEqual(new_handler[0], '/test_root/')


class URLPrefixRenderTests(AsyncHTTPTestCase):
    """Under ``url_prefix`` a rendered page must emit the normalized prefix
    (hidden ``#url_prefix`` input) and prefixed static URLs."""

    def setUp(self):
        self.url_prefix = '/test_root'
        self._settings_snapshot = dict(settings)
        # Mirror production wiring: extract_settings() prefixes static_url_prefix.
        settings['static_url_prefix'] = '/test_root/static/'
        with self.mock_option('url_prefix', self.url_prefix):
            super().setUp()

    def tearDown(self):
        settings.clear()
        settings.update(self._settings_snapshot)
        super().tearDown()

    def test_render_emits_normalized_prefix_and_static(self):
        r = self.get(self.url_prefix + '/')
        self.assertEqual(200, r.code)
        body = r.body.decode()
        # Hidden input that the frontend JS reads as its single prefix source.
        self.assertIn('value="/test_root"', body)
        # Static assets carry the prefix (version query string may follow).
        self.assertIn('/test_root/static/css/bootstrap.min.css', body)


class URLPrefixLoginRedirectTests(AsyncHTTPTestCase):
    """Under ``url_prefix`` an unauthenticated GET to a protected page must
    302-redirect to the prefixed login URL with a prefixed ``next``."""

    def setUp(self):
        self.url_prefix = '/test_root'
        self._settings_snapshot = dict(settings)
        settings['login_url'] = '/test_root/login'
        with self.mock_option('url_prefix', self.url_prefix):
            super().setUp()

    def tearDown(self):
        settings.clear()
        settings.update(self._settings_snapshot)
        super().tearDown()

    def test_unauthenticated_get_redirects_with_prefixed_next(self):
        with self.mock_option('auth', '.*@example.com'):
            r = self.get(self.url_prefix + '/', follow_redirects=False)
        self.assertEqual(302, r.code)
        location = r.headers['Location']
        self.assertTrue(location.startswith('/test_root/login'), location)
        next_param = parse_qs(urlsplit(location).query).get('next', [''])[0]
        self.assertEqual('/test_root/', next_param)
