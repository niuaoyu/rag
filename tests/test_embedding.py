from app.services.embedding import cosine, embed_query


def test_embedding_similarity():
    a = embed_query("volatile 不保证 i++ 原子性")
    b = embed_query("volatile 不能保证 i++ 的原子性")
    c = embed_query("今天北京天气适合跑步吗")
    assert cosine(a, b) > cosine(a, c)


def test_embedding_dimension():
    assert len(embed_query("hello world")) == 256
