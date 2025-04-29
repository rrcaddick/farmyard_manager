from farmyard_manager.utils.core_utils import coalesce


class TestCoalesce:
    def test_multiple_non_none_values(self):
        assert coalesce(None, 0, 10) == 0
        assert coalesce(None, "hello", "world") == "hello"
        assert coalesce(5, None, 10) == 5  # noqa: PLR2004

    def test_all_none_values(self):
        assert coalesce(None, None, None) is None

    def test_first_value_is_non_none(self):
        assert coalesce(1, None, 0) == 1
        assert coalesce("a", None, "b") == "a"

    def test_empty_cases(self):
        assert coalesce(None, "", "test") == ""
        assert coalesce(None, [], [1, 2]) == []
        assert coalesce(None, {}, {"key": "value"}) == {}

    def test_single_argument(self):
        assert coalesce(1) == 1
        assert coalesce(None) is None
        assert coalesce("string") == "string"

    def test_empty_input(self):
        assert coalesce() is None
