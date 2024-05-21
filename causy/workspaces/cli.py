import json
import logging
from datetime import datetime
from typing import List

import pydantic_yaml
import questionary
import typer
import os

from markdown.extensions.toc import slugify
from pydantic_yaml import to_yaml_str
from jinja2 import (
    Environment,
    select_autoescape,
    ChoiceLoader,
    FileSystemLoader,
    PackageLoader,
)

from causy.graph_model import graph_model_factory
from causy.graph_utils import hash_dictionary
from causy.models import (
    CausyAlgorithmReference,
    CausyAlgorithmReferenceType,
    CausyResult,
)
from causy.serialization import (
    load_algorithm_by_reference,
    CausyJSONEncoder,
)
from causy.variables import validate_variable_values, resolve_variables
from causy.workspaces.models import Workspace, Experiment
from causy.data_loader import DataLoaderReference, load_data_loader

app = typer.Typer()
logger = logging.getLogger(__name__)

WORKSPACE_FILE_NAME = "workspace.yml"

JINJA_ENV = Environment(
    loader=ChoiceLoader(
        [
            PackageLoader("causy", "workspaces/templates"),
            FileSystemLoader("./templates"),
        ]
    ),
    autoescape=select_autoescape(),
)


class WorkspaceNotFoundError(Exception):
    pass


def _current_workspace(fail_if_none: bool = True) -> Workspace:
    """
    Return the current workspace.
    :param fail_if_none: if True, raise an exception if no workspace is found
    :return: the workspace
    """

    workspace_data = None
    workspace_path = os.path.join(os.getcwd(), WORKSPACE_FILE_NAME)
    if os.path.exists(workspace_path):
        with open(workspace_path, "r") as f:
            workspace_data = f.read()

    if fail_if_none and workspace_data is None:
        raise WorkspaceNotFoundError("No workspace found in the current directory")

    workspace = None

    if workspace_data is not None:
        workspace = pydantic_yaml.parse_yaml_raw_as(Workspace, workspace_data)

    return workspace


def _create_pipeline(workspace: Workspace = None) -> Workspace:
    pipeline_creation = questionary.select(
        "Do you want to use an existing pipeline or create a new one?",
        choices=[
            questionary.Choice(
                "Use an existing causy pipeline (preconfigured).", "PRECONFIGURED"
            ),
            questionary.Choice(
                "Eject existing pipeline (allows you to change pipeline configs).",
                "EJECT",
            ),
            questionary.Choice(
                "Create a pipeline skeleton (as a python module).", "SKELETON"
            ),
        ],
    ).ask()

    if pipeline_creation == "PRECONFIGURED":
        from causy.causal_discovery.constraint.algorithms import AVAILABLE_ALGORITHMS

        pipeline_name = questionary.select(
            "Which pipeline do you want to use?", choices=AVAILABLE_ALGORITHMS.keys()
        ).ask()

        pipeline_reference = AVAILABLE_ALGORITHMS[pipeline_name]
        # make pipeline reference as string
        pipeline = CausyAlgorithmReference(
            reference=pipeline_reference().algorithm.name,
            type=CausyAlgorithmReferenceType.NAME,
        )
        workspace.pipelines[pipeline_name] = pipeline
    elif pipeline_creation == "EJECT":
        from causy.causal_discovery.constraint.algorithms import AVAILABLE_ALGORITHMS

        pipeline_skeleton = questionary.select(
            "Which pipeline do you want to use?", choices=AVAILABLE_ALGORITHMS.keys()
        ).ask()
        pipeline_reference = AVAILABLE_ALGORITHMS[pipeline_skeleton]
        pipeline_name = questionary.text("Enter the name of the pipeline").ask()
        pipeline_slug = slugify(pipeline_name, "_")
        with open(f"{pipeline_slug}.yml", "w") as f:
            f.write(to_yaml_str(pipeline_reference()._original_algorithm))

        pipeline = CausyAlgorithmReference(
            reference=f"{pipeline_slug}.yml", type=CausyAlgorithmReferenceType.FILE
        )
        workspace.pipelines[pipeline_slug] = pipeline
    elif pipeline_creation == "SKELETON":
        pipeline_name = questionary.text("Enter the name of the pipeline").ask()
        pipeline_slug = slugify(pipeline_name, "_")
        JINJA_ENV.get_template("pipeline.py.tpl").stream(
            pipeline_name=pipeline_name
        ).dump(f"{pipeline_slug}.py")
        pipeline = CausyAlgorithmReference(
            reference=f"{pipeline_slug}.PIPELINE",
            type=CausyAlgorithmReferenceType.PYTHON_MODULE,
        )
        workspace.pipelines[pipeline_slug] = pipeline

    typer.echo(f'Pipeline "{pipeline_name}" created.')

    return workspace


