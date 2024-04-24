from typing import Optional, List, Union, Dict, Any

from pydantic import BaseModel

from causy.interfaces import (
    LogicStepInterface,
    BaseGraphInterface,
    GraphModelInterface,
    PipelineStepInterface,
    ExitConditionInterface,
)
from causy.graph_utils import (
    load_pipeline_artefact_by_definition,
    load_pipeline_steps_by_definition,
)


class Loop(LogicStepInterface):
    """
    A loop which executes a list of pipeline_steps until the exit_condition is met.
    """

    pipeline_steps: Optional[
        List[Union[LogicStepInterface, PipelineStepInterface]]
    ] = None
    exit_condition: Optional[ExitConditionInterface] = None

    def execute(
        self, graph: BaseGraphInterface, graph_model_instance_: GraphModelInterface
    ):
        """
        Executes the loop til self.exit_condition is met
        :param graph:
        :param graph_model_instance_:
        :return:
        """
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
        pipeline_steps: Optional[
            Union[List[PipelineStepInterface], Dict[Any, Any]]
        ] = None,
        exit_condition: Union[ExitConditionInterface, Dict[Any, Any]] = None,
    ):
        super().__init__()
        # TODO check if this is a good idea
        if isinstance(exit_condition, dict):
            exit_condition = load_pipeline_artefact_by_definition(exit_condition)

        # TODO: check if this is a good idea
        if len(pipeline_steps) > 0 and isinstance(pipeline_steps[0], dict):
            pipeline_steps = load_pipeline_steps_by_definition(pipeline_steps)

        self.pipeline_steps = pipeline_steps or []
        self.exit_condition = exit_condition


class ApplyActionsTogether(LogicStepInterface):
    """
    A logic step which collects all actions and only takes them at the end of the pipeline
    """

    pipeline_steps: Optional[
        List[Union[LogicStepInterface, PipelineStepInterface]]
    ] = None

    def execute(
        self, graph: BaseGraphInterface, graph_model_instance_: GraphModelInterface
    ):
        """
        Executes the loop til self.exit_condition is met
        :param graph:
        :param graph_model_instance_:
        :return:
        """
        actions = []
        for pipeline_step in self.pipeline_steps:
            result = graph_model_instance_.execute_pipeline_step(pipeline_step)
            actions.extend(result)

        graph_model_instance_._take_action(actions)

    def __init__(
        self,
        pipeline_steps: Optional[
            Union[List[PipelineStepInterface], Dict[Any, Any]]
        ] = None,
    ):
        super().__init__()
        # TODO: check if this is a good idea
        if len(pipeline_steps) > 0 and isinstance(pipeline_steps[0], dict):
            pipeline_steps = load_pipeline_steps_by_definition(pipeline_steps)

        self.pipeline_steps = pipeline_steps or []
