# 工作台本地服务：静态托管 + ComfyUI 反代（同源，彻底绕开 CORS）
# 用法：python cors_proxy.py [端口] [--open] [上游地址]
#   浏览器打开 http://127.0.0.1:8199/ 即为工作台本体
#   页面里的 /comfy/* 请求由本进程转发到 http://127.0.0.1:8188/*
import http.server
import io
import json
import os
import re
import socketserver
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

UP = 'http://127.0.0.1:8188'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = '/comfy'

# 外部接口直通（通用）：/relay/* 把请求转给「X-Relay-Target」头里给的地址，
# 前端把界面里填的接口地址原样贴进来，所以换中转站 / 自建网关都不用改这里。
# 为什么需要它：目标站若校验 Origin 白名单，浏览器从 127.0.0.1:8199 发的请求会被 403
#   （如 casino.soliumbra.com 的 origin_not_allowed，连 localhost 也拒），预检本身也过不去；
#   服务器到服务器不带 Origin，这条才通。上游报错原样交还，不加工。
RELAY = '/relay'
RELAY_UP = 'https://casino.soliumbra.com/api/relay/v1'   # 只在没带 X-Relay-Target 时兜底（老配置）
RELAY_TIMEOUT = 320
# Cloudflare 按 UA 拉黑：Python-urllib/* 一律 Error 1010（实测 Chrome UA / curl UA 都放行）
RELAY_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
# 目标地址不许指回本机/内网，否则任意本机页面都能拿它当内网扫描器
_PRIVATE_HOST = re.compile(r'^(?:10\.|127\.|169\.254\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)')


def relay_target_ok(url):
    try:
        u = urllib.parse.urlsplit(url)
    except Exception:
        return False
    if u.scheme not in ('http', 'https'):
        return False
    h = (u.hostname or '').lower()
    if not h or h in ('localhost', '::1', '0.0.0.0'):
        return False
    return not _PRIVATE_HOST.match(h)

# 显式禁用系统代理：否则设了 HTTP_PROXY 的机器上，连本机 8188 也会被绕出去
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 「这个文件里有没有文本编码器/VAE」只看张量名前缀就够了。
# Anima 那批 ckpt 只有 model./net. 开头的 685 个张量 → 两个都 False。
CLIP_PREFIX = ('cond_stage_model.', 'conditioner.', 'text_encoders.', 'text_model.',
               'te.', 'te1.', 'te2.', 'clip_l.', 'clip_g.', 'clip.', 't5xxl.', 'qwen')
VAE_PREFIX = ('first_stage_model.', 'vae.', 'vae_', 'decoder.')


def safetensors_info(path):
    """只读 safetensors 文件头（几 KB），返回 {keys, prefix, clip, vae, prefixes}。"""
    with open(path, 'rb') as fp:
        raw = fp.read(8)
        if len(raw) < 8:
            raise ValueError('文件太小，不像 safetensors')
        n = struct.unpack('<Q', raw)[0]
        if n <= 0 or n > 64 * 1024 * 1024:
            raise ValueError('头长度异常：%d（不是 safetensors？）' % n)
        hdr = json.loads(fp.read(n).decode('utf-8', 'replace'))
    keys = [k for k in hdr if k != '__metadata__']
    cnt = {}
    for k in keys:
        p = k.split('.')[0] + '.'
        cnt[p] = cnt.get(p, 0) + 1
    order = sorted(cnt.items(), key=lambda kv: -kv[1])
    low = [k.lower() for k in keys]
    return {
        'keys': len(keys),
        'prefix': order[0][0] if order else '',
        'prefixes': [p for p, _ in order[:6]],
        'clip': any(k.startswith(CLIP_PREFIX) for k in low),
        'vae': any(k.startswith(VAE_PREFIX) for k in low),
    }

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.htm': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.md': 'text/plain; charset=utf-8',
    '.txt': 'text/plain; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon',
    '.woff2': 'font/woff2',
    '.bmp': 'image/bmp',
}

# 历史文件浏览：只认图片（视频/文本不进图库），缩略图统一转 JPEG 后放内存缓存
IMG_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp')
DATE_DIR_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_thumb_cache = {}
_thumb_lock = threading.Lock()


