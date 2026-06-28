"""
单元测试 · AU 数据层
=====================
直接测 CRUD 函数，不依赖 HTTP 路由。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from au_data import (
    get_all, get_active, add_au, activate, delete_au,
    _load_all, _save_all, _ensure_default, DEFAULT_AU,
)


class TestAuData:
    def test_ensure_default_adds_missing(self):
        """空列表 → 自动插入 default"""
        data = [{"id": "au_1", "name": "测试", "active": True}]
        result = _ensure_default(data)
        assert len(result) == 2
        assert result[0]["id"] == "default"

    def test_ensure_default_keeps_existing(self):
        """已有 default → 不变"""
        data = [{"id": "default", "name": "现代日常", "active": True}]
        result = _ensure_default(data)
        assert len(result) == 1

    def test_get_active_returns_none_when_no_active(self):
        """没有 active 的非 default AU → None"""
        data = [
            {"id": "default", "name": "现代日常", "active": True},
            {"id": "au_1", "name": "测试", "active": False},
        ]
        with patch("au_data._load_all", return_value=data):
            assert get_active() is None

    def test_get_active_returns_au(self):
        """有 active 的非 default AU → 返回它"""
        data = [
            {"id": "default", "name": "现代日常", "active": False},
            {"id": "au_1", "name": "古风江湖", "active": True},
        ]
        with patch("au_data._load_all", return_value=data):
            result = get_active()
            assert result is not None
            assert result["name"] == "古风江湖"

    @patch("au_data._save_all")
    def test_activate_sets_active(self, mock_save):
        data = [
            {"id": "default", "name": "现代日常", "active": False},
            {"id": "au_1", "name": "江湖", "active": False},
        ]
        with patch("au_data._load_all", return_value=data):
            result = activate("au_1")
            assert result["active"] is True
            # 验证保存时 default 关掉
            saved = mock_save.call_args[0][0]
            def_au = [a for a in saved if a["id"] == "default"][0]
            assert def_au["active"] is False

    @patch("au_data._save_all")
    def test_activate_turns_off_others(self, mock_save):
        data = [
            {"id": "default", "name": "现代日常", "active": False},
            {"id": "au_1", "name": "江湖", "active": True},  # 另一个已激活
            {"id": "au_2", "name": "校园", "active": False},
        ]
        with patch("au_data._load_all", return_value=data):
            activate("au_2")
            saved = mock_save.call_args[0][0]
            au1 = [a for a in saved if a["id"] == "au_1"][0]
            assert au1["active"] is False

    def test_activate_missing_raises(self):
        with patch("au_data._load_all", return_value=[dict(DEFAULT_AU)]):
            with pytest.raises(ValueError):
                activate("nonexistent")

    @patch("au_data._save_all")
    def test_add_au(self, mock_save):
        with patch("au_data._load_all", return_value=[dict(DEFAULT_AU)]):
            result = add_au("古风江湖", "古代世界", "你叫砚迟", "语气淡")
            assert result["name"] == "古风江湖"
            assert result["active"] is False
            assert result["background"] == "古代世界"

    @patch("au_data._save_all")
    def test_delete_non_default(self, mock_save):
        data = [
            {"id": "default", "name": "现代日常", "active": True},
            {"id": "au_1", "name": "测试", "active": False},
        ]
        with patch("au_data._load_all", return_value=data):
            ok = delete_au("au_1")
            assert ok is True
            saved = mock_save.call_args[0][0]
            assert len(saved) == 1
            assert saved[0]["id"] == "default"

    def test_delete_default_fails(self):
        with patch("au_data._load_all", return_value=[dict(DEFAULT_AU)]):
            ok = delete_au("default")
            assert ok is False