def _create_experiment(workspace: Workspace) -> Workspace:
    experiment_name = questionary.text("Enter the name of the experiment").ask()
    experiment_pipeline = questionary.select(
        "Select the pipeline for the experiment", choices=workspace.pipelines.keys()
    ).ask()
    experiment_data_loader = questionary.select(
        "Select the data loader for the experiment",
        choices=workspace.data_loaders.keys(),
    ).ask()

    experiment_slug = slugify(experiment_name, "_")

    # extract and prefill the variables
    variables = {}
    pipeline = load_algorithm_by_reference(
        workspace.pipelines[experiment_pipeline].type,
        workspace.pipelines[experiment_pipeline].reference,
    )
    if len(pipeline.variables) > 0:
        variables = resolve_variables(pipeline.variables, {})

    workspace.experiments[experiment_slug] = Experiment(
        **{
            "pipeline": experiment_pipeline,
            "data_loader": experiment_data_loader,
            "variables": variables,
        }
    )

    typer.echo(f'Experiment "{experiment_name}" created.')

    return workspace


def _create_data_loader(workspace: Workspace) -> Workspace:
    data_loader_type = questionary.select(
        "Do you want to use an existing pipeline or create a new one?",
        choices=[
            questionary.Choice("Load a JSON File.", "json"),
            questionary.Choice("Load a JSONL File.", "jsonl"),
            questionary.Choice("Load data dynamically (via Python Script).", "dynamic"),
        ],
    ).ask()

    data_loader_name = questionary.text("Enter the name of the data loader").ask()

    if data_loader_type in ["json", "jsonl"]:
        data_loader_path = questionary.path(
            "Choose the file or enter the file name:",
        ).ask()
        data_loader_slug = slugify(data_loader_name, "_")
        workspace.data_loaders[data_loader_slug] = DataLoaderReference(
            **{
                "type": data_loader_type,
                "reference": data_loader_path,
            }
        )
    elif data_loader_type == "dynamic":
        data_loader_slug = slugify(data_loader_name, "_")
        JINJA_ENV.get_template("dataloader.py.tpl").stream(
            data_loader_name=data_loader_name
        ).dump(f"{data_loader_slug}.py")
        workspace.data_loaders[data_loader_slug] = DataLoaderReference(
            **{
                "type": data_loader_type,
                "reference": f"{data_loader_slug}.DataLoader",
            }
        )

    typer.echo(f'Data loader "{data_loader_name}" created.')

    return workspace


def _execute_experiment(workspace: Workspace, experiment: Experiment) -> CausyResult:
    """
    Execute an experiment. This function will load the pipeline and the data loader and execute the pipeline.
    :param workspace:
    :param experiment:
    :return:
    """
    typer.echo(f"Loading Pipeline: {experiment.pipeline}")
    pipeline = load_algorithm_by_reference(
        workspace.pipelines[experiment.pipeline].type,
        workspace.pipelines[experiment.pipeline].reference,
    )

    validate_variable_values(pipeline, experiment.variables)
    variables = resolve_variables(pipeline.variables, experiment.variables)
    typer.echo(f"Using variables: {variables}")

    typer.echo(f"Loading Data: {experiment.data_loader}")
    data_loader = load_data_loader(workspace.data_loaders[experiment.data_loader])

    model = graph_model_factory(pipeline)()
    model.create_graph_from_data(data_loader)
    model.create_all_possible_edges()
    model.execute_pipeline_steps()
    return CausyResult(
        algorithm=workspace.pipelines[experiment.pipeline],
        action_history=model.graph.graph.action_history,
        edges=model.graph.retrieve_edges(),
        nodes=model.graph.nodes,
        variables=variables,
        data_loader_hash=data_loader.hash(),
        algorithm_hash=pipeline.hash(),
        variables_hash=hash_dictionary(variables),
    )


def _load_latest_experiment_result(
    workspace: Workspace, experiment_name: str
) -> Experiment:
    versions = _load_experiment_versions(workspace, experiment_name)

    if experiment_name not in workspace.experiments:
        raise ValueError(f"Experiment {experiment_name} not found in the workspace")

    if len(versions) == 0:
        raise ValueError(f"Experiment {experiment_name} not found in the file system")

    with open(f"{experiment_name}_{versions[0]}.json", "r") as f:
        experiment = json.load(f)

    return experiment


