from abc import ABC, abstractmethod
from statistics import correlation, linear_regression, covariance
from typing import Tuple, List, Optional
import numpy as np
import math
from utils import get_t_and_critial_t

from utils import get_correlation

from interfaces import IndependenceTestInterface, BaseGraphInterface, NodeInterface, CorrelationTestResult, \
    CorrelationTestResultAction, AS_MANY_AS_FIELDS, ComparisonSettings


class CalculateCorrelations(IndependenceTestInterface):

    NUM_OF_COMPARISON_ELEMENTS = 2
    CHUNK_SIZE_PARALLEL_PROCESSING = 10000
    PARALLEL = False

    def test(self, edges: Tuple[str], graph: BaseGraphInterface) -> CorrelationTestResult:
        """
        Test if x and y are independent
        :param edges: the Edges to test
        :return: A CorrelationTestResult with the action to take
        """
        x = graph.nodes[edges[0]]
        y = graph.nodes[edges[1]]

        edge_value = graph.edge_value(graph.nodes[edges[0]], graph.nodes[edges[1]])
        edge_value["correlation"] = correlation(x.values, y.values)
        # edge_value["covariance"] = covariance(x.values, y.values)
        return CorrelationTestResult(x=x, y=y, action=CorrelationTestResultAction.UPDATE_EDGE, data=edge_value,)



class CorrelationCoefficientTest(IndependenceTestInterface):

    NUM_OF_COMPARISON_ELEMENTS = 2
    CHUNK_SIZE_PARALLEL_PROCESSING = 10000
    PARALLEL = True

    def test(self, edges: Tuple[str], graph: BaseGraphInterface) -> CorrelationTestResult:
        """
        Test if x and y are independent
        :param edges: the Edges to test
        :return: A CorrelationTestResult with the action to take
        """
        x = graph.nodes[edges[0]]
        y = graph.nodes[edges[1]]

        #make t test for independency of x and y 
        sample_size = len(x.values)
        nb_of_control_vars = 0
        corr = graph.edge_value(x,y)["correlation"]
        t, critical_t = get_t_and_critial_t(sample_size, nb_of_control_vars, corr, self.threshold)
        print("critical_t")
        print(t, critical_t) 
        if abs(t) < critical_t:
            return CorrelationTestResult(x=x, y=y, action=CorrelationTestResultAction.REMOVE_EDGE_UNDIRECTED, data={})

        return CorrelationTestResult(x=x, y=y, action=CorrelationTestResultAction.DO_NOTHING, data={})


class PartialCorrelationTest(IndependenceTestInterface):

    NUM_OF_COMPARISON_ELEMENTS = 3
    CHUNK_SIZE_PARALLEL_PROCESSING = 10000
    PARALLEL = True

    def test(self, edges: Tuple[str], graph: BaseGraphInterface) -> CorrelationTestResult:
        """
            Test if edges x,y are independent based on partial correlation with z as conditioning variable
            we use this test for all combinations of 3 nodes because it is faster than the extended test and we can
            use it to remove edges which are not independent and so reduce the number of combinations for the extended
            (See https://en.wikipedia.org/wiki/Partial_correlation#Using_recursive_formula)
            :param edges: the Edges to test
            :return: A CorrelationTestResult with the action to take
        """
        x: NodeInterface = graph.nodes[edges[0]]
        y: NodeInterface = graph.nodes[edges[1]]
        z: NodeInterface = graph.nodes[edges[2]]

        # Avoid division by zero
        if x is None or y is None or z is None:
            return CorrelationTestResult(x=x, y=y, action=CorrelationTestResultAction.DO_NOTHING)
        try:
            cor_xy = graph.edge_value(x, y)["correlation"]
            cor_xz = graph.edge_value(x, z)["correlation"]
            cor_yz = graph.edge_value(y, z)["correlation"]
        except KeyError:
            print("k_error")
            return CorrelationTestResult(x=x, y=y, action=CorrelationTestResultAction.DO_NOTHING)

        numerator = cor_xy - cor_xz * cor_yz
        denominator = ((1 - cor_xz ** 2) * (1 - cor_yz ** 2)) ** 0.5

        # Avoid division by zero
        if denominator == 0:
            return CorrelationTestResult(x=x, y=y, action=CorrelationTestResultAction.DO_NOTHING)

        par_corr = numerator / denominator

        #make t test for independency of x and y given z
        sample_size = len(x.values)
        nb_of_control_vars = len(edges) - 2
        t, critical_t = get_t_and_critial_t(sample_size, nb_of_control_vars, par_corr, self.threshold)
        print("critical_t")
        print(t, critical_t)    

        if abs(t) < critical_t:
            return CorrelationTestResult(x=x, y=y, action=CorrelationTestResultAction.REMOVE_EDGE_UNDIRECTED, data={
                "separatedBy": [z]
            })
        return CorrelationTestResult(x=x, y=y, action=CorrelationTestResultAction.DO_NOTHING, data={})



