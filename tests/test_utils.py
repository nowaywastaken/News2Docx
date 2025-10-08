from news2docx.core.utils import now_stamp, safe_filename


def test_safe_filename_basic():
    assert safe_filename("a:b*c?.txt").endswith(".txt")
    assert "?" not in safe_filename("q?.md")


def test_now_stamp_format():
    ts = now_stamp()
    assert len(ts) == 15 and ts[8] == "_"
