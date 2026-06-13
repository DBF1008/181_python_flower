# 重构：URL Prefix 与登录回跳链路收口

## Context

Flower 部署在反向代理子路径下时，URL prefix 处理分散在多处：
- 路由重写 (`app.py:rewrite_handler`)
- 设置调整 (`command.py:extract_settings`)
- 模板注入 (`views/__init__.py:BaseHandler.render`)
- 前端 JS (`flower.js:url_prefix()` + 21 处手动拼接)
- 4 个 OAuth handler 各自复制粘贴的 `next` 回跳逻辑

具体问题：
1. `rewrite_handler()` 丢弃 3 元组的 kwargs，导致 StaticFileHandler 在 prefix 下失效
2. `BaseHandler.get_argument()` 对所有字符串做 `xhtml_escape`，`&` 变 `&amp;`，破坏含 query string 的 `next` URL
3. 4 个 OAuth handler 各自复制 3 行 next 回跳逻辑，不统一
4. 无 open-redirect 防护
5. JS 21 处手动拼接 `url_prefix() + '/api/...'`

---

## 修改计划

### Step 1: 加固 `flower/utils/__init__.py`

**修改 `prepend_url`** + **新增 `normalize_url_prefix`** + **新增 `is_safe_redirect_url`**

```python
from urllib.parse import urlparse

def normalize_url_prefix(prefix):
    """统一前缀格式：无前缀返回 ''，有前缀返回 '/xxx' (无前导重复/尾随斜杠)"""
    if not prefix or not prefix.strip():
        return ''
    return '/' + prefix.strip('/')

def prepend_url(url, prefix):
    """给 url 加前缀，安全处理空前缀"""
    normalized = normalize_url_prefix(prefix)
    if not normalized:
        return url
    return normalized + url

def is_safe_redirect_url(url):
    """校验重定向目标是否为同源的相对路径，防止 open-redirect"""
    if not url:
        return False
    parsed = urlparse(url)
    # 只允许相对路径 (无 scheme、无 netloc)
    if parsed.scheme or parsed.netloc:
        return False
    # 必须以 / 开头
    if not url.startswith('/'):
        return False
    return True
```

### Step 2: 修复 `flower/app.py` 的 `rewrite_handler`

修复 3 元组 kwargs 丢失问题：

```python
def rewrite_handler(handler, url_prefix):
    if isinstance(handler, url):
        return url("/{}{}".format(url_prefix.strip("/"), handler.regex.pattern),
                   handler.handler_class, handler.kwargs, handler.name)
    # 保留 3 元组 (pattern, handler_class, kwargs)
    if len(handler) >= 3:
        return ("/{}{}".format(url_prefix.strip("/"), handler[0]), handler[1], handler[2])
    return ("/{}{}".format(url_prefix.strip("/"), handler[0]), handler[1])
```

### Step 3: 修复 `flower/views/__init__.py`

**3a. 移除 `get_argument` 中的 `xhtml_escape`**

```python
def get_argument(self, name, default=[], strip=True, type=None):
    arg = super().get_argument(name, default, strip)
    # 移除 xhtml_escape — 它破坏了含 & 的 next URL
    # 模板渲染时 Tornado 会自动转义，无需在此处做
    if type is not None:
        try:
            if type is bool:
                arg = strtobool(str(arg))
            else:
                arg = type(arg)
        except (ValueError, TypeError) as exc:
            if arg is None and default is None:
                return arg
            raise tornado.web.HTTPError(
                    400,
                    f"Invalid argument '{arg}' of type '{type.__name__}'") from exc
    return arg
```

**3b. 新增 `_get_safe_next_url` 方法到 BaseHandler**

```python
from ..utils import normalize_url_prefix, is_safe_redirect_url

class BaseHandler(tornado.web.RequestHandler):
    # ... existing code ...

    def get_safe_next_url(self):
        """统一获取安全的登录后回跳 URL。
        从 query param 'next' 读取，验证为同源相对路径，
        默认回退到 url_prefix 或 '/'。
        """
        prefix = normalize_url_prefix(self.application.options.url_prefix)
        default_next = prefix if prefix else '/'
        next_ = super().get_argument('next', default_next, strip=True)
        # 安全校验：不允许跳转到外部站点
        if not is_safe_redirect_url(next_):
            next_ = default_next
        return next_
```

### Step 4: 重构 `flower/views/auth.py` — 收口 4 处 `_on_auth` 回跳

将所有 4 个 OAuth handler 中的回跳逻辑替换为调用 `self.get_safe_next_url()`：

**GoogleAuth2LoginHandler._on_auth** (L77-81) → 
```python
        self.set_secure_cookie("user", str(email))
        self.redirect(self.get_safe_next_url())
```

**GithubLoginHandler._on_auth** (L165-168) → 同上

**GitLabLoginHandler._on_auth** (L257-260) → 同上

**OktaLoginHandler._on_auth** (L356-359) → 同上

### Step 5: 重构 `flower/static/js/flower.js` — 收口前端 prefix 拼接

**5a. 新增 `flowerUrl` 工具函数**

```javascript
function flowerUrl(path) {
    return url_prefix() + path;
}
```

**5b. 替换所有 21 处 `url_prefix() + '...'` 为 `flowerUrl('...')`**

