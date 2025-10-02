from news2docx.core.utils import force_https


def test_force_https_basic():
    assert force_https("http://example.com").startswith("https://")
    assert force_https("http://example.com/a?b=1") == "https://example.com/a?b=1"
    assert force_https("https://already.secure/path").startswith("https://")
    assert force_https("") == ""
