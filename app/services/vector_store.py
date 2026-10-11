"""M6：向量入库与（M7 用的）向量检索。

这个模块回答面试高频题："向量库和关系库谁存什么？"
答案：**关系库是正文的唯一真相源，向量库只存向量 + 定位信息**（chunk_id/user_id/document_id/ordinal）。
     检索回来的是 chunk_id，正文回表取（见 app/services/retrieval.py）。

本地开发用 Qdrant 嵌入式模式（path=./qdrant_data），不需要起容器。
在什么条件下会输：
- 嵌入式模式对目录**独占文件锁** → 多个 uvicorn worker 会互相冲突 → 生产必须用 qdrant_url 走服务端。
- 单机嵌入式没有副本/多租户隔离 → 部署上线（M11）必须换 Docker 里的 qdrant 服务。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings as default_settings


@dataclass(frozen=True)
class VectorRecord:
    """一条待入向量库的记录。id 用 chunks 表主键，天然全局唯一。"""

    chunk_id: int
    vector: list[float]
    user_id: int
    document_id: int
    ordinal: int


@dataclass(frozen=True)
class VectorHit:
    chunk_id: int
    document_id: int
    ordinal: int
    score: float


class VectorStoreError(Exception):
    pass


class QdrantVectorStore:
    def __init__(
        self,
        collection: str,
        dim: int,
        path: str | None = None,
        url: str | None = None,
    ) -> None:
        if dim <= 0:
            raise VectorStoreError("建 collection 需要明确的向量维度，当前为 0")
        self.collection = collection
        self.dim = dim
        self._lock = threading.Lock()
        if url:
            self.client = QdrantClient(url=url)
        else:
            self.client = QdrantClient(path=path or "./qdrant_data")
        self.ensure_collection()

    def ensure_collection(self) -> None:
        """幂等建 collection；维度不一致时明确报错，不静默重建（静默重建会丢数据）。"""
        if self.client.collection_exists(self.collection):
            info = self.client.get_collection(self.collection)
            params = info.config.params.vectors
            size = getattr(params, "size", None)
            if size is not None and size != self.dim:
                raise VectorStoreError(
                    f"collection '{self.collection}' 已存在且维度为 {size}，"
                    f"与当前 embedding 维度 {self.dim} 不一致。"
                    "换模型后必须重建 collection（删掉 qdrant_data 或换 collection 名），"
                    "否则旧向量会污染检索结果。"
                )
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
        )

    def upsert_chunks(self, records: Sequence[VectorRecord]) -> int:
        if not records:
            return 0
        points = [
            PointStruct(
                id=record.chunk_id,
                vector=record.vector,
                payload={
                    "chunk_id": record.chunk_id,
                    "user_id": record.user_id,
                    "document_id": record.document_id,
                    "ordinal": record.ordinal,
                },
            )
            for record in records
        ]
        with self._lock:
            self.client.upsert(collection_name=self.collection, points=points, wait=True)
        return len(points)

    def search(
        self,
        user_id: int,
        vector: list[float],
        top_k: int = 5,
        document_ids: Sequence[int] | None = None,
        min_score: float = 0.0,
    ) -> list[VectorHit]:
        """检索必须带 user_id 过滤：多租户下"忘了过滤"就是越权读别人的文档。"""
        must = [FieldCondition(key="user_id", match=MatchValue(value=user_id))]
        if document_ids:
            must.append(
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_ids[0])
                    if len(document_ids) == 1
                    else MatchValue(value=list(document_ids)),
                )
            )
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=top_k,
            query_filter=Filter(must=must),
            with_payload=True,
        )
        hits: list[VectorHit] = []
        for point in response.points:
            if point.score is not None and point.score < min_score:
                continue
            payload = point.payload or {}
            hits.append(
                VectorHit(
                    chunk_id=int(payload.get("chunk_id", point.id)),
                    document_id=int(payload.get("document_id", -1)),
                    ordinal=int(payload.get("ordinal", -1)),
                    score=float(point.score or 0.0),
                )
            )
        return hits

    def delete_document(self, document_id: int) -> None:
        """重新处理同一份文档前先删旧向量，保证幂等（不然会检索到上一版内容）。"""
        with self._lock:
            self.client.delete(
                collection_name=self.collection,
                points_selector=Filter(
                    must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
                ),
                wait=True,
            )

    def count(self) -> int:
        return self.client.count(collection_name=self.collection, exact=True).count

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:  # pragma: no cover
            pass


_store_cache: dict[tuple, QdrantVectorStore] = {}


def get_vector_store(dim: int | None = None, cfg=default_settings) -> QdrantVectorStore:
    """按 (位置, collection, 维度) 复用同一个 client —— 嵌入式模式重复 open 同一目录会报锁冲突。"""
    if dim is None:
        from app.services.embedding import build_embedder

        dim = build_embedder(cfg).dim
    key = (cfg.qdrant_url or cfg.qdrant_path, cfg.qdrant_collection, dim)
    store = _store_cache.get(key)
    if store is None:
        store = QdrantVectorStore(
            collection=cfg.qdrant_collection,
            dim=dim,
            path=cfg.qdrant_path,
            url=cfg.qdrant_url or None,
        )
        _store_cache[key] = store
    return store


def reset_vector_store_cache() -> None:
    """测试用：关闭并清空缓存的 client，避免用例之间互相污染。"""
    for store in _store_cache.values():
        store.close()
    _store_cache.clear()