class ExtendedPartialCorrelationTest(IndependenceTestInterface):

    NUM_OF_COMPARISON_ELEMENTS = ComparisonSettings(min=5, max=AS_MANY_AS_FIELDS)
    CHUNK_SIZE_PARALLEL_PROCESSING = 1

    def test(self, nodes: List[str], graph: BaseGraphInterface) -> CorrelationTestResult:
        """
        Test if edges x,y are independent based on partial correlation with z as conditioning variable
        we use this test for all combinations of more than 3 nodes because it is slower.

        """
        n = len(nodes)
        sample_size = len(graph.nodes[nodes[0]].values)
        nb_of_control_vars = n - 2
        results = []
        for i in range(n):
            for j in range(i+1,n):
                x = graph.nodes[nodes[i]]
                y = graph.nodes[nodes[j]]
                exclude_indices = [i, j]
                other_nodes = [graph.nodes[n].values for idx, n in enumerate(nodes) if idx not in exclude_indices]
                par_corr = get_correlation(x, y, other_nodes)

                # make t test for independence of a and y given other nodes
                t, critical_t = get_t_and_critial_t(sample_size, nb_of_control_vars, par_corr, self.threshold)
                if abs(t) < critical_t:
                    results.append(CorrelationTestResult(x=x, y=y,
                                                         action=CorrelationTestResultAction.REMOVE_EDGE_UNDIRECTED,
                                                         data={
                        "separatedBy": other_nodes
                    }))

        return results


class UnshieldedTriplesTest(IndependenceTestInterface):
    NUM_OF_COMPARISON_ELEMENTS = 2
    CHUNK_SIZE_PARALLEL_PROCESSING = 1000


    def test(self, edges: Tuple[str], graph: BaseGraphInterface) -> List[CorrelationTestResult]|CorrelationTestResult:
        # https://github.com/pgmpy/pgmpy/blob/1fe10598df5430295a8fc5cdca85cf2d9e1c4330/pgmpy/estimators/PC.py#L416

        x = graph.nodes[edges[0]]
        y = graph.nodes[edges[1]]

        if graph.edge_exists(x, y):
            return CorrelationTestResult(x=x, y=y, action=CorrelationTestResultAction.DO_NOTHING, data={})

        potential_zs = set(graph.edges[x].keys()).intersection(set(graph.edges[y].keys()))

        for z in potential_zs:
            separators = graph.retrieve_edge_history(x, y, CorrelationTestResultAction.REMOVE_EDGE_UNDIRECTED)

            if z not in separators:
                return [CorrelationTestResult(x=z, y=x, action=CorrelationTestResultAction.REMOVE_EDGE_DIRECTED, data={}),
                        CorrelationTestResult(x=z, y=y, action=CorrelationTestResultAction.REMOVE_EDGE_DIRECTED, data={})]

        return CorrelationTestResult(x=x, y=y, action=CorrelationTestResultAction.DO_NOTHING, data={})


class ExtendedPartialCorrelationTest2(IndependenceTestInterface):

    NUM_OF_COMPARISON_ELEMENTS = ComparisonSettings(min=4, max=AS_MANY_AS_FIELDS)
    CHUNK_SIZE_PARALLEL_PROCESSING = 50
    PARALLEL = False


    def test(self, nodes: List[str], graph: BaseGraphInterface) -> CorrelationTestResult:

        covariance_matrix = [[None for _ in range(len(nodes))] for _ in range(len(nodes))]
        for i in range(len(nodes)):
            for k in range(i, len(nodes)):
                if covariance_matrix[i][k] is None:
                    covariance_matrix[i][k] = covariance(graph.nodes[nodes[i]].values, graph.nodes[nodes[k]].values)
                    covariance_matrix[k][i] = covariance_matrix[i][k]

        cov_matrix = np.array(covariance_matrix)
        inverse_cov_matrix = np.linalg.inv(cov_matrix)
        n = len(inverse_cov_matrix)
        diagonal = np.diagonal(inverse_cov_matrix)
        diagonal_matrix = np.zeros((n, n))
        np.fill_diagonal(diagonal_matrix, diagonal)
        helper = np.dot(np.sqrt(diagonal_matrix), inverse_cov_matrix)
        partial_correlation_coefficients = np.dot(helper, np.sqrt(diagonal_matrix))
        par_corr_xy = partial_correlation_coefficients[1][0]

class PlaceholderTest(IndependenceTestInterface):
    NUM_OF_COMPARISON_ELEMENTS = 2
    CHUNK_SIZE_PARALLEL_PROCESSING = 10
    PARALLEL = False


    def test(self, edges: Tuple[str], graph: BaseGraphInterface) -> List[CorrelationTestResult]|CorrelationTestResult:
        print("PlaceholderTest")
        return CorrelationTestResult(x=None, y=None, action=CorrelationTestResultAction.DO_NOTHING, data={})
