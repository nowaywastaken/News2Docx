import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.text import now_stamp, count_english_words, safe_filename


def test_now_stamp_format():
    stamp = now_stamp()
    assert re.fullmatch(r"\d{8}_\d{6}", stamp)


def test_count_english_words():
    text = "Hello, world!<br>This is a test."
    assert count_english_words(text) == 6
    assert count_english_words("") == 0


def test_safe_filename_basic():
    filename = "my:file*name?.txt"
    assert safe_filename(filename) == "myfilename.txt"


def test_safe_filename_length_and_default():
    long_name = "a" * 300 + ".txt"
    result = safe_filename(long_name)
    assert len(result) <= 255
    assert result.endswith(".txt")
    untitled = safe_filename("")
    assert untitled.startswith("untitled_")
