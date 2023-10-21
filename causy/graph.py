import importlib
import itertools
import json
from abc import ABC
from dataclasses import dataclass
from typing import List, Optional, Dict, Set
import multiprocessing as mp

from causy.interfaces import (
    IndependenceTestInterface,
)

from causy.interfaces import (
    BaseGraphInterface,
    NodeInterface,
    TestResultAction,
    TestResult,
    GraphModelInterface,
    LogicStepInterface,
    ExitConditionInterface,
)

import logging

from causy.utils import (
    load_pipeline_artefact_by_definition,
    load_pipeline_steps_by_definition,
)

logger = logging.getLogger(__name__)


@dataclass
class Node(NodeInterface):
    name: str
    values: List[float]

    def __hash__(self):
        return hash(self.name)


class UndirectedGraphError(Exception):
    pass


class UndirectedGraph(BaseGraphInterface):
    nodes: Dict[str, Node]
    edges: Dict[Node, Dict[Node, Dict]]
    edge_history: Dict[Set[Node], List[TestResult]]
    action_history: List[Dict[str, List[TestResult]]]

    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.edge_history = {}
        self.action_history = []

    def add_edge(self, u: Node, v: Node, value: Dict):
        """
        Add an edge to the graph
        :param u: u node
        :param v: v node
        :return:
        """
        if u.name not in self.nodes:
            raise UndirectedGraphError(f"Node {u} does not exist")
        if v.name not in self.nodes:
            raise UndirectedGraphError(f"Node {v} does not exist")
        if u not in self.edges:
            self.edges[u] = {}
        if v not in self.edges:
            self.edges[v] = {}

        self.edges[u][v] = value
        self.edges[v][u] = value

        self.edge_history[(u, v)] = []
        self.edge_history[(v, u)] = []

    def retrieve_edge_history(
        self, u, v, action: TestResultAction = None
    ) -> List[TestResult]:
        """
        Retrieve the edge history
        :param u:
        :param v:
        :param action:
        :return:
        """
        if action is None:
            return self.edge_history[(u, v)]

        return [i for i in self.edge_history[(u, v)] if i.action == action]

    def add_edge_history(self, u, v, action: TestResultAction):
        if (u, v) not in self.edge_history:
            self.edge_history[(u, v)] = []
        self.edge_history[(u, v)].append(action)

    def remove_edge(self, u: Node, v: Node):
        """
        Remove an edge from the graph
        :param u: u node
        :param v: v node
        :return:
        """
        if u.name not in self.nodes:
            raise UndirectedGraphError(f"Node {u} does not exist")
        if v.name not in self.nodes:
            raise UndirectedGraphError(f"Node {v} does not exist")
        if u not in self.edges:
            raise UndirectedGraphError(f"Node {u} does not have any nodes")
        if v not in self.edges:
            raise UndirectedGraphError(f"Node {v} does not have any nodes")

        if v not in self.edges[u]:
            return
        del self.edges[u][v]

        if u not in self.edges[v]:
            return
        del self.edges[v][u]

    def remove_directed_edge(self, u: Node, v: Node):
        """
        Remove an edge from the graph
        :param u: u node
        :param v: v node
        :return:
        """
        if u.name not in self.nodes:
            raise UndirectedGraphError(f"Node {u} does not exist")
        if v.name not in self.nodes:
            raise UndirectedGraphError(f"Node {v} does not exist")
        if u not in self.edges:
            raise UndirectedGraphError(f"Node {u} does not have any nodes")
        if v not in self.edges:
            raise UndirectedGraphError(f"Node {v} does not have any nodes")

        if v not in self.edges[u]:
            return
        del self.edges[u][v]

    def update_edge(self, u: Node, v: Node, value: Dict):
        """
        Update an edge in the graph
        :param u: u node
        :param v: v node
        :return:
        """
        if u.name not in self.nodes:
            raise UndirectedGraphError(f"Node {u} does not exist")
        if v.name not in self.nodes:
            raise UndirectedGraphError(f"Node {v} does not exist")
        if u not in self.edges:
            raise UndirectedGraphError(f"Node {u} does not have any edges")
        if v not in self.edges:
            raise UndirectedGraphError(f"Node {v} does not have any edges")

        self.edges[u][v] = value
        self.edges[v][u] = value

    def update_directed_edge(self, u: Node, v: Node, value: Dict):
        """
        Update an edge in the graph
        :param u: u node
        :param v: v node
        :return:
        """
        if u.name not in self.nodes:
            raise UndirectedGraphError(f"Node {u} does not exist")
        if v.name not in self.nodes:
            raise UndirectedGraphError(f"Node {v} does not exist")
        if u not in self.edges:
            raise UndirectedGraphError(f"Node {u} does not have any edges")
        if v not in self.edges[u]:
            raise UndirectedGraphError(f"There is no edge from {u} to {v}")

        self.edges[u][v] = value

    def edge_exists(self, u: Node, v: Node):
        """
        Check if any edge exists between u and v. Cases: u -> v, u <-> v, u <- v
        :param u: node u
        :param v: node v
        :return: True if any edge exists, False otherwise
        """
        if u.name not in self.nodes:
            return False
        if v.name not in self.nodes:
            return False
        if u in self.edges and v in self.edges[u]:
            return True
        if v in self.edges and u in self.edges[v]:
            return True
        return False

    def directed_edge_exists(self, u: Node, v: Node):
        """
        Check if a directed edge exists between u and v. Cases: u -> v, u <-> v
        :param u: node u
        :param v: node v
        :return: True if a directed edge exists, False otherwise
        """
        if u.name not in self.nodes:
            return False
        if v.name not in self.nodes:
            return False
        if u not in self.edges:
            return False
        if v not in self.edges[u]:
            return False
        return True

    def only_directed_edge_exists(self, u: Node, v: Node):
        """
        Check if a directed edge exists between u and v, but no directed edge exists between v and u. Case: u -> v
        :param u: node u
        :param v: node v
        :return: True if only directed edge exists, False otherwise
        """
        if self.directed_edge_exists(u, v) and not self.directed_edge_exists(v, u):
            return True
        return False

    def undirected_edge_exists(self, u: Node, v: Node):
        """
        Check if an undirected edge exists between u and v. Note: currently, an undirected edges is implemented just as
        a directed edge. However, they are two functions as they mean different things in different algorithms.
        Currently, this function is used in the PC algorithm, where an undirected edge is an edge which could not be
        oriented in any direction by orientation rules.
        Later, a cohersive naming scheme should be implemented.
        :param u: node u
        :param v: node v
        :return: True if an undirected edge exists, False otherwise
        """
        if self.directed_edge_exists(u, v) and self.directed_edge_exists(v, u):
            return True
        return False

    def bidirected_edge_exists(self, u: Node, v: Node):
        """
        Check if a bidirected edge exists between u and v. Note: currently, a bidirected edges is implemented just as
        an undirected edge. However, they are two functions as they mean different things in different algorithms.
        This function will be used for the FCI algorithm for now, where a bidirected edge is an edge between two nodes
        that have been identified to have a common cause by orientation rules.
        Later, a cohersive naming scheme should be implemented.
        :param u: node u
        :param v: node v
        :return: True if a bidirected edge exists, False otherwise
        """
        if self.directed_edge_exists(u, v) and self.directed_edge_exists(v, u):
            return True
        return False

    def edge_value(self, u: Node, v: Node):
        return self.edges[u][v]

    def add_node(self, name: str, values: List[float]):
        """
        Add a node to the graph
        :param name: name of the node
        :param values: values of the node
        :param : node

        :return:
        """
        self.nodes[name] = Node(name, values)

    def directed_path_exists(self, u: Node, v: Node):
        """
        Check if a directed path from u to v exists
        :param u: node u
        :param v: node v
        :return: True if a directed path exists, False otherwise
        """
        if self.directed_edge_exists(u, v):
            return True
        for w in self.edges[u]:
            if self.directed_path_exists(w, v):
                return True
        return False

    def directed_paths(self, u: Node, v: Node):
        """
        Return all directed paths from u to v
        :param u: node u
        :param v: node v
        :return: list of directed paths
        """
        if self.directed_edge_exists(u, v):
            return [[(u, v)]]
        paths = []
        for w in self.edges[u]:
            for path in self.directed_paths(w, v):
                paths.append([(u, w)] + path)
        return paths

    def inducing_path_exists(self, u: Node, v: Node):
        """
        Check if an inducing path from u to v exists.
        An inducing path from u to v is a directed path from u to v on which all mediators are colliders.
        :param u: node u
        :param v: node v
        :return: True if an inducing path exists, False otherwise
        """
        if not self.directed_path_exists(u, v):
            return False
        for path in self.directed_paths(u, v):
            for i in range(1, len(path) - 1):
                r, w = path[i]
                if not self.bidirected_edge_exists(r, w):
                    return False
        return False


