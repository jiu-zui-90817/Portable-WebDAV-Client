import os
import unittest

from portable_webdav_client_Pro import MAX_CACHE_ENTRIES, WebDAVApp


def make_app(path="/"):
    """构造一个不创建 Tk 窗口的实例，用于测试纯逻辑方法。"""
    app = object.__new__(WebDAVApp)
    app.current_path = path
    app.cache = {}
    app._current_items = []
    app._sort_column = "name"
    app._sort_reverse = False
    return app


class FormatTests(unittest.TestCase):
    def test_zero_is_not_dash(self):
        self.assertEqual(WebDAVApp.format_size(0), "0 B")

    def test_none_and_invalid(self):
        self.assertEqual(WebDAVApp.format_size(None), "-")
        self.assertEqual(WebDAVApp.format_size("abc"), "-")

    def test_units(self):
        self.assertEqual(WebDAVApp.format_size(1024), "1.0 KB")
        self.assertEqual(WebDAVApp.format_size(1024 * 1024), "1.0 MB")
        self.assertEqual(WebDAVApp.format_size(1024 ** 3), "1.00 GB")

    def test_speed(self):
        self.assertEqual(WebDAVApp.format_speed(0), "0 KB/s")
        self.assertEqual(WebDAVApp.format_speed(2048), "2.0 KB/s")
        self.assertEqual(WebDAVApp.format_speed(2 * 1024 * 1024), "2.00 MB/s")


class PathTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(WebDAVApp._normalize_remote(""), "/")
        self.assertEqual(WebDAVApp._normalize_remote("a//b/"), "/a/b")
        self.assertEqual(WebDAVApp._normalize_remote("//a///b//"), "/a/b")

    def test_parent(self):
        self.assertEqual(WebDAVApp._parent_remote("/"), "/")
        self.assertEqual(WebDAVApp._parent_remote("/a"), "/")
        self.assertEqual(WebDAVApp._parent_remote("/a/b/"), "/a")

    def test_join(self):
        app = make_app("/docs")
        self.assertEqual(app._join_remote("a.txt"), "/docs/a.txt")
        app = make_app("/")
        self.assertEqual(app._join_remote("a.txt"), "/a.txt")


class FileListTests(unittest.TestCase):
    def test_build_items_keeps_same_name_subdirectory(self):
        app = make_app("/foo")
        items = app._build_items([
            {"path": "/foo/foo", "isdir": True, "size": 0},
            {"path": "/foo/a.txt", "isdir": False, "size": 12},
        ])
        names = [item[0] for item in items]
        self.assertIn("foo", names)
        self.assertIn("a.txt", names)

    def test_build_items_deduplicates(self):
        app = make_app("/")
        items = app._build_items([
            {"path": "/a.txt", "isdir": False, "size": 1},
            {"path": "/a.txt", "isdir": False, "size": 1},
        ])
        self.assertEqual([item[0] for item in items], ["a.txt"])

    def test_root_webdav_folder_filtered_but_file_kept(self):
        app = make_app("/")
        items = app._build_items([
            {"path": "/webdav", "isdir": True, "size": 0},
            {"path": "/webdav.txt", "isdir": False, "size": 3},
        ])
        names = [item[0] for item in items]
        self.assertNotIn("webdav", names)
        self.assertIn("webdav.txt", names)

    def test_sort_directories_first(self):
        app = make_app("/")
        app._current_items = [
            ("b.txt", False, 2, "/b.txt"),
            ("zdir", True, 0, "/zdir"),
            ("a.txt", False, 1, "/a.txt"),
        ]
        self.assertEqual([i[0] for i in app._sorted_items()], ["zdir", "a.txt", "b.txt"])
        app._sort_reverse = True
        self.assertEqual([i[0] for i in app._sorted_items()], ["zdir", "b.txt", "a.txt"])

    def test_cache_is_bounded(self):
        app = make_app("/")
        for index in range(MAX_CACHE_ENTRIES + 5):
            app._cache_put("/{}".format(index), [])
        self.assertEqual(len(app.cache), MAX_CACHE_ENTRIES)


class FakeSession:
    def __init__(self):
        self.proxies = {}
        self.verify = True


class FakeClient:
    def __init__(self):
        self.session = FakeSession()
        self.verify = True


