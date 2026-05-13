from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.journal_match.topic_profile import ManuscriptTopicProfile

NUMPY_ABSTRACT = (
    "Array programming with NumPy. NumPy is the fundamental array programming library "
    "for scientific computing in Python. It provides a high-performance multidimensional "
    "array object and tools for working with these arrays. We demonstrate how NumPy enables "
    "efficient numerical computations through vectorization, broadcasting, and indexing. "
    "As an application example, we use NumPy to analyze gravitational wave data from LIGO, "
    "and we apply the library to reconstruct black hole images from the Event Horizon Telescope. "
    "NumPy has become a cornerstone of the Python scientific computing stack, supporting "
    "research across physics, astronomy, biology, and engineering."
)

STREET_FOOD_TEXT = (
    "Traditional Vietnamese street food and urban sidewalk culture. "
    "This study examines the vibrant street food scene in Hanoi and Ho Chi Minh City, "
    "focusing on how sidewalk vendors shape urban public space. We investigate the cultural "
    "significance of pho, banh mi, and other traditional dishes in Vietnam's urban food culture. "
    "The research combines ethnographic observation with qualitative interviews to understand "
    "the social dynamics of street food vending."
)


class ManuscriptTopicProfileTest(unittest.TestCase):
    def test_numpy_topic_extraction(self) -> None:
        profile = ManuscriptTopicProfile(
            title="Array programming with NumPy",
            abstract=NUMPY_ABSTRACT,
            keywords=["NumPy", "array programming", "scientific computing", "Python"],
            subjects=["Computer Science", "Scientific Computing", "Numerical Analysis"],
        )
        result = profile.to_dict()
        self.assertEqual(result["research_field"], "computer_science")
        self.assertIn("numpy", profile.main_topic_text.lower())
        self.assertIn("scientific computing", profile.main_topic_text.lower())
        self.assertEqual(profile.research_field, "computer_science")
        self.assertIsNotNone(result.get("application_domain_summary"))

    def test_numpy_excludes_astronomy_from_main_topic(self) -> None:
        profile = ManuscriptTopicProfile(
            title="Array programming with NumPy",
            abstract=NUMPY_ABSTRACT,
            keywords=["NumPy", "array programming", "scientific computing", "Python"],
            subjects=["Computer Science", "Scientific Computing"],
        )
        clean_query = profile.build_embedding_query()
        clean_lower = clean_query.lower()
        self.assertIn("numpy", clean_lower)
        self.assertIn("scientific computing", clean_lower)
        self.assertNotIn("black hole", clean_lower)
        self.assertNotIn("ligo", clean_lower)

    def test_numpy_excluded_minor_topics(self) -> None:
        profile = ManuscriptTopicProfile(
            title="Array programming with NumPy",
            abstract=NUMPY_ABSTRACT,
            keywords=["NumPy", "array programming", "scientific computing", "Python"],
            subjects=["Computer Science", "Scientific Computing"],
        )
        excluded = profile.excluded_minor_topics
        topic_terms = {"ligo", "black", "hole", "gravitational", "wave", "telescope", "horizon", "event"}
        self.assertTrue(
            any(term in excluded for term in topic_terms),
            msg=f"Expected astronomy terms in excluded_minor_topics but got {excluded}",
        )

    def test_street_food_topic_classification(self) -> None:
        profile = ManuscriptTopicProfile(
            title="Traditional Vietnamese street food and urban sidewalk culture",
            abstract=STREET_FOOD_TEXT,
            keywords=["street food", "Vietnamese cuisine", "urban culture", "sidewalk vending"],
            subjects=["Food Studies", "Urban Studies", "Cultural Anthropology"],
        )
        result = profile.to_dict()
        self.assertIn("food", result.get("main_topic_summary", "").lower())
        self.assertIn("street", result.get("main_topic_summary", "").lower())
        clean_query = profile.build_embedding_query()
        self.assertIn("vietnamese", clean_query.lower())
        self.assertIn("street food", clean_query.lower())

    def test_from_doi_metadata(self) -> None:
        metadata = {
            "doi": "10.1038/s41586-020-2649-2",
            "title": "Array programming with NumPy",
            "abstract": NUMPY_ABSTRACT,
            "subjects": ["Computer Science", "Scientific Computing", "Numerical Analysis"],
            "keywords": ["NumPy", "array programming", "scientific computing", "Python"],
            "year": 2020,
        }
        profile = ManuscriptTopicProfile.from_doi_metadata(metadata)
        self.assertEqual(profile.title, "Array programming with NumPy")
        self.assertIn("numpy", profile.build_embedding_query().lower())
        self.assertNotIn("black hole", profile.build_embedding_query().lower())

    def test_clean_query_removes_application_paragraphs(self) -> None:
        text_with_app = (
            "A new algorithm for fast matrix multiplication. "
            "We present a novel divide-and-conquer approach to matrix multiplication "
            "that reduces the number of scalar multiplications. "
            "We apply this algorithm to train large neural networks, "
            "and we demonstrate its effectiveness in image recognition and natural language processing. "
            "The method achieves a 15% speedup over existing approaches."
        )
        profile = ManuscriptTopicProfile(
            title="Fast Matrix Multiplication Algorithm",
            abstract=text_with_app,
            keywords=["matrix multiplication", "algorithm"],
        )
        clean = profile.build_embedding_query().lower()
        self.assertIn("matrix multiplication", clean)
        self.assertNotIn("image recognition", clean)
        self.assertNotIn("natural language processing", clean)


if __name__ == "__main__":
    unittest.main()
