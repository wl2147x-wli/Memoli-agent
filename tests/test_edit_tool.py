# 编码：utf-8
"""
Regression tests for the Edit tool's fuzzy matching.

When the provided oldText does not match byte-for-byte (usually because the
whitespace differs), the Edit tool falls back to a whitespace-tolerant fuzzy
match. The fuzzy match must replace only the matched region in the original
file. It previously rewrote the entire file from a whitespace-normalized copy,
which collapsed the indentation of every untouched line and corrupted the file
(e.g. broke Python indentation).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.edit.edit import Edit


class TestEditFuzzyPreservesWhitespace(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.path = os.path.join(self.work, "sample.py")
        self.original = (
            "def foo():\n"
            "    x = 1\n"
            "    y = 2\n"
            "    return x + y\n"
        )
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(self.original)
        self.tool = Edit({"cwd": self.work})

    def _read(self):
        with open(self.path, "r", encoding="utf-8") as f:
            return f.read()

    def test_fuzzy_match_does_not_reformat_untouched_lines(self):
        # oldText 与文件的区别仅在于“=”周围有额外的空格，因此
        # 精确匹配失败，采用模糊路径。仅“x = 1”行
        # 应该改变；其他行必须保持 4 个空格的缩进。
        result = self.tool.execute({
            "path": self.path,
            "oldText": "    x  =  1",
            "newText": "    x = 100",
        })
        self.assertEqual(result.status, "success", result.result)

        expected = (
            "def foo():\n"
            "    x = 100\n"
            "    y = 2\n"
            "    return x + y\n"
        )
        self.assertEqual(self._read(), expected)

    def test_exact_match_still_replaces_in_place(self):
        result = self.tool.execute({
            "path": self.path,
            "oldText": "    y = 2",
            "newText": "    y = 20",
        })
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(
            self._read(),
            "def foo():\n    x = 1\n    y = 20\n    return x + y\n",
        )

    def test_multiline_fuzzy_match_preserves_surrounding_indentation(self):
        result = self.tool.execute({
            "path": self.path,
            "oldText": "    x = 1\n    y  =  2",  # 第二行有多余的空格
            "newText": "    x = 9\n    y = 8",
        })
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(
            self._read(),
            "def foo():\n    x = 9\n    y = 8\n    return x + y\n",
        )

    def test_fuzzy_match_with_unindented_oldtext_preserves_file_indent(self):
        # oldText 没有前导缩进（并且“=”周围的间距较松），因此
        # 精确匹配失败并且模糊路径针对缩进文件运行
        # 线。必须保留文件的缩进——保留在文件之外
        # 替换的区域——而不是被吞没到比赛中并且
        # 删除（这会破坏文件的缩进）。新文本是
        # 同样不缩进，镜像精确子字符串替换。
        result = self.tool.execute({
            "path": self.path,
            "oldText": "x  =  1",
            "newText": "x = 100",
        })
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(
            self._read(),
            "def foo():\n    x = 100\n    y = 2\n    return x + y\n",
        )

    def test_exact_match_rejects_multiple_occurrences(self):
        # 两个字节相同的语句；应用完全匹配路径并且
        # 唯一性守卫计算确切的出现次数，因此不明确的编辑是
        # 拒绝而不是默默地只编辑第一个。
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("a = 1\nb = 2\na = 1\n")
        result = self.tool.execute({
            "path": self.path,
            "oldText": "a = 1",
            "newText": "a = 9",
        })
        self.assertEqual(result.status, "error", result.result)
        self.assertIn("occurrences", result.result)
        # 不明确的匹配必须保持文件不变。
        self.assertEqual(self._read(), "a = 1\nb = 2\na = 1\n")

    def test_fuzzy_match_rejects_multiple_occurrences(self):
        # oldText 使用宽松的间距，因此精确匹配失败并且模糊
        # 路径运行。唯一性保护现在与使用的相同正则表达式一起计数
        # 匹配/替换，因此不明确的模糊匹配（两次命中）被拒绝
        # 而不是默默地编辑第一个。
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("def foo():\n    x = 1\n    y = 2\n    x = 1\n")
        result = self.tool.execute({
            "path": self.path,
            "oldText": "x  =  1",
            "newText": "x = 99",
        })
        self.assertEqual(result.status, "error", result.result)
        self.assertIn("occurrences", result.result)
        self.assertEqual(
            self._read(),
            "def foo():\n    x = 1\n    y = 2\n    x = 1\n",
        )


if __name__ == "__main__":
    unittest.main()
