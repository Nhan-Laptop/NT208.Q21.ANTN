from __future__ import annotations

import unittest

from app.services.embeddings.specter2_service import Specter2Service


class FakeSentenceTransformer:
    def encode(self, texts, show_progress_bar=False):  # noqa: ANN001
        class EncodedVectors(list):
            def tolist(self):  # noqa: ANN001
                return list(self)

        return EncodedVectors([[1.0, 2.0, 2.0] for _ in texts])


class FakeAdapterModel:
    def __init__(self) -> None:
        self.active_adapters = "None"
        self.activation_calls: list[str] = []

    def set_active_adapters(self, adapter_label: str) -> None:
        self.activation_calls.append(adapter_label)
        self.active_adapters = f"Stack[{adapter_label}]"


class BrokenAdapterModel:
    active_adapters = "None"

    def set_active_adapters(self, adapter_label: str) -> None:
        self.active_adapters = "None"


class Specter2ServiceTest(unittest.TestCase):
    def test_hash_fallback_is_explicit(self) -> None:
        service = Specter2Service()
        service._backend = "hash-fallback"
        service._loaded_model_name = "hash-fallback"
        service._model = "hash-fallback"
        vector = service.embed_text("scientific retrieval")
        self.assertEqual(len(vector), 384)
        self.assertTrue(service.is_degraded)
        self.assertEqual(service.status()["model_name"], "hash-fallback")

    def test_loaded_model_path_normalizes_vectors(self) -> None:
        service = Specter2Service()
        service._backend = "sentence-transformers"
        service._loaded_model_name = "fake-specter2"
        service._model = FakeSentenceTransformer()
        vector = service.embed_text("scientific retrieval")
        self.assertAlmostEqual(sum(value * value for value in vector), 1.0, places=5)
        self.assertEqual(service.embedding_model_name, "fake-specter2")
        self.assertFalse(service.is_degraded)

    def test_adapter_backend_explicitly_activates_adapter(self) -> None:
        service = Specter2Service()
        service._model = FakeAdapterModel()
        service._adapter_label = "specter2"

        service._ensure_adapter_active()

        self.assertEqual(service._model.active_adapters, "Stack[specter2]")
        self.assertEqual(service._model.activation_calls, ["specter2"])

    def test_adapter_backend_rejects_missing_activation(self) -> None:
        service = Specter2Service()
        service._model = BrokenAdapterModel()
        service._adapter_label = "specter2"

        with self.assertRaisesRegex(RuntimeError, "is not active"):
            service._ensure_adapter_active()


if __name__ == "__main__":
    unittest.main()