def unpack_run(args):
    tst = args[0]
    del args[0]
    return tst(*args)


class AbstractGraphModel(GraphModelInterface, ABC):

    pipeline_steps: List[IndependenceTestInterface]
    graph: BaseGraphInterface
    pool: mp.Pool

    def __init__(
        self,
        graph=None,
        pipeline_steps: Optional[List[IndependenceTestInterface]] = None,
    ):
        self.graph = graph
        self.pipeline_steps = pipeline_steps or []
        self.pool = mp.Pool(mp.cpu_count() * 2)

    def create_graph_from_data(self, data: List[Dict[str, float]]):
        """
        Create a graph from data
        :param data: is a list of dictionaries
        :return:
        """
        # initialize nodes
        keys = data[0].keys()
        nodes: Dict[str, List[float]] = {}

        for key in keys:
            nodes[key] = []

        # load nodes into node dict
        for row in data:
            for key in keys:
                nodes[key].append(row[key])

        graph = UndirectedGraph()
        for key in keys:
            graph.add_node(key, nodes[key])

        self.graph = graph
        return graph

    def create_all_possible_edges(self):
        """
        Create all possible nodes
        :return:
        """
        for u in self.graph.nodes.values():
            for v in self.graph.nodes.values():
                if u == v:
                    continue
                self.graph.add_edge(u, v, {})

    def execute_pipeline_steps(self):
        """
        Execute all pipeline_steps
        :return: the steps taken during the step execution
        """
        action_history = []

        for filter in self.pipeline_steps:
            logger.info(f"Executing pipeline step {filter.__class__.__name__}")
            if isinstance(filter, LogicStepInterface):
                filter.execute(self.graph, self)
                continue

            result = self.execute_pipeline_step(filter)
            action_history.append(
                {"step": filter.__class__.__name__, "actions": result}
            )

        return action_history

    def _format_yield(self, test_fn, graph, generator):
        for i in generator:
            yield [test_fn, [*i], graph]

    def _take_action(self, results):
        actions_taken = []
        for result_items in results:
            if result_items is None:
                continue
            if not isinstance(result_items, list):
                result_items = [result_items]

            for i in result_items:
                if i.x is not None and i.y is not None:
                    logger.info(f"Action: {i.action} on {i.x.name} and {i.y.name}")

                # execute the action returned by the test
                if i.action == TestResultAction.REMOVE_EDGE_UNDIRECTED:
                    if not self.graph.undirected_edge_exists(i.x, i.y):
                        logger.debug(
                            f"Tried to remove undirected edge {i.x.name} <-> {i.y.name}. But it does not exist."
                        )
                        continue
                    self.graph.remove_edge(i.x, i.y)
                    self.graph.add_edge_history(i.x, i.y, i)
                    self.graph.add_edge_history(i.y, i.x, i)
                elif i.action == TestResultAction.UPDATE_EDGE:
                    if not self.graph.edge_exists(i.x, i.y):
                        logger.debug(
                            f"Tried to update edge {i.x.name} -> {i.y.name}. But it does not exist."
                        )
                        continue
                    self.graph.update_edge(i.x, i.y, i.data)
                    self.graph.add_edge_history(i.x, i.y, i)
                    self.graph.add_edge_history(i.y, i.x, i)
                elif i.action == TestResultAction.UPDATE_EDGE_DIRECTED:
                    if not self.graph.directed_edge_exists(i.x, i.y):
                        logger.debug(
                            f"Tried to update directed edge {i.x.name} -> {i.y.name}. But it does not exist."
                        )
                        continue
                    self.graph.update_directed_edge(i.x, i.y, i.data)
                    self.graph.add_edge_history(i.x, i.y, i)
                elif i.action == TestResultAction.DO_NOTHING:
                    continue
                elif i.action == TestResultAction.REMOVE_EDGE_DIRECTED:
                    if not self.graph.directed_edge_exists(i.x, i.y):
                        logger.debug(
                            f"Tried to remove directed edge {i.x.name} -> {i.y.name}. But it does not exist."
                        )
                        continue
                    self.graph.remove_directed_edge(i.x, i.y)
                    self.graph.add_edge_history(i.x, i.y, i)

                # add the action to the actions history
                actions_taken.append(i)

        return actions_taken

    def execute_pipeline_step(self, test_fn: IndependenceTestInterface):
        """
        Filter the graph
        :param test_fn: the test function
        :param threshold: the threshold
        :return:
        """
        actions_taken = []

        # initialize the worker pool (we currently use all available cores * 2)

        # run all combinations in parallel except if the number of combinations is smaller then the chunk size
        # because then we would create more overhead then we would definetly gain from parallel processing
        if test_fn.PARALLEL:
            for result in self.pool.imap_unordered(
                unpack_run,
                self._format_yield(
                    test_fn, self.graph, test_fn.GENERATOR.generate(self.graph, self)
                ),
                chunksize=test_fn.CHUNK_SIZE_PARALLEL_PROCESSING,
            ):
                if not isinstance(result, list):
                    result = [result]
                actions_taken.extend(self._take_action(result))
        else:
            iterator = [
                unpack_run(i)
                for i in [
                    [test_fn, [*i], self.graph]
                    for i in test_fn.GENERATOR.generate(self.graph, self)
                ]
            ]
            actions_taken.extend(self._take_action(iterator))
        self.graph.action_history.append(
            {"step": type(test_fn).__name__, "actions": actions_taken}
        )

        return actions_taken


