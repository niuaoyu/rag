"""M6 向量库单测：多租户过滤、幂等删除、维度不一致。

这些是"接口层测不到"的东西：接口测的是端到端行为，向量库的过滤条件写错时
端到端可能依然"看起来对"（因为只有一份文档、一个用户）。
"""

import pytest

from app.services.vector_store import (
    QdrantVectorStore,
    VectorRecord,
    VectorStoreError,
)


@pytest.fixture()
def store(tmp_path):
    return QdrantVectorStore(
        collection="unit_test", dim=4, path=str(tmp_path / "qdrant_unit")
    )


def _record(chunk_id, user_id, document_id, vector):
    return VectorRecord(
        chunk_id=chunk_id,
        vector=vector,
        user_id=user_id,
        document_id=document_id,
        ordinal=chunk_id,
    )


def test_user_filter_blocks_cross_tenant_read(store):
    store.upsert_chunks(
        [
            _record(1, user_id=1, document_id=10, vector=[1.0, 0.0, 0.0, 0.0]),
            _record(2, user_id=2, document_id=20, vector=[1.0, 0.0, 0.0, 0.0]),
        ]
    )
    hits = store.search(user_id=1, vector=[1.0, 0.0, 0.0, 0.0], top_k=10)
    assert [hit.chunk_id for hit in hits] == [1]


def test_document_filter(store):
    store.upsert_chunks(
        [
            _record(1, 1, 10, [1.0, 0.0, 0.0, 0.0]),
            _record(2, 1, 11, [1.0, 0.0, 0.0, 0.0]),
        ]
    )
    hits = store.search(user_id=1, vector=[1.0, 0.0, 0.0, 0.0], top_k=10, document_ids=[11])
    assert [hit.chunk_id for hit in hits] == [2]


def test_min_score_filters(store):
    store.upsert_chunks([_record(1, 1, 10, [1.0, 0.0, 0.0, 0.0])])
    assert store.search(user_id=1, vector=[1.0, 0.0, 0.0, 0.0], top_k=5, min_score=0.99)
    assert not store.search(
        user_id=1, vector=[0.0, 0.0, 0.0, 1.0], top_k=5, min_score=0.5
    )


def test_delete_document_removes_points(store):
    store.upsert_chunks([_record(1, 1, 10, [1.0, 0.0, 0.0, 0.0])])
    assert store.count() == 1
    store.delete_document(10)
    assert store.count() == 0


def test_upsert_empty_is_noop(store):
    assert store.upsert_chunks([]) == 0


def test_dimension_mismatch_raises(tmp_path):
    path = str(tmp_path / "qdrant_dim")
    QdrantVectorStore(collection="dim_check", dim=4, path=path)
    with pytest.raises(VectorStoreError, match="维度"):
        QdrantVectorStore(collection="dim_check", dim=8, path=path)


def test_zero_dim_raises(tmp_path):
    with pytest.raises(VectorStoreError):
        QdrantVectorStore(collection="bad", dim=0, path=str(tmp_path / "bad"))
