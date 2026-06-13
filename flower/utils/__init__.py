import base64
import os.path
import uuid
from urllib.parse import urlsplit

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
    """Return ``prefix`` as a canonical URL path prefix.

    The result is either an empty string (no prefix) or a string with a single
    leading slash and no trailing slash: ``flower`` and ``/flower/`` both
    normalize to ``/flower``. This is the single source of truth for turning the
    ``url_prefix`` option into something that can be prepended to a path.
    """
    if not prefix:
        return ''
    return '/' + prefix.strip('/')


def prepend_url(url, prefix):
    return normalize_url_prefix(prefix) + url


def safe_next_path(next_url, url_prefix=''):
    """Return a safe in-app redirect target for a user-supplied ``next`` value.

    Falls back to the application root when ``next_url`` is missing or points
    outside the application, preventing open redirects (e.g.
    ``next=https://evil.com`` or ``next=//evil.com``). ``url_prefix`` is the
    application base path; the root fallback is ``<prefix>/`` so it matches the
    prefixed root route instead of 404'ing.
    """
    root = normalize_url_prefix(url_prefix) + '/'
    if not next_url:
        return root
    # Browsers treat backslashes as forward slashes, so normalize them before
    # validating to avoid bypasses such as ``/\evil.com``.
    candidate = next_url.replace('\\', '/')
    # Reject protocol-relative URLs (//host) and anything carrying a scheme or
    # network location (https://host, javascript:..., mailto:..., etc).
    if candidate.startswith('//'):
        return root
    split = urlsplit(candidate)
    if split.scheme or split.netloc:
        return root
    # Only allow absolute, in-app paths.
    if not candidate.startswith('/'):
        return root
    return candidate


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