class NetworkOptionsTests(unittest.TestCase):
    def test_http_proxy_applied(self):
        client = FakeClient()
        WebDAVApp._apply_network_options(client, "http://127.0.0.1:7890", "")
        self.assertEqual(client.session.proxies["http"], "http://127.0.0.1:7890")
        self.assertEqual(client.session.proxies["https"], "http://127.0.0.1:7890")

    def test_socks_proxy_applied(self):
        client = FakeClient()
        WebDAVApp._apply_network_options(client, "socks5://127.0.0.1:1080", "")
        self.assertEqual(client.session.proxies["https"], "socks5://127.0.0.1:1080")

    def test_invalid_proxy_rejected(self):
        with self.assertRaises(ValueError):
            WebDAVApp._apply_network_options(FakeClient(), "127.0.0.1:7890", "")

    def test_custom_ca_applied(self):
        client = FakeClient()
        ca_path = os.path.abspath(__file__)
        WebDAVApp._apply_network_options(client, "", ca_path)
        self.assertEqual(client.verify, ca_path)
        self.assertEqual(client.session.verify, ca_path)

    def test_missing_ca_rejected(self):
        with self.assertRaises(ValueError):
            WebDAVApp._apply_network_options(FakeClient(), "", os.path.join(os.getcwd(), "no-such-ca.pem"))


class FakeRoot:
    def after(self, _delay, callback, *args):
        callback(*args)


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=0):
        yield self.payload

    def close(self):
        return None


class FakeDownloadClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def info(self, path):
        return {"size": "10", "etag": '"abc123"', "modified": "Wed, 21 Oct 2015 07:28:00 GMT"}

    def execute_request(self, action, path, headers_ext=None):
        self.requests.append(headers_ext)
        return self.response


class DownloadResumeTests(unittest.TestCase):
    def _app(self, client, done):
        app = object.__new__(WebDAVApp)
        app.root = FakeRoot()
        app.client = client
        app.cancel_flag = False
        app._update_progress = lambda *args, **kwargs: None
        app._download_done = lambda *args, **kwargs: done.append(args)
        app.set_status = lambda *args, **kwargs: None
        return app

    def test_resume_uses_range_and_appends(self):
        local_path = os.path.join(os.getcwd(), "_test_resume_" + os.urandom(4).hex() + ".bin")
        part_path = local_path + ".part"
        done = []
        try:
            with open(part_path, "wb") as handle:
                handle.write(b"12345")

            client = FakeDownloadClient(
                FakeResponse(206, b"67890", {"Content-Range": "bytes 5-9/10", "Content-Length": "5"})
            )
            app = self._app(client, done)
            app._do_download_stream("/file.bin", local_path, "file.bin", 10)

            with open(local_path, "rb") as handle:
                self.assertEqual(handle.read(), b"1234567890")
            self.assertFalse(os.path.exists(part_path))
            headers = client.requests[0]
            self.assertTrue(any(h.startswith("Range: bytes=5-") for h in headers))
            self.assertTrue(any(h.startswith("If-Range:") for h in headers))
            self.assertEqual(done[-1][0], True)
        finally:
            for path in (local_path, part_path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def test_server_ignores_range_restarts_from_zero(self):
        local_path = os.path.join(os.getcwd(), "_test_restart_" + os.urandom(4).hex() + ".bin")
        part_path = local_path + ".part"
        done = []
        try:
            with open(part_path, "wb") as handle:
                handle.write(b"OLDDATA")

            client = FakeDownloadClient(FakeResponse(200, b"newcontent", {"Content-Length": "10"}))
            app = self._app(client, done)
            app._do_download_stream("/file.bin", local_path, "file.bin", 10)

            with open(local_path, "rb") as handle:
                self.assertEqual(handle.read(), b"newcontent")
            self.assertFalse(os.path.exists(part_path))
            self.assertEqual(done[-1][0], True)
        finally:
            for path in (local_path, part_path):
                try:
                    os.remove(path)
                except OSError:
                    pass


class FakeUploadClient:
    def __init__(self, app):
        self.app = app

    def upload_sync(self, remote_path, local_path, progress=None, **kwargs):
        progress(0, 10)
        self.app.cancel_flag = True
        progress(5, 10)


class UploadCancelTests(unittest.TestCase):
    def test_cancel_from_progress_callback(self):
        local_path = os.path.join(os.getcwd(), "_test_upload_" + os.urandom(4).hex() + ".bin")
        with open(local_path, "wb") as handle:
            handle.write(b"0123456789")

        done = []
        app = object.__new__(WebDAVApp)
        app.root = FakeRoot()
        app.cancel_flag = False
        app._update_progress = lambda *args, **kwargs: None
        app._upload_done = lambda *args, **kwargs: done.append(args)
        app.client = FakeUploadClient(app)
        try:
            app._do_upload_task("/file.bin", local_path, "file.bin")
        finally:
            try:
                os.remove(local_path)
            except OSError:
                pass

        self.assertEqual(done[-1], (False, "上传已取消", True))


if __name__ == "__main__":
    unittest.main()