def _load_experiment_result(
    workspace: Workspace, experiment_name: str, version_number: int
) -> Experiment:
    if experiment_name not in workspace.experiments:
        raise ValueError(f"Experiment {experiment_name} not found in the workspace")

    if version_number not in _load_experiment_versions(workspace, experiment_name):
        raise ValueError(
            f"Version {version_number} not found for experiment {experiment_name}"
        )

    with open(f"{experiment_name}_{version_number}.json", "r") as f:
        experiment = json.load(f)

    return experiment


def _load_experiment_versions(workspace: Workspace, experiment_name: str) -> List[int]:
    versions = []
    for file in os.listdir():
        # check for files if they have the right prefix followed by a unix timestamp (int) and the file extension, e.g. experiment_123456789.json.
        # Extract the unix timestamp
        if file.startswith(f"{experiment_name}_") and file.endswith(".json"):
            segments = file.split("_")
            timestamp = int(segments[-1].split(".")[0])
            name = "_".join(segments[:-1])
            if name != experiment_name:
                # an experiment with a different name
                continue
            versions.append(timestamp)
    return sorted(versions, reverse=True)


def _save_experiment_result(
    workspace: Workspace, experiment_name: str, result: CausyResult
):
    timestamp = int(datetime.timestamp(result.created_at))
    with open(f"{experiment_name}_{timestamp}.json", "w") as f:
        f.write(json.dumps(result.model_dump(), cls=CausyJSONEncoder, indent=4))


@app.command()
def create_pipeline():
    """Create a new pipeline in the current workspace."""
    workspace = _current_workspace()
    workspace = _create_pipeline(workspace)

    workspace_path = os.path.join(os.getcwd(), WORKSPACE_FILE_NAME)
    with open(workspace_path, "w") as f:
        f.write(pydantic_yaml.to_yaml_str(workspace))


def _experiment_needs_reexecution(workspace: Workspace, experiment_name: str) -> bool:
    """
    Check if an experiment needs to be re-executed.
    :param workspace:
    :param experiment_name:
    :return:
    """
    if experiment_name not in workspace.experiments:
        raise ValueError(f"Experiment {experiment_name} not found in the workspace")

    versions = _load_experiment_versions(workspace, experiment_name)

    if len(versions) == 0:
        logger.info(f"Experiment {experiment_name} not found in the file system.")
        return True

    latest_experiment = _load_latest_experiment_result(workspace, experiment_name)
    experiment = workspace.experiments[experiment_name]
    latest_experiment = CausyResult(**latest_experiment)
    if (
        latest_experiment.algorithm_hash is None
        or latest_experiment.data_loader_hash is None
    ):
        logger.info(f"Experiment {experiment_name} has no hashes.")
        return True

    pipeline = load_algorithm_by_reference(
        workspace.pipelines[experiment.pipeline].type,
        workspace.pipelines[experiment.pipeline].reference,
    )
    model = graph_model_factory(pipeline)()
    if latest_experiment.algorithm_hash != model.algorithm.hash():
        logger.info(f"Experiment {experiment_name} has a different pipeline.")
        return True

    data_loder = load_data_loader(workspace.data_loaders[experiment.data_loader])
    if latest_experiment.data_loader_hash != data_loder.hash():
        logger.info(
            f"Experiment {experiment_name} has a different data loader/dataset."
        )
        return True

    validate_variable_values(pipeline, experiment.variables)
    variables = resolve_variables(pipeline.variables, experiment.variables)

    if latest_experiment.variables_hash != hash_dictionary(variables):
        logger.info(f"Experiment {experiment_name} has different variables.")
        return True

    return False


@app.command()
def create_experiment():
    """Create a new experiment in the current workspace."""
    workspace = _current_workspace()
    workspace = _create_experiment(workspace)

    workspace_path = os.path.join(os.getcwd(), WORKSPACE_FILE_NAME)
    with open(workspace_path, "w") as f:
        f.write(pydantic_yaml.to_yaml_str(workspace))


@app.command()
def create_data_loader():
    """Create a new data loader in the current workspace."""
    workspace = _current_workspace()
    workspace = _create_data_loader(workspace)

    workspace_path = os.path.join(os.getcwd(), WORKSPACE_FILE_NAME)
    with open(workspace_path, "w") as f:
        f.write(pydantic_yaml.to_yaml_str(workspace))


