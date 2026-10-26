"""使用手算样例验证指标，避免错误公式给出漂亮数字。"""

import math
import unittest

from backend.evals.retrieval_metrics import macro_average, score_ranking


class RetrievalMetricsTests(unittest.TestCase):
    def test_multiple_relevant_documents_and_rank_discount(self):
        result = score_ranking(["b", "a", "c"], {"a", "c"}, 3)
        self.assertEqual(result["recall"], 1)
        self.assertAlmostEqual(result["precision"], 2 / 3)
        self.assertEqual(result["mrr"], 0.5)
        self.assertAlmostEqual(result["ndcg"], (1 / math.log2(3) + 0.5) / (1 + 1 / math.log2(3)))

    def test_cutoff_and_short_result_precision(self):
        self.assertEqual(score_ranking(["b", "a"], {"a"}, 1)["recall"], 0)
        result = score_ranking(["a"], {"a", "c"}, 5)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["precision"], 0.2)
        self.assertEqual(result["mrr"], 1)

    def test_empty_hits_and_macro_average(self):
        missing = score_ranking([], {"a"}, 3)
        perfect = score_ranking(["a"], {"a"}, 3)
        self.assertEqual(missing, dict.fromkeys(["recall", "precision", "mrr", "ndcg"], 0))
        self.assertEqual(macro_average([missing, perfect])["recall"], 0.5)

    def test_invalid_labels_or_duplicate_ranks_are_rejected(self):
        for ranking, gold, k in [([], set(), 3), (["a", "a"], {"a"}, 3), ([], {"a"}, 0)]:
            with self.assertRaises(ValueError):
                score_ranking(ranking, gold, k)
