"""T4 — Embeddings (critical for pgvector migration).

Tests the cosine similarity, serialize/deserialize round-trip,
dedup, and relevance scoring. These are the canary tests
for the pgvector column definition and embedding dimension.
"""

import math
import pytest

from services.embeddings import (
    cosine,
    serialize,
    deserialize,
    is_duplicate,
    score_relevance,
    build_org_fingerprint_text,
    RELEVANCE_THRESHOLD,
    DEDUP_THRESHOLD,
)


# Fixed test vectors (512-dim would be real, using small for unit tests)
VEC_A = [1.0, 0.0, 0.0, 0.0]
VEC_B = [0.0, 1.0, 0.0, 0.0]
VEC_C = [0.707, 0.707, 0.0, 0.0]  # ~45 degrees from A
VEC_ZERO = [0.0, 0.0, 0.0, 0.0]


class TestCosine:
    def test_identical_vectors(self):
        """T4.2 — cosine(a, a) == 1.0"""
        assert cosine(VEC_A, VEC_A) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """T4.3 — cosine(a, b) == 0.0 when orthogonal."""
        assert cosine(VEC_A, VEC_B) == pytest.approx(0.0)

    def test_similar_vectors(self):
        """Cosine of partially similar vectors is between 0 and 1."""
        sim = cosine(VEC_A, VEC_C)
        assert 0.0 < sim < 1.0

    def test_empty_vector_returns_zero(self):
        """Empty vector returns 0.0."""
        assert cosine([], VEC_A) == 0.0
        assert cosine(VEC_A, []) == 0.0

    def test_zero_vector_returns_zero(self):
        """Zero magnitude vector returns 0.0."""
        assert cosine(VEC_ZERO, VEC_A) == 0.0

    def test_mismatched_lengths(self):
        """Mismatched vector lengths return 0.0."""
        assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


class TestSerializeDeserialize:
    def test_round_trip(self):
        """T4.1 — Round-trip: serialize then deserialize returns same float list."""
        vec = [0.123, -0.456, 0.789, 0.0]
        result = deserialize(serialize(vec))
        assert result == vec

    def test_round_trip_512_dim(self):
        """T4.1 — 512-dim vector round-trips correctly."""
        vec = [float(i) / 512.0 for i in range(512)]
        result = deserialize(serialize(vec))
        assert len(result) == 512
        for a, b in zip(vec, result):
            assert a == pytest.approx(b)

    def test_deserialize_empty(self):
        """Empty string deserializes to empty list."""
        assert deserialize("") == []
        assert deserialize(None) == []

    def test_deserialize_invalid(self):
        """Invalid JSON returns empty list."""
        assert deserialize("not json") == []

    def test_post_migration_native_array(self):
        """T4.8 — After pgvector migration, embedding should be stored as native array.

        This test verifies the serialization format. Post-migration, serialize()
        should be removed and embeddings stored directly as float lists.
        """
        vec = [1.0, 2.0, 3.0]
        serialized = serialize(vec)
        # Current: JSON string
        assert isinstance(serialized, str)
        assert serialized == "[1.0, 2.0, 3.0]"


class TestDedup:
    def test_duplicate_above_threshold(self):
        """T4.4 — is_duplicate returns True when similarity >= 0.92."""
        # Identical vector = cosine 1.0, above 0.92
        assert is_duplicate(VEC_A, [VEC_A]) is True

    def test_not_duplicate_below_threshold(self):
        """T4.5 — is_duplicate returns False when below threshold."""
        # Orthogonal vectors = cosine 0.0, below 0.92
        assert is_duplicate(VEC_A, [VEC_B]) is False

    def test_duplicate_empty_existing(self):
        """No existing embeddings = not a duplicate."""
        assert is_duplicate(VEC_A, []) is False

    def test_duplicate_custom_threshold(self):
        """Custom threshold works."""
        sim = cosine(VEC_A, VEC_C)
        # sim ~ 0.707, set threshold just below
        assert is_duplicate(VEC_A, [VEC_C], threshold=0.5) is True
        assert is_duplicate(VEC_A, [VEC_C], threshold=0.9) is False


class TestScoreRelevance:
    def test_range(self):
        """T4.6 — score_relevance returns float in [0.0, 1.0]."""
        score = score_relevance(VEC_A, VEC_C)
        assert 0.0 <= score <= 1.0

    def test_identical_max(self):
        """Identical embeddings = max relevance (1.0)."""
        assert score_relevance(VEC_A, VEC_A) == pytest.approx(1.0)

    def test_orthogonal_zero(self):
        """Orthogonal embeddings = zero relevance."""
        assert score_relevance(VEC_A, VEC_B) == pytest.approx(0.0)


class TestBuildFingerprint:
    def test_builds_text(self):
        """build_org_fingerprint_text returns meaningful text."""
        settings = {
            "onboard_company_name": "Acme Corp",
            "onboard_industry": "SaaS",
            "onboard_topics": '["API", "REST"]',
            "onboard_competitors": '["Competitor A"]',
            "onboard_domain": "acme.com",
        }
        text = build_org_fingerprint_text(settings)
        assert "Acme Corp" in text
        assert "SaaS" in text
        assert "API" in text
        assert "acme.com" in text

    def test_empty_settings(self):
        """Empty settings returns empty string."""
        text = build_org_fingerprint_text({})
        assert text == ""

    def test_json_string_topics(self):
        """Topics as JSON string are parsed."""
        settings = {"onboard_topics": '["Machine Learning", "NLP"]'}
        text = build_org_fingerprint_text(settings)
        assert "Machine Learning" in text
