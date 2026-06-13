import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from celery import Celery

from flower.utils import (abs_path, bugreport, gen_cookie_secret,
                          normalize_url_prefix, prepend_url, safe_next_path,
                          strtobool)


class BugreportTests(unittest.TestCase):
    def test_default(self):
        report = bugreport()
        self.assertFalse('Error when generating bug report' in report)
        self.assertTrue('tornado' in report)
        self.assertTrue('humanize' in report)
        self.assertTrue('celery' in report)

    def test_with_app(self):
        app = Celery()
        report = bugreport(app)
        self.assertFalse('Error when generating bug report' in report)
        self.assertTrue('tornado' in report)
        self.assertTrue('humanize' in report)
        self.assertTrue('celery' in report)

    def test_when_unable_to_generate_report(self):
        fake_app = Mock()
        fake_app.bugreport.side_effect = ImportError('import error message')
        report = bugreport(fake_app)
        self.assertTrue('Error when generating bug report' in report)
        self.assertTrue('import error message' in report)
        self.assertTrue("Have you installed correct versions of Flower's dependencies?" in report)


class TestGenCookieSecret(unittest.TestCase):
    def test_cookie_secret_generation(self):
        secret1 = gen_cookie_secret()
        secret2 = gen_cookie_secret()
        self.assertNotEqual(secret1, secret2)


class TestAbsPath(unittest.TestCase):
    def test_absolute_path(self):
        self.assertEqual(abs_path('/home/user/file.txt'), '/home/user/file.txt')

    @unittest.skip
    def test_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            original_dir = os.getcwd()
            try:
                os.chdir(tmp_dir)
                path = abs_path('file.txt')
                expected = os.path.join(tmp_dir, 'file.txt')
                self.assertEqual(path, expected)
            finally:
                os.chdir(original_dir)

    def test_relative_path_with_pwd(self):
        with patch.dict(os.environ, {'PWD': '/home/user'}):
            self.assertEqual(abs_path('file.txt'), '/home/user/file.txt')

    def test_home_path(self):
        self.assertEqual(abs_path('~/file.txt'), os.path.join(os.path.expanduser('~'), 'file.txt'))


class TestStrtobool(unittest.TestCase):
    def test_true_values(self):
        self.assertEqual(strtobool('y'), 1)
        self.assertEqual(strtobool('yes'), 1)
        self.assertEqual(strtobool('t'), 1)
        self.assertEqual(strtobool('true'), 1)
        self.assertEqual(strtobool('on'), 1)
        self.assertEqual(strtobool('1'), 1)

    def test_false_values(self):
        self.assertEqual(strtobool('n'), 0)
        self.assertEqual(strtobool('no'), 0)
        self.assertEqual(strtobool('f'), 0)
        self.assertEqual(strtobool('false'), 0)
        self.assertEqual(strtobool('off'), 0)
        self.assertEqual(strtobool('0'), 0)

    def test_invalid_value(self):
        self.assertRaises(ValueError, strtobool, 'invalid')


class TestNormalizeUrlPrefix(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(normalize_url_prefix(''), '')
        self.assertEqual(normalize_url_prefix(None), '')

    def test_single_leading_slash_no_trailing(self):
        self.assertEqual(normalize_url_prefix('flower'), '/flower')
        self.assertEqual(normalize_url_prefix('/flower'), '/flower')
        self.assertEqual(normalize_url_prefix('flower/'), '/flower')
        self.assertEqual(normalize_url_prefix('/flower/'), '/flower')

    def test_collapses_surrounding_slashes(self):
        self.assertEqual(normalize_url_prefix('//a/b//'), '/a/b')


class TestPrependUrl(unittest.TestCase):
    def test_prepend(self):
        self.assertEqual(prepend_url('/login', 'flower'), '/flower/login')
        self.assertEqual(prepend_url('/static/', '/flower/'), '/flower/static/')

    def test_empty_prefix_is_noop(self):
        self.assertEqual(prepend_url('/login', ''), '/login')


class TestSafeNextPath(unittest.TestCase):
    def test_empty_falls_back_to_root(self):
        self.assertEqual(safe_next_path('', ''), '/')
        self.assertEqual(safe_next_path('', 'flower'), '/flower/')
        self.assertEqual(safe_next_path(None, '/flower/'), '/flower/')

    def test_valid_local_path_preserved(self):
        self.assertEqual(
            safe_next_path('/test_root/tasks', '/test_root'),
            '/test_root/tasks')
        self.assertEqual(
            safe_next_path('/test_root/tasks?state=SUCCESS', '/test_root'),
            '/test_root/tasks?state=SUCCESS')

    def test_open_redirect_blocked(self):
        # Every external / scheme-bearing target must fall back to the root.
        for evil in ['//evil.com', 'https://evil.com', 'http://evil.com',
                     '/\\evil.com', '\\\\evil.com', 'javascript:alert(1)',
                     'mailto:x@evil.com']:
            self.assertEqual(
                safe_next_path(evil, '/flower'), '/flower/',
                msg=f'{evil!r} should fall back to root')

    def test_relative_without_leading_slash_blocked(self):
        self.assertEqual(safe_next_path('tasks', '/flower'), '/flower/')
