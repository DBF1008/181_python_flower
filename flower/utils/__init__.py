import base64
import os.path
import uuid
from urllib.parse import urlparse

from .. import __version__


def gen_cookie_secret():
    return base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes)


def bugreport(app=None):
    try:
        import celery
        import humanize
        import tornado

        app = app or celery.Celery()

		# pylint: disable=consider-using-f-string
        return 'flower   -> flower:%s tornado:%s humanize:%s%s' % (
            __version__,
            tornado.version,
            getattr(humanize, '__version__', None) or getattr(humanize, 'VERSION'),
            app.bugreport()
        )
    except (ImportError, AttributeError) as e:
        return f"Error when generating bug report: {e}. Have you installed correct versions of Flower's dependencies?"


def abs_path(path):
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        cwd = os.environ.get('PWD') or os.getcwd()
        path = os.path.join(cwd, path)
    return path


def normalize_url_prefix(prefix):
    """Normalize a URL prefix to a consistent format.

    Returns '' if no prefix is configured (None, empty, or whitespace-only).
    Otherwise returns '/prefix' — a single leading slash, no trailing slash.
    """
    if not prefix or not prefix.strip():
        return ''
    return '/' + prefix.strip('/')


def prepend_url(url, prefix):
    """Prepend *prefix* to *url*. Returns *url* unchanged when prefix is empty."""
    normalized = normalize_url_prefix(prefix)
    if not normalized:
        return url
    return normalized + url


def is_safe_redirect_url(url):
    """Return True if *url* is a safe same-origin redirect target.

    Only relative paths starting with '/' are considered safe.
    Absolute URLs (with scheme or netloc) are rejected to prevent
    open-redirect attacks.
    """
    if not url:
        return False
    if not url.startswith('/'):
        return False
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc:
        return False
    return True


def strtobool(val):
    """Convert a string representation of truth to true (1) or false (0).

    True values are 'y', 'yes', 't', 'true', 'on', and '1'; false values
    are 'n', 'no', 'f', 'false', 'off', and '0'.  Raises ValueError if
    'val' is anything else.
    """
    val = val.lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return 1
    if val in ('n', 'no', 'f', 'false', 'off', '0'):
        return 0
    raise ValueError(f"invalid truth value {val!r}")
