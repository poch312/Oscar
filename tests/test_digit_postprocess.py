from oscar.ocr.digit_postprocess import clean_digit_string, digits_match_words, words_to_number


def test_clean_digit_string_fixes_common_confusions():
    assert clean_digit_string("8O") == "80"
    assert clean_digit_string("l23") == "123"
    assert clean_digit_string("4S") == "45"
    assert clean_digit_string(" 45 ") == "45"


def test_words_to_number_basic():
    assert words_to_number("ochenta") == 80
    assert words_to_number("ciento veinte") == 120
    assert words_to_number("doscientos cinco") == 205
    assert words_to_number("mil quinientos") == 1500
    assert words_to_number("veintitres") == 23


def test_words_to_number_unparseable_returns_none():
    assert words_to_number("") is None
    assert words_to_number("xyz") is None


def test_digits_match_words():
    assert digits_match_words(80, "ochenta") is True
    assert digits_match_words(80, "setenta") is False
    assert digits_match_words(80, "") is None
    assert digits_match_words(None, "ochenta") is None
