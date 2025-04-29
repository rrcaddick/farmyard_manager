import pytest

from farmyard_manager.utils.string_utils import to_snake_case


class TestToSnakeCase:
    @pytest.mark.parametrize(
        ("input_str", "prefix", "suffix", "pluralize", "expected_output"),
        [
            # Basic cases for camelCase to snake_case conversion
            ("camelCase", "", "", False, "camel_case"),
            ("CamelCase", "", "", False, "camel_case"),
            ("simple", "", "", False, "simple"),
            ("MultiWordExample", "", "", False, "multi_word_example"),
            ("SomeLongVariableName", "", "", False, "some_long_variable_name"),
            # Prefix cases
            ("CamelCase", "prefix", "", False, "prefix_camel_case"),
            ("camelCase", "prefix", "", False, "prefix_camel_case"),
            ("multiWord", "prefix", "", False, "prefix_multi_word"),
            (
                "SomeLongVariableName",
                "prefix",
                "",
                False,
                "prefix_some_long_variable_name",
            ),
            # Suffix cases
            ("CamelCase", "", "suffix", False, "camel_case_suffix"),
            ("camelCase", "", "suffix", False, "camel_case_suffix"),
            ("multiWord", "", "suffix", False, "multi_word_suffix"),
            (
                "SomeLongVariableName",
                "",
                "suffix",
                False,
                "some_long_variable_name_suffix",
            ),
            # Prefix and suffix cases
            ("CamelCase", "prefix", "suffix", False, "prefix_camel_case_suffix"),
            ("camelCase", "prefix", "suffix", False, "prefix_camel_case_suffix"),
            ("multiWord", "prefix", "suffix", False, "prefix_multi_word_suffix"),
            (
                "SomeLongVariableName",
                "prefix",
                "suffix",
                False,
                "prefix_some_long_variable_name_suffix",
            ),
            # Pluralization cases
            ("entry", "", "", True, "entries"),
            ("CamelCase", "", "", True, "camel_cases"),
            ("box", "", "", True, "boxes"),
            ("carDrive", "", "", True, "car_drives"),
            ("handMade", "", "", True, "hand_mades"),
            # Pluralization with prefix and suffix
            ("entry", "prefix", "suffix", True, "prefix_entry_suffixes"),
            ("CamelCase", "prefix", "suffix", True, "prefix_camel_case_suffixes"),
            ("carDrive", "prefix", "suffix", True, "prefix_car_drive_suffixes"),
            # Edge cases: empty string, already snake_case, special
            # characters, numbers, spaces
            ("", "", "", False, ""),
            ("already_snake_case", "", "", False, "already_snake_case"),
            ("Special!Case", "", "", False, "special_case"),
            ("Some Value", "prefix", "", False, "prefix_some_value"),
            ("test123Variable", "", "", False, "test123_variable"),
            ("Variable_123Test", "", "", False, "variable_123_test"),
            ("camelCase", None, None, None, "camel_case"),
        ],
        ids=[
            # IDs to identify tests
            "basic_snake_case_1",
            "basic_snake_case_2",
            "basic_snake_case_3",
            "multi_word_case",
            "long_variable_case",
            "prefix_case_1",
            "prefix_case_2",
            "prefix_case_3",
            "prefix_case_4",
            "suffix_case_1",
            "suffix_case_2",
            "suffix_case_3",
            "suffix_case_4",
            "prefix_suffix_case_1",
            "prefix_suffix_case_2",
            "prefix_suffix_case_3",
            "prefix_suffix_case_4",
            "pluralize_case_1",
            "pluralize_case_2",
            "pluralize_case_3",
            "pluralize_case_4",
            "pluralize_case_5",
            "pluralize_prefix_suffix_case_1",
            "pluralize_prefix_suffix_case_2",
            "pluralize_prefix_suffix_case_3",
            "empty_string",
            "already_snake_case",
            "special_chars_case",
            "space_case",
            "numbers_in_case",
            "mixed_case",
            "none_case",
        ],
    )
    def test_to_snake_case(self, input_str, prefix, suffix, pluralize, expected_output):
        snake_case = to_snake_case(
            input_str,
            prefix=prefix,
            suffix=suffix,
            pluralize=pluralize,
        )
        assert snake_case == expected_output
