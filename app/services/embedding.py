"""M6：文本 → 向量。

两个实现，切换靠 settings.embedding_provider：
- openai：打任意 OpenAI 兼容的 /embeddings 接口（智谱、DashScope、自建 vLLM 都行），是**唯一语义可用**的实现。
- hash  ：离线确定性哈希（字符 n-gram 词袋）。**只是词面重叠**，不具备语义相似度能力，
          用途仅限于"CI/离线跑通管道 + 单测断言检索能命中词面相关的块"。
          任何检索质量数字（命中率/召回）在 hash 下都是假的，不许写进简历或文档结论。

为什么把 hash 也做成一个正式实现而不是在测试里 mock：
embedding 是管道里最容易"其实没跑"的一环（mock 掉之后，向量库维度、payload、过滤条件全都测不到）。
有确定性的真实现，M6/M7 的测试才测得到真东西。
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Protocol, Sequence

import httpx

from app.core.config import settings as default_settings
from app.core.http import resolve_verify

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_WORD = re.compile(r"[a-z0-9_]+")


class EmbeddingError(Exception):
    pass


class BaseEmbedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashEmbedder:
    """确定性、离线的词面哈希向量。dim 必须显式指定。"""

    name = "hash"

    def __init__(self, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError("dim 必须为正数")
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        """特征 = 中文单字 + 中文二元组 + 英文/数字词。中文二元组是为了让"向量检索"能覆盖词序。"""
        lowered = text.lower()
        cjk_chars = _CJK.findall(lowered)
        features = list(cjk_chars)
        features += [cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1)]
        features += _WORD.findall(lowered)
        return features

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for feature in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self.dim
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:  # 空文本/纯符号
            return vector
        return [v / norm for v in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


class OpenAICompatEmbedder:
    """OpenAI 兼容 /embeddings 客户端。dim 由接口首次返回决定。"""

    name = "openai"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dim: int | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise EmbeddingError("embedding_provider=openai 但 embedding_api_key 为空")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim or 0
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
            verify=resolve_verify(),
        )

    def _post_embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = self._client.post(
                "/embeddings", json={"model": self.model, "input": list(texts)}
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"embedding 接口调用失败: {type(exc).__name__}: {exc}") from exc

        try:
            # OpenAI 兼容接口按 index 排序返回，不能假设顺序
            items = sorted(payload["data"], key=lambda item: item["index"])
            vectors = [list(map(float, item["embedding"])) for item in items]
        except (KeyError, TypeError) as exc:
            raise EmbeddingError(f"embedding 接口返回格式不符合预期: {payload}") from exc

        if not vectors:
            raise EmbeddingError("embedding 接口返回空结果")
        self.dim = len(vectors[0])
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._post_embeddings(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._post_embeddings([text])[0]


class LocalOnnxEmbedder:
    """本地 ONNX 语义向量（无需任何 API key）。

    为什么加这一档：`hash` 只有词面信息，任何"检索质量"数字都站不住；而 API embedding 需要 key。
    本地 ONNX 模型让**语义检索的数字可以在离线环境复现**（模型文件由 scripts/fetch_embedding_model.py 拉取）。

    模型约定：目录下要有 `model_optimized.onnx` 与 `tokenizer.json`（默认 BAAI/bge-small-zh-v1.5 的 ONNX 版）。
    池化方式是 **CLS**（BGE 系列用首 token），不是 mean pooling —— 换模型必须重新确认池化方式。
    """

    name = "local"

    def __init__(self, model_dir: str | Path, max_tokens: int = 512, batch_size: int = 32) -> None:
        try:
            import onnxruntime  # noqa: F401
            from tokenizers import Tokenizer
        except ImportError as exc:  # pragma: no cover
            raise EmbeddingError(
                "embedding_provider=local 需要 onnxruntime 与 tokenizers："
                "pip install onnxruntime tokenizers"
            ) from exc

        self.model_dir = Path(model_dir)
        model_path = self.model_dir / "model_optimized.onnx"
        tokenizer_path = self.model_dir / "tokenizer.json"
        for path in (model_path, tokenizer_path):
            if not path.exists():
                raise EmbeddingError(
                    f"本地模型文件缺失：{path}。"
                    "先跑 python3 scripts/fetch_embedding_model.py"
                )

        import onnxruntime as ort

        self.max_tokens = max_tokens
        self.batch_size = batch_size
        self._session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self._input_names = {item.name for item in self._session.get_inputs()}
        self._output_name = self._session.get_outputs()[0].name

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=max_tokens)
        pad_id = self._tokenizer.token_to_id("[PAD]")
        self._tokenizer.enable_padding(pad_id=0 if pad_id is None else pad_id, pad_token="[PAD]")

        self.dim = 0  # 首次前向时确定
        # 预热一次：ONNX 输出维度是动态的，不预热 dim 就是 0，
        # 而调用方（建 Qdrant collection）在写第一份文档前就需要知道维度。
        # 这个 bug 是真实跑 e2e 时才暴露的：测试里用 hash（维度一开始就确定），根本测不到。
        self._warm_up()

    def _warm_up(self) -> None:
        self._embed(["维度探测"])

    def _pool(self, hidden, attention_mask):
        """CLS 池化 + L2 归一化（BGE 系列取首 token；换模型必须重新确认池化方式）。"""
        import numpy as np

        cls = hidden[:, 0, :]
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return cls / norms

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        import numpy as np

        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            encodings = self._tokenizer.encode_batch(batch)
            feed = {
                "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
            }
            # bge 的 ONNX 导出通常还要 token_type_ids；按模型实际输入喂，缺了会直接报错
            if "token_type_ids" in self._input_names:
                feed["token_type_ids"] = np.zeros_like(feed["input_ids"])
            hidden = self._session.run([self._output_name], feed)[0]
            pooled = self._pool(hidden, feed["attention_mask"])
            if self.dim == 0:
                self.dim = int(pooled.shape[1])
            vectors.extend(row.tolist() for row in pooled)
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


def build_embedder(cfg=default_settings) -> BaseEmbedder:
    provider = (cfg.embedding_provider or "hash").lower()
    if provider == "hash":
        return HashEmbedder(dim=cfg.embedding_dim)
    if provider == "local":
        return LocalOnnxEmbedder(
            model_dir=cfg.embedding_local_dir, max_tokens=cfg.embedding_max_tokens
        )
    if provider == "openai":
        return OpenAICompatEmbedder(
            base_url=cfg.embedding_base_url,
            api_key=cfg.embedding_api_key,
            model=cfg.embedding_model,
            dim=None,
            timeout=cfg.llm_timeout_seconds,
        )
    raise EmbeddingError(f"未知的 embedding_provider: {provider}（可选 hash / local / openai）")


_embedder_cache: dict[tuple, BaseEmbedder] = {}


def get_embedder(cfg=default_settings) -> BaseEmbedder:
    """缓存 embedder：本地 ONNX 模型加载一次要 ~1.2s，每处理一份文档重建一次是纯浪费。"""
    key = (
        (cfg.embedding_provider or "hash").lower(),
        cfg.embedding_local_dir,
        cfg.embedding_model,
        cfg.embedding_dim,
    )
    embedder = _embedder_cache.get(key)
    if embedder is None:
        embedder = build_embedder(cfg)
        _embedder_cache[key] = embedder
    return embedder


def reset_embedder_cache() -> None:
    """测试用：清掉缓存，避免用例之间共享模型实例。"""
    _embedder_cache.clear()