def graph_model_factory(
    pipeline_steps: Optional[List[IndependenceTestInterface]] = None,
) -> type[AbstractGraphModel]:
    """
    Create a graph model
    :param pipeline_steps: a list of pipeline_steps which should be applied to the graph
    :return: the graph model
    """

    class GraphModel(AbstractGraphModel):
        def __init__(self):
            super().__init__(pipeline_steps=pipeline_steps)

    return GraphModel


class Loop(LogicStepInterface):
    def execute(
        self, graph: BaseGraphInterface, graph_model_instance_: GraphModelInterface
    ):
        n = 0
        steps = None
        while not self.exit_condition(
            graph=graph,
            graph_model_instance_=graph_model_instance_,
            actions_taken=steps,
            iteration=n,
        ):
            steps = []
            for pipeline_step in self.pipeline_steps:
                result = graph_model_instance_.execute_pipeline_step(pipeline_step)
                steps.extend(result)
            n += 1

    def __init__(
        self,
        pipeline_steps: Optional[List[IndependenceTestInterface]] = None,
        exit_condition: ExitConditionInterface = None,
    ):
        super().__init__()
        # TODO check if this is a good idea
        if type(exit_condition) == dict:
            exit_condition = load_pipeline_artefact_by_definition(exit_condition)

        # TODO: check if this is a good idea
        if len(pipeline_steps) > 0 and type(pipeline_steps[0]) == dict:
            pipeline_steps = load_pipeline_steps_by_definition(pipeline_steps)

        self.pipeline_steps = pipeline_steps or []
        self.exit_condition = exit_condition

    def serialize(self) -> dict:
        serialized = super().serialize()
        serialized["params"] = {}
        serialized["params"]["exit_condition"] = self.exit_condition.serialize()
        serialized["params"]["pipeline_steps"] = [
            i.serialize() for i in self.pipeline_steps
        ]
        return serialized