def make_thumb(path):
    """生成 360px 缩略图；生成不了就返回 None，调用方直接发原图。"""
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
        with _thumb_lock:
            hit = _thumb_cache.get(key)
        if hit is not None:
            return hit
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im = im.convert('RGB')
            im.thumbnail((360, 360), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=78)
            data = buf.getvalue()
        with _thumb_lock:
            if len(_thumb_cache) > 400:
                _thumb_cache.clear()
            _thumb_cache[key] = data
        return data
    except Exception:
        return None


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def handle_one_request(self):
        # 浏览器提前断开（刷新/关页/图片取消）是常态，不该刷一屏 traceback
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError):
            self.close_connection = True

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def _send(self, code, ctype, data, cors=True, cache=None):
        self.send_response(code)
        if cors:
            self._cors()
        # 缓存头单独算：跨域头不再和缓存头互斥。给了 cache 就按 cache 来（图片要能被浏览器缓存），
        # 没给就沿用接口的老规矩 no-store
        cc = cache or ('no-store' if cors else None)
        if cc:
            self.send_header('Cache-Control', cc)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if self.command != 'HEAD':
            try:
                self.wfile.write(data)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                self.close_connection = True

    # ---------------------------------------------------------------- 静态
    def _static(self, path):
        rel = urllib.parse.unquote(urllib.parse.urlparse(path).path)
        if rel in ('', '/'):
            rel = '/index.html'
        target = os.path.normpath(os.path.join(ROOT, rel.lstrip('/')))
        if os.path.commonpath([os.path.abspath(ROOT), os.path.abspath(target)]) != os.path.abspath(ROOT):
            return False
        if not os.path.isfile(target):
            return False
        ext = os.path.splitext(target)[1].lower()
        try:
            with open(target, 'rb') as f:
                data = f.read()
        except OSError:
            return False
        self._send(200, MIME.get(ext, 'application/octet-stream'), data, cors=False)
        return True

    # ---------------------------------------------------------------- 反代
    def _proxy(self, method):
        raw = self.path
        path = raw[len(PREFIX):] if raw.startswith(PREFIX) else raw
        if not path.startswith('/'):
            path = '/' + path
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(UP + path, data=body, method=method)
        ct = self.headers.get('Content-Type')
        if ct:
            req.add_header('Content-Type', ct)
        try:
            with _opener.open(req, timeout=180) as r:
                data = r.read()
                self._send(r.status, r.headers.get('Content-Type', 'application/octet-stream'), data)
        except urllib.error.HTTPError as e:
            try:
                data = e.read()
            except Exception:
                data = b''
            self._send(e.code, 'application/json', data)
        except Exception as e:
            msg = ('upstream 8188 连不上：%s（ComfyUI 没启动？）' % e).encode('utf-8')
            self._send(502, 'text/plain; charset=utf-8', msg)

    def do_OPTIONS(self):
        self._send(204, 'text/plain', b'')

    # ---------------------------------------------------------------- 外部接口直通（/relay）
    def _relay_origin_ok(self):
        # 只让本机同源页面用这条通道，否则任何网页都能把它当开放代理使
        o = self.headers.get('Origin')
        if not o:
            return True                                   # 服务器间 / curl：没有来源，放行
        try:
            u = urllib.parse.urlsplit(o)
        except Exception:
            return False
        if (u.hostname or '').lower() not in ('127.0.0.1', 'localhost', '::1'):
            return False
        try:
            port = u.port or (443 if u.scheme == 'https' else 80)
            return port == self.server.server_address[1]
        except Exception:
            return True

    def _relay(self, method):
        if not self._relay_origin_ok():
            self._send(403, 'application/json',
                       json.dumps({'error': 'relay_origin_blocked',
                                   'message': '/relay 只转发本机页面发起的请求'}).encode('utf-8'))
            return
        # 目标地址随请求走（前端把界面上填的接口地址贴到这个头里），没带就用兜底值
        target = (self.headers.get('X-Relay-Target') or '').strip().rstrip('/')
        if target and not relay_target_ok(target):
            self._send(400, 'application/json',
                       json.dumps({'error': 'relay_target_blocked',
                                   'message': 'X-Relay-Target 只能是外部的 http(s) 地址'}).encode('utf-8'))
            return
        try:
            up = target or RELAY_UP
            raw = self.path
            rest = raw[len(RELAY):]
            if not rest.startswith('/'):
                rest = '/' + rest
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else None
            req = urllib.request.Request(up + rest, data=body, method=method)
            # 只转必要头：鉴权、类型、可接受类型。Origin / Referer 一律不带（带上就 403）
            for h in ('Authorization', 'Content-Type', 'Accept'):
                v = self.headers.get(h)
                if v:
                    req.add_header(h, v)
            if not self.headers.get('Accept'):
                req.add_header('Accept', 'application/json')
            req.add_header('User-Agent', RELAY_UA)
            with _opener.open(req, timeout=RELAY_TIMEOUT) as r:
                data = r.read()
                self._send(r.status, r.headers.get('Content-Type') or 'application/json', data)
        except urllib.error.HTTPError as e:
            try:
                data = e.read()
            except Exception:
                data = b''
            # 上游的报错原文照搬（工作台口径：外部报错只留原文）
            self._send(e.code, e.headers.get('Content-Type') or 'application/json', data)
        except Exception as e:
            self._send(502, 'text/plain; charset=utf-8',
                       ('/relay 转发失败（%s）：%s' % (target or RELAY_UP, e)).encode('utf-8'))

    # ---------------------------------------------------------------- 图片另存
    # 浏览器给不了绝对路径，所以由本服务代劳：先从 ComfyUI 的 /view 拿图，再写到用户指定目录
    def _json_body(self):
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b'{}'
        try:
            return json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            return {}

    def _reply(self, obj, code=200):
        self._send(code, 'application/json; charset=utf-8',
                   json.dumps(obj, ensure_ascii=False).encode('utf-8'))

    def _dir_of(self, d):
        d = str(d or '').strip().strip('"').strip("'")
        if not d:
            raise ValueError('保存目录是空的')
        d = os.path.expandvars(os.path.expanduser(d))
        if not os.path.isabs(d):
            raise ValueError('要填绝对路径，或用 ~ 开头（如 ~/Pictures/AI绘图）')
        return os.path.normpath(d)

    def _save_images(self):
        j = self._json_body()
        try:
            d = self._dir_of(j.get('dir'))
        except ValueError as e:
            self._reply({'ok': False, 'error': str(e)}, 400)
            return
        if j.get('sub'):
            d = os.path.join(d, time.strftime('%Y-%m-%d'))
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            self._reply({'ok': False, 'error': '建目录失败：%s' % e}, 200)
            return
        saved, errs = [], []
        for f in (j.get('files') or [])[:16]:
            fn = os.path.basename(str(f.get('filename') or ''))
            ext = os.path.splitext(fn)[1].lower()
            if not fn or ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4'):
                continue
            q = urllib.parse.urlencode({'filename': fn,
                                        'subfolder': str(f.get('subfolder') or ''),
                                        'type': str(f.get('type') or 'output')})
            try:
                with _opener.open(UP + '/view?' + q, timeout=90) as r:
                    data = r.read()
                dst = os.path.join(d, fn)
                base, e2 = os.path.splitext(fn)
                i = 1
                while os.path.exists(dst):
                    dst = os.path.join(d, '%s_%d%s' % (base, i, e2))
                    i += 1
                with open(dst, 'wb') as fp:
                    fp.write(data)
                saved.append(dst)
            except Exception as e:
                errs.append('%s：%s' % (fn, e))
        self._reply({'ok': bool(saved), 'dir': d, 'saved': saved, 'errors': errs})

    def _mkdir(self):
        j = self._json_body()
        try:
            d = self._dir_of(j.get('dir'))
        except ValueError as e:
            self._reply({'ok': False, 'error': str(e)}, 400)
            return
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, '.wb_write_test')
            with open(probe, 'wb') as fp:
                fp.write(b'1')
            os.remove(probe)
        except OSError as e:
            self._reply({'ok': False, 'error': str(e), 'dir': d}, 200)
            return
        self._reply({'ok': True, 'dir': d})

    def _open_dir(self):
        j = self._json_body()
        try:
            d = self._dir_of(j.get('dir'))
        except ValueError as e:
            self._reply({'ok': False, 'error': str(e)}, 400)
            return
        if not os.path.isdir(d):
            self._reply({'ok': False, 'error': '目录还不存在，先点「测试并创建」', 'dir': d}, 200)
            return
        try:
            if os.name == 'nt':
                os.startfile(d)                       # noqa: 仅 Windows
            else:
                subprocess.Popen(['xdg-open', d])
        except Exception as e:
            self._reply({'ok': False, 'error': str(e), 'dir': d}, 200)
            return
        self._reply({'ok': True, 'dir': d})

    # ---------------------------------------------------------------- 历史文件浏览
    # 扫描自动保存目录：开了「按日期分子目录」就用目录名分组，没开就按文件修改时间分组；
    # 两种混着放也能读。图片本体走 /__wb_img（同源静态），浏览器不必知道绝对路径。
    def _list_images(self):
        j = self._json_body()
        try:
            root = os.path.abspath(self._dir_of(j.get('dir')))
        except ValueError as e:
            self._reply({'ok': False, 'error': str(e)}, 400)
            return
        if not os.path.isdir(root):
            self._reply({'ok': False, 'error': '目录不存在：%s' % root}, 200)
            return
        try:
            per_day = max(20, min(int(j.get('limit') or 600), 2000))
        except (TypeError, ValueError):
            per_day = 600
        days = {}
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                rel_dir = os.path.relpath(dirpath, root)
                parts = [] if rel_dir == '.' else rel_dir.split(os.sep)
                if len(parts) >= 3:
                    dirnames[:] = []
                dirnames[:] = [d for d in dirnames if not d.startswith('.')]
                date = next((p for p in parts if DATE_DIR_RE.match(p)), '')
                day_dir = os.path.join(root, *parts[:parts.index(date) + 1]) if date else root
                for fn in filenames:
                    if os.path.splitext(fn)[1].lower() not in IMG_EXTS:
                        continue
                    p = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    d = date or time.strftime('%Y-%m-%d', time.localtime(st.st_mtime))
                    rel = os.path.relpath(p, root).replace(os.sep, '/')
                    base = {'dir': root, 'path': rel}
                    days.setdefault(d, {'dir': day_dir, 'files': []})['files'].append({
                        'name': fn, 'rel': rel, 'size': st.st_size, 'mtime': int(st.st_mtime),
                        'time': time.strftime('%H:%M:%S', time.localtime(st.st_mtime)),
                        'thumb': '/__wb_img?' + urllib.parse.urlencode(dict(base, thumb='1')),
                        'full': '/__wb_img?' + urllib.parse.urlencode(base),
                    })
        except OSError as e:
            self._reply({'ok': False, 'error': '扫描失败：%s' % e}, 200)
            return
        out = []
        for d in sorted(days, reverse=True):
            fs = sorted(days[d]['files'], key=lambda x: -x['mtime'])
            out.append({'date': d, 'dir': days[d]['dir'], 'count': len(fs), 'files': fs[:per_day]})
        self._reply({'ok': True, 'dir': root, 'days': out,
                     'total': sum(x['count'] for x in out)})

    def _wb_img(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            root = os.path.abspath(self._dir_of((q.get('dir') or [''])[0]))
        except ValueError as e:
            self._send(400, 'text/plain; charset=utf-8', str(e).encode('utf-8'))
            return
        rel = (q.get('path') or [''])[0].replace('\\', '/')
        parts = [p for p in rel.split('/') if p not in ('', '.')]
        target = os.path.abspath(os.path.join(root, *parts))
        try:
            inside = os.path.commonpath([root, target]) == root
        except ValueError:
            inside = False
        ext = os.path.splitext(target)[1].lower()
        if not inside or ext not in IMG_EXTS:
            self._send(403, 'text/plain; charset=utf-8', b'forbidden', cors=False)
            return
        if not os.path.isfile(target):
            self._send(404, 'text/plain; charset=utf-8', b'not found', cors=False)
            return
        data = None
        if (q.get('thumb') or [''])[0] == '1':
            data = make_thumb(target)
        ctype = 'image/jpeg'
        if data is None:
            try:
                with open(target, 'rb') as fp:
                    data = fp.read()
                ctype = MIME.get(ext, 'application/octet-stream')
            except OSError as e:
                self._send(500, 'text/plain; charset=utf-8', str(e).encode('utf-8'), cors=False)
                return
        # cors=True：灯箱要从这张图上读 PNG 文本块（fetch 拿字节），页面用 file:// 打开时也需要跨域头
        self._send(200, ctype, data, cors=True, cache='public, max-age=3600')

    # ---------------------------------------------------------------- 酒馆配置
    # 工作台没有 OAuth，只能吃 Vertex 的「快速模式」API 密钥；密钥存在酒馆的 secrets.json 里。
    # 让用户手抄不现实，这里代读一次（只读，不改任何东西）。
    def _st_vertex(self):
        base = os.environ.get('WB_ST_DIR') or r'G:\jiuguan\SillyTavern\data\default-user'
        sec_p = os.path.join(base, 'secrets.json')
        set_p = os.path.join(base, 'settings.json')
        if not os.path.isfile(sec_p):
            self._reply({'ok': False, 'error': '找不到酒馆的 secrets.json：%s（可用环境变量 WB_ST_DIR 指到 user 目录）' % base}, 200)
            return
        try:
            with open(sec_p, 'r', encoding='utf-8') as f:
                sec = json.load(f)
        except Exception as e:
            self._reply({'ok': False, 'error': '读 secrets.json 失败：%s' % e}, 200)
            return
        raw = sec.get('api_key_vertexai')
        keys = []
        if isinstance(raw, str):
            keys = [raw]
        elif isinstance(raw, list):
            act = [x.get('value') for x in raw if isinstance(x, dict) and x.get('active') and x.get('value')]
            keys = act or [x.get('value') for x in raw if isinstance(x, dict) and x.get('value')]
        key = str(keys[-1]).strip() if keys else ''
        if not key:
            self._reply({'ok': False, 'error': '酒馆里没存 Vertex 密钥（secrets.json → api_key_vertexai 为空）'}, 200)
            return
        proj = region = model = mode = ''
        try:
            with open(set_p, 'r', encoding='utf-8') as f:
                oai = (json.load(f).get('oai_settings') or {})
            proj = oai.get('vertexai_express_project_id') or ''
            region = oai.get('vertexai_region') or ''
            model = oai.get('vertexai_model') or ''
            mode = oai.get('vertexai_auth_mode') or ''
        except Exception:
            pass
        self._reply({'ok': True, 'key': key, 'project': proj, 'region': region or 'global',
                     'model': model or 'gemini-4-argon', 'auth': mode or 'express', 'dir': base})

    # ---------------------------------------------------------------- CKPT 体检
    # 工作台左侧「底模」下拉里的 CKPT 项，有些其实只是纯 DiT 权重（ComfyUI 里
    # CheckpointLoaderSimple 能加载，但 CLIP/VAE 两个输出是 None，出图报
    # "clip input is invalid: None"）。这里只读文件头给个结论，浏览器那边据此决定
    # 要不要补挂 CLIPLoader + VAELoader。
    _folders = None

    def _model_folders(self, folder):
        if H._folders is None:
            with _opener.open(UP + '/experiment/models', timeout=10) as r:
                H._folders = {it.get('name'): (it.get('folders') or []) for it in json.load(r)}
        return H._folders.get(folder) or []

    def _ckptinfo(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        folder = (q.get('dir') or ['checkpoints'])[0] or 'checkpoints'
        name = (q.get('name') or [''])[0]
        if not name:
            self._reply({'ok': False, 'error': '缺 name 参数'}, 400)
            return
        try:
            folders = [str(f).strip() for f in self._model_folders(folder)]
            with _opener.open(UP + '/experiment/models/' + urllib.parse.quote(folder), timeout=20) as r:
                items = json.load(r)
            it = None
            for x in items if isinstance(items, list) else []:
                if x.get('name') == name:
                    it = x
                    break
            if it is None:
                self._reply({'ok': False, 'error': 'ComfyUI 里没有这个文件：%s/%s' % (folder, name)}, 200)
                return
            idx = int(it.get('pathIndex') or 0)
            base = folders[idx] if idx < len(folders) else (folders[0] if folders else '')
            path = os.path.join(base, name.replace('/', os.sep))
            if not os.path.isfile(path):
                self._reply({'ok': False, 'error': '文件不在磁盘上：%s' % path}, 200)
                return
            info = safetensors_info(path)
            info.update({'ok': True, 'path': path, 'size': it.get('size') or os.path.getsize(path)})
            self._reply(info)
        except Exception as e:
            self._reply({'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}, 200)

    def do_GET(self):
        if self.path == '/__wb_ping':
            self._send(200, 'application/json', json.dumps({'wb': 1, 'up': UP}).encode())
            return
        if self.path.startswith('/__wb_ckptinfo'):
            self._ckptinfo()
            return
        if self.path.startswith('/__wb_img'):
            self._wb_img()
            return
        if self.path.startswith(PREFIX):
            self._proxy('GET')
            return
        if self.path.startswith(RELAY):
            self._relay('GET')
            return
        if not self._static(self.path):
            self._send(404, 'text/plain; charset=utf-8', b'not found')

    def do_HEAD(self):
        if self.path.startswith(PREFIX):
            self._proxy('HEAD')
        elif self.path.startswith(RELAY):
            self._relay('HEAD')
        elif not self._static(self.path):
            self._send(404, 'text/plain; charset=utf-8', b'not found')

    def do_POST(self):
        if self.path == '/__wb_save':
            self._save_images()
            return
        if self.path == '/__wb_files':
            self._list_images()
            return
        if self.path == '/__wb_mkdir':
            self._mkdir()
            return
        if self.path == '/__wb_open':
            self._open_dir()
            return
        if self.path == '/__wb_st_vertex':
            self._st_vertex()
            return
        if self.path.startswith(RELAY):
            self._relay('POST')
            return
        self._proxy('POST')

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    # Windows 上 SO_REUSEADDR 允许「抢绑」已在监听的端口，会出现多个进程同时收请求
    # （有的还是旧代码），表现为时好时坏。这里禁掉，端口被占就直接报错。
    allow_reuse_address = (os.name != 'nt')
    daemon_threads = True


if __name__ == '__main__':
    args = [a for a in sys.argv[1:]]
    open_browser = '--open' in args
    args = [a for a in args if a != '--open']
    port = 8199
    if args and args[0].isdigit():
        port = int(args[0])
        args = args[1:]
    if args:
        UP = args[0].rstrip('/')
    try:
        srv = Server(('127.0.0.1', port), H)
    except OSError as e:
        print('端口 %d 起不来：%s' % (port, e), flush=True)
        try:
            with _opener.open('http://127.0.0.1:%d/__wb_ping' % port, timeout=2) as r:
                if r.status == 200:
                    print('  · 已经有一份工作台在跑（可能是旧版本，没有新功能）。')
                    print('  · 先关掉那个黑窗口再启动；或直接用它。也可以换端口：python tools\\cors_proxy.py 8200', flush=True)
        except Exception:
            print('  · 端口被别的软件占用了，换个端口：python tools\\cors_proxy.py 8200', flush=True)
        sys.exit(1)
    url = 'http://127.0.0.1:%d/' % port
    print('工作台已就绪：%s' % url, flush=True)
    print('  · 页面与接口同源，不经过浏览器跨域检查')
    print('  · /comfy/*  ->  %s/*' % UP)
    print('  · /relay/*  ->  X-Relay-Target 指定的地址（默认 %s）' % RELAY_UP)
    print('  · 关掉这个窗口即停止服务')
    if open_browser:
        threading.Timer(0.9, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
