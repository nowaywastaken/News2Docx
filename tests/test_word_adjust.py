from processor.word_adjust import count_english_words, calculate_word_adjustment_percentage


def test_count_english_words() -> None:
    text = "<p>Hello world!</p> This is a test."
    assert count_english_words(text) == 6


def test_calculate_word_adjustment_percentage() -> None:
    # 200 words should require roughly 125% increase to reach center 425
    assert calculate_word_adjustment_percentage(200) > 0
    # 500 words should require a negative adjustment
    assert calculate_word_adjustment_percentage(500) < 0
