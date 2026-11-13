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


if __name__ == "__main__":
    unittest.main()
