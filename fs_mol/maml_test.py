#!/usr/bin/env python3
import contextlib
import json
import logging
import os
import pickle
import sys
from pathlib import Path

import tensorflow as tf
from dpu_utils.utils import run_and_debug

from tf2_gnn.cli_utils.model_utils import load_weights_verbosely

from pyreporoot import project_root

sys.path.insert(0, str(project_root(Path(__file__), root_files="requirements.txt")))


from metamol.data import DataFold
from metamol.maml_train import VALIDATION_MODEL_DEFAULT_HYPER_PARAMS
from metamol.models.split_lr_graph_binary_classification import SplitLRGraphBinaryClassificationTask
from metamol.utils.logging import FileLikeLogger
from metamol.utils.maml_data_utils import MetamolStubGraphDataset
from metamol.utils.maml_train_utils import eval_model_by_finetuning_on_task
from metamol.utils.test_utils import add_eval_cli_args, set_up_test_run, write_csv_summary


logger = logging.getLogger(__name__)


def load_model_for_eval(args):
    # Load the model parameters if there is a model to load
    if args.trained_model:
        with open(args.trained_model, "rb") as in_file:
            data_to_load = pickle.load(in_file)
            # Check whether model to load matches the type we are training
            if data_to_load["model_class"] is SplitLRGraphBinaryClassificationTask:
                model_cls = data_to_load["model_class"]
                model_params = data_to_load["model_params"]
            else:
                # initialise a new one
                model_cls = SplitLRGraphBinaryClassificationTask
                model_params = model_cls.get_default_hyperparameters("GNN_Edge_MLP")
                model_params.update(data_to_load["model_params"])
                model_params.update(VALIDATION_MODEL_DEFAULT_HYPER_PARAMS)
    else:
        model_cls = SplitLRGraphBinaryClassificationTask
        model_params = model_cls.get_default_hyperparameters("GNN_Edge_MLP")
        model_params.update(VALIDATION_MODEL_DEFAULT_HYPER_PARAMS)
    model_params.update(args.model_params_override or {})

    # Create the model:
    stub_graph_dataset = MetamolStubGraphDataset()
    model = model_cls(model_params, dataset=stub_graph_dataset)
    data_description = stub_graph_dataset.get_batch_tf_data_description()
    model.build(data_description.batch_features_shapes)

    # Load other parameters where possible, but supersede with use fresh init flag:
    if args.use_fresh_param_init and args.trained_model:
        logger.info("Using fresh model init.")
    elif args.trained_model:
        logger.info(f"Using model weights loaded from {args.trained_model}.")
        with contextlib.redirect_stdout(FileLikeLogger(logger, logging.INFO)):
            load_weights_verbosely(args.trained_model, model)

    return model


def run_from_args(args) -> None:
    out_dir, dataset = set_up_test_run("MAML", args, tf=True)

    model = load_model_for_eval(args)
    base_model_weights = {var.name: var.value() for var in model.trainable_variables}

    for task in dataset.get_task_reading_iterable(DataFold.TEST):
        _, test_results = eval_model_by_finetuning_on_task(
            model,
            base_model_weights,
            task,
            train_set_sample_sizes=args.train_sizes,
            test_set_size=None,
            num_samples=args.num_runs,
            max_num_nodes_in_batch=10000,
            metric_to_use="avg_precision",
            seed=args.seed,
            quiet=True,
        )

        write_csv_summary(os.path.join(out_dir, f"{task.name}_eval_results.csv"), test_results)


def run():
    import argparse

    parser = argparse.ArgumentParser(
        description="Test finetuning a MAML GNN model on tasks, or run with a fresh model.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    add_eval_cli_args(parser)

    parser.add_argument(
        "--trained-model",
        type=str,
        help=(
            "File to load model from (determines model architecture & task). If this is None,"
            " a fresh model will be initialised and trained from scratch."
            " If the model type does not match SplitLRGraphBinaryClassificationTask,"
            " will load as many parameters as possible."
        ),
    )

    parser.add_argument(
        "--use-fresh-param-init",
        action="store_true",
        help="Do not use trained weights, but start from a fresh, random initialisation.",
    )

    parser.add_argument(
        "--model-params-override",
        type=lambda s: json.loads(s),
        help="JSON dictionary overriding model hyperparameter values.",
    )

    parser.add_argument("--debug", dest="debug", action="store_true", help="Enable debug routines")
    args = parser.parse_args()

    # Shut up tensorflow:
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "1"
    tf.get_logger().setLevel("ERROR")
    import warnings

    warnings.simplefilter("ignore")

    run_and_debug(lambda: run_from_args(args), args.debug)


if __name__ == "__main__":
    run()