替换规则（所有 `url_prefix() + '/xxx'` → `flowerUrl('/xxx')`）：

| 行号 | 原代码 | 新代码 |
|------|--------|--------|
| 41 | `url_prefix() + name` | `flowerUrl(name)` |
| 44 | `url_prefix() + name` | `flowerUrl(name)` |
| 57 | `url_prefix() + '/api/workers'` | `flowerUrl('/api/workers')` |
| 79 | `url_prefix() + '/api/workers'` | `flowerUrl('/api/workers')` |
| 102 | `url_prefix() + '/api/worker/pool/restart/' + workername` | `flowerUrl('/api/worker/pool/restart/' + workername)` |
| 125 | `url_prefix() + '/api/worker/shutdown/' + workername` | `flowerUrl('/api/worker/shutdown/' + workername)` |
| 148 | `url_prefix() + '/api/worker/pool/grow/' + workername` | `flowerUrl('/api/worker/pool/grow/' + workername)` |
| 172 | `url_prefix() + '/api/worker/pool/shrink/' + workername` | `flowerUrl('/api/worker/pool/shrink/' + workername)` |
| 197 | `url_prefix() + '/api/worker/pool/autoscale/' + workername` | `flowerUrl('/api/worker/pool/autoscale/' + workername)` |
| 222 | `url_prefix() + '/api/worker/queue/add-consumer/' + workername` | `flowerUrl('/api/worker/queue/add-consumer/' + workername)` |
| 250 | `url_prefix() + '/api/worker/queue/cancel-consumer/' + workername` | `flowerUrl('/api/worker/queue/cancel-consumer/' + workername)` |
| 282 | `url_prefix() + '/api/task/timeout/' + taskname` | `flowerUrl('/api/task/timeout/' + taskname)` |
| 301 | `url_prefix() + '/api/task/rate-limit/' + taskname` | `flowerUrl('/api/task/rate-limit/' + taskname)` |
| 325 | `url_prefix() + '/api/task/revoke/' + taskid` | `flowerUrl('/api/task/revoke/' + taskid)` |
| 349 | `url_prefix() + '/api/task/revoke/' + taskid` | `flowerUrl('/api/task/revoke/' + taskid)` |
| 442 | `url_prefix() + '/workers?json=1'` | `flowerUrl('/workers?json=1')` |
| 454 | `url_prefix() + '/tasks' + queryParams` | `flowerUrl('/tasks' + queryParams)` |
| 464 | `url_prefix() + '/worker/' + encodeURIComponent(data)` | `flowerUrl('/worker/' + encodeURIComponent(data))` |
| 557 | `url_prefix() + '/tasks/datatable'` | `flowerUrl('/tasks/datatable')` |
| 579 | `url_prefix() + '/task/' + encodeURIComponent(data)` | `flowerUrl('/task/' + encodeURIComponent(data))` |
| 649 | `url_prefix() + '/worker/' + encodeURIComponent(data)` | `flowerUrl('/worker/' + encodeURIComponent(data))` |

### Step 6: 回归测试 `tests/unit/views/test_url_prefix.py` (新建)

```python
# 测试覆盖场景：

class NormalizeUrlPrefixTests(unittest.TestCase):
    # normalize_url_prefix 各输入场景
    
class PrependUrlTests(unittest.TestCase):
    # prepend_url 各输入场景

class IsSafeRedirectUrlTests(unittest.TestCase):
    # open-redirect 防护测试

class RewriteHandlerKwargsTests(AsyncHTTPTestCase):
    # 3 元组 kwargs 保留测试

class URLPrefixStaticFilesTests(AsyncHTTPTestCase):
    # prefix 下静态资源路由可访问

class LoginRedirectTests(AsyncHTTPTestCase):
    # get_safe_next_url 各场景：
    # - 默认回跳到 prefix
    # - next 参数正常传递
    # - next 含 & 不被转义
    # - 外部 URL 被拦截
    # - 无前缀时默认 /

class GetArgumentNoEscapeTests(AsyncHTTPTestCase):
    # get_argument 不再 xhtml_escape 字符串
```

---

## 文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `flower/utils/__init__.py` | 修改 | 加固 `prepend_url`，新增 `normalize_url_prefix`、`is_safe_redirect_url` |
| `flower/app.py` | 修改 | 修复 `rewrite_handler` 保留 3 元组 kwargs |
| `flower/views/__init__.py` | 修改 | 移除 `xhtml_escape`，新增 `get_safe_next_url` |
| `flower/views/auth.py` | 修改 | 4 个 OAuth handler 统一调用 `get_safe_next_url()` |
| `flower/static/js/flower.js` | 修改 | 新增 `flowerUrl()` 并替换 21 处手动拼接 |
| `tests/unit/views/test_url_prefix.py` | 新建 | 全面回归测试 |

## 验证方式

```bash
cd /Users/dongbufan/work/ai_color/one_claude_project/success/181_python_flower/prompt/p5/p5-qwen-3.7-max
python -m pytest tests/unit/ -v
```

重点验证：
1. 所有现有测试仍然通过
2. 新增测试覆盖上述所有 bug 场景
3. `url_prefix` 设置时，路由、静态资源、登录回跳全链路正确
