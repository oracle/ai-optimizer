"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch, MagicMock

import pytest

from server.api.core import prompts
from common.schema import Prompt


class TestPrompts:
    """Test prompts module functionality"""

    def setup_method(self):
        """Setup test data before each test"""
        self.sample_prompt_1 = Prompt(category="sys", name="default", prompt="You are a helpful assistant.")
        self.sample_prompt_2 = Prompt(category="sys", name="custom", prompt="You are a custom assistant.")
        self.sample_prompt_3 = Prompt(category="ctx", name="greeting", prompt="Hello, how can I help you?")

    @patch("server.api.core.prompts.bootstrap")
    def test_get_prompts_all(self, mock_bootstrap):
        """Test getting all prompts when no filters are provided"""
        all_prompts = [self.sample_prompt_1, self.sample_prompt_2, self.sample_prompt_3]
        mock_bootstrap.PROMPT_OBJECTS = all_prompts

        result = prompts.get_prompts()

        assert result == all_prompts

    @patch("server.api.core.prompts.bootstrap.PROMPT_OBJECTS")
    def test_get_prompts_by_category(self, mock_prompt_objects):
        """Test filtering prompts by category"""
        all_prompts = [self.sample_prompt_1, self.sample_prompt_2, self.sample_prompt_3]
        mock_prompt_objects.__iter__ = MagicMock(return_value=iter(all_prompts))

        result = prompts.get_prompts(category="sys")

        expected = [self.sample_prompt_1, self.sample_prompt_2]
        assert result == expected

    @patch("server.api.core.prompts.bootstrap.PROMPT_OBJECTS")
    def test_get_prompts_by_category_and_name_found(self, mock_prompt_objects):
        """Test filtering prompts by category and name when found"""
        all_prompts = [self.sample_prompt_1, self.sample_prompt_2, self.sample_prompt_3]
        mock_prompt_objects.__iter__ = MagicMock(return_value=iter(all_prompts))

        result = prompts.get_prompts(category="sys", name="custom")

        assert result == self.sample_prompt_2

    @patch("server.api.core.prompts.bootstrap.PROMPT_OBJECTS")
    def test_get_prompts_by_category_and_name_not_found(self, mock_prompt_objects):
        """Test filtering prompts by category and name when not found"""
        all_prompts = [self.sample_prompt_1, self.sample_prompt_2, self.sample_prompt_3]
        mock_prompt_objects.__iter__ = MagicMock(return_value=iter(all_prompts))

        with pytest.raises(ValueError, match="nonexistent \\(sys\\) not found"):
            prompts.get_prompts(category="sys", name="nonexistent")

    @patch("server.api.core.prompts.bootstrap.PROMPT_OBJECTS")
    def test_get_prompts_by_name_without_category_raises_error(self, mock_prompt_objects):
        """Test that filtering by name without category raises an error"""
        with pytest.raises(ValueError, match="Cannot filter prompts by name without specifying category"):
            prompts.get_prompts(name="default")

    @patch("server.api.core.prompts.bootstrap.PROMPT_OBJECTS")
    def test_get_prompts_empty_category_filter(self, mock_prompt_objects):
        """Test filtering by category that has no matches"""
        all_prompts = [self.sample_prompt_1, self.sample_prompt_2, self.sample_prompt_3]
        mock_prompt_objects.__iter__ = MagicMock(return_value=iter(all_prompts))

        result = prompts.get_prompts(category="nonexistent")

        assert result == []

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(prompts, "logger")
        assert prompts.logger.name == "api.core.prompts"