@app.command()
def info():
    """Show general information about the workspace."""
    workspace = _current_workspace()
    typer.echo(f"Workspace: {workspace.name}")
    typer.echo(f"Author: {workspace.author}")
    typer.echo(f"Pipelines: {workspace.pipelines}")
    typer.echo(f"Data loaders: {workspace.data_loaders}")
    typer.echo(f"Experiments: {workspace.experiments}")


@app.command()
def init():
    """
    Initialize a new workspace in the current directory.
    """
    workspace_path = os.path.join(os.getcwd(), WORKSPACE_FILE_NAME)

    if os.path.exists(workspace_path):
        typer.confirm(
            "Workspace already exists. Do you want to overwrite it?", abort=True
        )

    workspace = Workspace(
        **{
            "name": "",
            "author": "",
            "data_loaders": {},
            "pipelines": {},
            "experiments": {},
        }
    )

    current_folder_name = os.path.basename(os.getcwd())

    workspace.name = typer.prompt("Name", default=current_folder_name, type=str)
    workspace.author = typer.prompt(
        "Author", default=os.environ.get("USER", os.environ.get("USERNAME")), type=str
    )

    configure_pipeline = typer.confirm(
        "Do you want to configure a pipeline?", default=False
    )

    workspace.pipelines = {}
    if configure_pipeline:
        workspace = _create_pipeline(workspace)

    configure_data_loader = typer.confirm(
        "Do you want to configure a data loader?", default=False
    )

    workspace.data_loaders = {}
    if configure_data_loader:
        data_loader_type = questionary.select(
            "Do you want to use an existing pipeline or create a new one?",
            choices=[
                questionary.Choice("Load a JSON File.", "json"),
                questionary.Choice("Load a JSONL File.", "jsonl"),
                questionary.Choice(
                    "Load data dynamically (via Python Script).", "dynamic"
                ),
            ],
        ).ask()

        if data_loader_type in ["json", "jsonl"]:
            data_loader_path = questionary.path(
                "Choose the file or enter the file name:",
            ).ask()
            data_loader_name = questionary.text(
                "Enter the name of the data loader"
            ).ask()
            data_loader_slug = slugify(data_loader_name, "_")
            workspace.data_loaders[data_loader_slug] = {
                "type": data_loader_type,
                "reference": data_loader_path,
            }
        elif data_loader_type == "dynamic":
            data_loader_name = questionary.text(
                "Enter the name of the data loader"
            ).ask()
            data_loader_slug = slugify(data_loader_name, "_")
            JINJA_ENV.get_template("dataloader.py.tpl").stream(
                data_loader_name=data_loader_name
            ).dump(f"{data_loader_slug}.py")
            workspace.data_loaders[data_loader_slug] = DataLoaderReference(
                **{
                    "type": data_loader_type,
                    "reference": f"{data_loader_slug}.DataLoader",
                }
            )
    workspace.experiments = {}

    if len(workspace.pipelines) > 0 and len(workspace.data_loaders) > 0:
        configure_experiment = typer.confirm(
            "Do you want to configure an experiment?", default=False
        )

        if configure_experiment:
            workspace = _create_experiment(workspace)

    with open(workspace_path, "w") as f:
        f.write(pydantic_yaml.to_yaml_str(workspace))

    typer.echo(f"Workspace created in {workspace_path}")


@app.command()
def execute(experiment_name=None, force_reexecution=False):
    """
    Execute an experiment or all experiments in the workspace.
    :param experiment_name: name of the experiment to execute (as defined in the workspace) - if defined only this experiment will be executed
    :param force_reexecution: if True, all experiments will be re-executed regardless of there were changes or not
    :return:
    """
    workspace = _current_workspace()
    if experiment_name is None:
        # execute all experiments
        for experiment_name, experiment in workspace.experiments.items():
            if (
                not _experiment_needs_reexecution(workspace, experiment_name)
                and not force_reexecution
            ):
                typer.echo(f"Skipping experiment: {experiment_name}. (no changes)")
                continue
            typer.echo(f"Executing experiment: {experiment_name}")
            result = _execute_experiment(workspace, experiment)
            _save_experiment_result(workspace, experiment_name, result)
    else:
        if experiment_name not in workspace.experiments:
            typer.echo(f"Experiment {experiment_name} not found in the workspace.")
            return
        experiment = workspace.experiments[experiment_name]
        typer.echo(f"Executing experiment: {experiment_name}")
        result = _execute_experiment(workspace, experiment)

        _save_experiment_result(workspace, experiment_name, result)
