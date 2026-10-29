"""The two local models behind the meaning-based linking stages (D-42).

Both turn text into numbers and nothing else; they know nothing about skills or thresholds.
- EmbeddingModel: a phrase -> a vector. Phrases with similar meaning get similar vectors.
- NliModel: a pair of sentences -> how likely the first implies, contradicts, or is neutral to the second.
"""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy
import onnxruntime
from tokenizers import Tokenizer

from recruiter_bot.linking.model_files import MODEL_FILES, MODELS_DIR

EMBEDDING_MAX_TOKENS = 64   # skills and traits are a few words; this leaves a wide margin
NLI_MAX_TOKENS = 128        # two short sentences


def _session(model_path: Path) -> onnxruntime.InferenceSession:
    options = onnxruntime.SessionOptions()
    options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
    return onnxruntime.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])


def _tokenizer(tokenizer_path: Path, max_tokens: int) -> Tokenizer:
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    padding_id = tokenizer.token_to_id("[PAD]")
    if padding_id is None:
        raise ValueError(f"{tokenizer_path}: no [PAD] token")
    tokenizer.enable_padding(pad_id=padding_id, pad_token="[PAD]")
    tokenizer.enable_truncation(max_length=max_tokens)
    return tokenizer


class EmbeddingModel:
    """BGE-small: each phrase becomes a 384-number vector of length 1, so cosine similarity is a dot product."""

    def __init__(self, models_dir: Path) -> None:
        self._session = _session(models_dir / "embedding" / "model.onnx")
        self._tokenizer = _tokenizer(models_dir / "embedding" / "tokenizer.json", EMBEDDING_MAX_TOKENS)

    def embed(self, phrases: list[str]) -> numpy.ndarray:
        """One row per phrase."""
        rows = [self._embed_one(phrase) for phrase in phrases]
        if not rows:
            return numpy.zeros((0, 384), dtype=numpy.float32)
        return numpy.stack(rows)

    def _embed_one(self, phrase: str) -> numpy.ndarray:
        # One phrase per run, never a padded batch: the int8 model scales its numbers over the whole
        # batch, so batching would make a phrase's vector depend on the phrases next to it.
        encoding = self._tokenizer.encode(phrase)
        input_ids = numpy.array([encoding.ids], dtype=numpy.int64)
        attention_mask = numpy.array([encoding.attention_mask], dtype=numpy.int64)
        token_type_ids = numpy.zeros_like(input_ids)

        hidden_states = self._session.run(None, {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        })[0]
        # BGE's documented pooling: the vector of the first ([CLS]) token, scaled to length 1.
        first_token_vector = hidden_states[0, 0, :]
        return first_token_vector / numpy.linalg.norm(first_token_vector)


@dataclass(frozen=True)
class NliResult:
    entailment: float
    contradiction: float
    neutral: float


class NliModel:
    """DeBERTa-v3 NLI: does the premise imply the hypothesis, contradict it, or neither?"""

    def __init__(self, models_dir: Path) -> None:
        self._session = _session(models_dir / "nli" / "model.onnx")
        self._tokenizer = _tokenizer(models_dir / "nli" / "tokenizer.json", NLI_MAX_TOKENS)
        # The position of each label in the output comes from the model's own config, never from a guess.
        id_to_label = json.loads((models_dir / "nli" / "config.json").read_text(encoding="utf-8"))["id2label"]
        self._position_of = {label: int(position) for position, label in id_to_label.items()}
        expected = {"entailment", "contradiction", "neutral"}
        if set(self._position_of) != expected:
            raise ValueError(f"NLI config labels {sorted(self._position_of)} are not {sorted(expected)}")

    def judge(self, pairs: list[tuple[str, str]]) -> list[NliResult]:
        """One result per (premise, hypothesis) pair; the three probabilities add up to 1."""
        return [self._judge_one(premise, hypothesis) for premise, hypothesis in pairs]

    def _judge_one(self, premise: str, hypothesis: str) -> NliResult:
        # One pair per run, for the same reason as EmbeddingModel._embed_one.
        encoding = self._tokenizer.encode(premise, hypothesis)
        input_ids = numpy.array([encoding.ids], dtype=numpy.int64)
        attention_mask = numpy.array([encoding.attention_mask], dtype=numpy.int64)

        logits = self._session.run(None, {"input_ids": input_ids, "attention_mask": attention_mask})[0][0]
        # Softmax, shifted by the maximum so large values can't overflow.
        shifted = logits - logits.max()
        probabilities = numpy.exp(shifted) / numpy.exp(shifted).sum()
        return NliResult(
            entailment=float(probabilities[self._position_of["entailment"]]),
            contradiction=float(probabilities[self._position_of["contradiction"]]),
            neutral=float(probabilities[self._position_of["neutral"]]),
        )


@dataclass(frozen=True)
class LinkingModels:
    embedding: EmbeddingModel
    nli: NliModel


def models_are_present(models_dir: Path = MODELS_DIR) -> bool:
    """A quick size check of every file; the full hash check runs when the files are downloaded."""
    for model_file in MODEL_FILES:
        path = models_dir / model_file.local_name
        if not path.exists() or path.stat().st_size != model_file.size:
            return False
    return True


def load_models(models_dir: Path = MODELS_DIR) -> LinkingModels | None:
    """Both models, or None when the files are missing. Linking then falls back to the rules alone (D-41)."""
    if not models_are_present(models_dir):
        return None
    return LinkingModels(embedding=EmbeddingModel(models_dir), nli=NliModel(models_dir))
