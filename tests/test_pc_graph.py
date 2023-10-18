import csv
import json
import unittest
import numpy as np

from causy.algorithms import PC
from causy.cli import show_edges


# TODO: generate larger toy model to test quadruple orientation rules.
def generate_data_minimal_example(a, b, c, d, sample_size):
    V = d * np.random.normal(0, 1, sample_size)
    W = c * np.random.normal(0, 1, sample_size)
    Z = W + V + np.random.normal(0, 1, sample_size)
    X = a * Z + np.random.normal(0, 1, sample_size)
    Y = b * Z + np.random.normal(0, 1, sample_size)

    data = {}
    data["V"], data["W"], data["Z"], data["X"], data["Y"] = V, W, Z, X, Y
    test_data = []

    for i in range(sample_size):
        entry = {}
        for key in data.keys():
            entry[key] = data[key][i]
        test_data.append(entry)
    return test_data


def generate_data_further_example(a, b, c, d, e, f, g, sample_size):
    A = a * np.random.normal(0, 1, sample_size)
    B = b * np.random.normal(0, 1, sample_size)
    C = A + c * B + np.random.normal(0, 1, sample_size)
    D = d * A + B + C + np.random.normal(0, 1, sample_size)
    E = e * B + np.random.normal(0, 1, sample_size)
    F = f * E + g * B + C + D + np.random.normal(0, 1, sample_size)

    data = {}
    data["A"], data["B"], data["C"], data["D"], data["E"], data["F"] = A, B, C, D, E, F
    test_data = []

    for i in range(sample_size):
        entry = {}
        for key in data.keys():
            entry[key] = data[key][i]
        test_data.append(entry)

    return test_data


class PCTestTestCase(unittest.TestCase):
    def test_with_rki_data(self):
        with open("./tests/fixtures/rki-data.csv") as f:
            data = csv.DictReader(f)
            test_data = []
            for row in data:
                for k in row.keys():
                    if row[k] == "":
                        row[k] = 0.0
                    row[k] = float(row[k])
                test_data.append(row)

        tst = PC()
        tst.create_graph_from_data(test_data)
        tst.create_all_possible_edges()
        tst.execute_pipeline_steps()
        show_edges(tst.graph)

    def test_with_minimal_toy_model(self):
        a, b, c, d, sample_size = 1.2, 1.7, 2, 1.5, 10000
        test_data = generate_data_minimal_example(a, b, c, d, sample_size)
        tst = PC()
        tst.create_graph_from_data(test_data)
        tst.create_all_possible_edges()
        tst.execute_pipeline_steps()
        show_edges(tst.graph)

    def test_with_larger_toy_model(self):
        a, b, c, d, e, f, g, sample_size = 1.2, 1.7, 2, 1.5, 3, 4, 1.8, 10000
        test_data = generate_data_further_example(a, b, c, d, e, f, g, sample_size)
        tst = PC()
        tst.create_graph_from_data(test_data)
        tst.create_all_possible_edges()
        tst.execute_pipeline_steps()
        show_edges(tst.graph)


if __name__ == "__main__":
    unittest.main()
