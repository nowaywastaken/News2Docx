from news2docx.services.processing import articles_from_json


def test_articles_from_json_basic():
    data = {
        "articles": [
            {
                "id": 1,
                "url": "http://example.com/a",
                "title": "T",
                "content": "Hello world",
                "content_length": 11,
                "word_count": 2,
            }
        ]
    }
    arts = articles_from_json(data)
    assert len(arts) == 1
    a = arts[0]
    assert a.index == 1
    assert a.url.endswith("/a")
    assert a.title == "T"
    assert a.content.startswith("Hello")
