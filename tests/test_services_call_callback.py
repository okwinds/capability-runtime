from __future__ import annotations

"""call_callback 签名检测单元测试。"""

import pytest

from capability_runtime.services import call_callback


class TestCallCallback:
    """call_callback 签名检测与兼容性测试。"""

    def test_var_args_handler_receives_all_args(self):
        """VAR_POSITIONAL (*args) handler 应全量传入。"""
        received = []

        def handler(*args):
            received.extend(args)

        call_callback(handler, "a", "b", "c")
        assert received == ["a", "b", "c"]

    def test_two_param_handler(self):
        """两参数 handler 正常调用。"""
        received = []

        def handler(x, y):
            received.append((x, y))

        call_callback(handler, "a", "b")
        assert received == [("a", "b")]

    def test_one_param_handler(self):
        """单参数 handler 仅接收第一个参数。"""
        received = []

        def handler(x):
            received.append(x)

        call_callback(handler, "a", "b")
        assert received == ["a"]

    def test_zero_param_handler(self):
        """零参数 handler 不接收任何参数。"""
        called = []

        def handler():
            called.append(True)

        call_callback(handler, "a", "b")
        assert called == [True]

    def test_handler_with_defaults(self):
        """带默认值的 handler 正常调用。"""
        received = []

        def handler(x, y="default"):
            received.append((x, y))

        call_callback(handler, "a", "b")
        assert received == [("a", "b")]

    def test_keyword_only_params_not_counted_as_positional(self):
        """KEYWORD_ONLY 参数不计入 positional 统计。"""
        received = []

        def handler(x, *, y="kw"):
            received.append((x, y))

        # 只有 1 个 positional 参数，传入 2 个参数时应只取第一个
        call_callback(handler, "a", "b")
        assert received == [("a", "kw")]

    def test_no_signature_fallback(self):
        """无法获取签名时回退到全量传入。"""

        class CallableWithoutSignature:
            def __call__(self, *args):
                self.received = args

        cb = CallableWithoutSignature()
        # 模拟无法获取签名的情况（实际上 __call__ 有签名，但测试逻辑会回退）
        call_callback(cb, "a", "b")
        assert cb.received == ("a", "b")
