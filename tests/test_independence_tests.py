import random
import unittest

from causy.graph import graph_model_factory
from causy.utils import sum_lists
from causy.independence_tests import (
    CalculateCorrelations,
    CorrelationCoefficientTest,
)


class IndependenceTestTestCase(unittest.TestCase):
    def test_correlation_coefficient_standard_model(self):
        samples = {}
        test_data = []
        n = 1000
        x = [random.normalvariate(mu=0.0, sigma=1.0) for _ in range(n)]
        noise_y = [random.normalvariate(mu=0.0, sigma=1.0) for _ in range(n)]
        y = sum_lists([5 * x_val for x_val in x], noise_y)
        samples["x"] = x
        samples["y"] = y
        for i in range(n):
            entry = {}
            for key in samples.keys():
                entry[key] = samples[key][i]
            test_data.append(entry)

        pipeline = [CalculateCorrelations(), CorrelationCoefficientTest(threshold=0.1)]
        model = graph_model_factory(pipeline_steps=pipeline)()
        model.create_graph_from_data(test_data)
        model.create_all_possible_edges()
        model.execute_pipeline_steps()
        self.assertEqual(len(model.graph.action_history[-1]["actions"]), 0)


if __name__ == "__main__":
    unittest.main()
