import os
import argparse

import torch
import firedrake as fd

from functools import partial
from tqdm.auto import tqdm

from models.autoencoder import EncoderDecoder
from models.cnn import CNN
from training.utils import TrainingConfig, get_logger
from dataset_processing.load_data import load_dataset


logger = get_logger("Evaluation")

fd_backend = fd.get_backend()

def evaluate(model, config, data, disable_tqdm=False):

    model.eval()

    eval_steps = min(len(data), config.max_eval_steps)
    total_error = 0.0
	compute_error = partial(eval_error, evaluation_metric=config.evaluation_metric)
    for step_num, batch in tqdm(enumerate(data[:eval_steps]), total=eval_steps, disable=disable_tqdm):

        # TODO: Add device to batch
        # Convert to PyTorch tensors
        k_exact, u_obs = batch
        u_obs = fd_backend.to_ml_backend(u_obs)

        with torch.no_grad():
            kP = model(u_obs)
            kF = fd_backend.from_ml_backend(kP, k_exact.function_space())
            total_error += compute_error(kF, k_exact)

    total_error /= eval_steps
    return total_error


def eval_error(x, x_exact, evaluation_metric):
    if evaluation_metric == 'avg_rel':
        # Compute relative L2-error: ||x - x_exact||_{L2}^{2} / ||x_exact||_{L2}^{2}
        return fd.assemble((x - x_exact)** 2 * fd.dx)/fd.assemble(x_exact** 2 * fd.dx)
    return fd.norm(x - x_exact, norm_type=evaluation_metric)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resources_dir", default="../data", type=str, help="Resources directory")
    parser.add_argument("--model", default="cnn", type=str, help="one of [encoder-decoder, cnn]")
    parser.add_argument("--model_dir", default="model", type=str, help="Directory name to load the model from")
    parser.add_argument("--model_version", default="", type=str, help="Saved model version to load (e.g. for a specific checkpoint)")
    parser.add_argument("--max_eval_steps", default=5000, type=int, help="Maximum number of evaluation steps")
    parser.add_argument("--evaluation_metric", default="L2", type=str, help="Evaluation metric: one of [Lp, H1, Hdiv, Hcurl, avg_rel]")
    parser.add_argument("--dataset", default="poisson", type=str, help="Dataset name")
    parser.add_argument("--device", default="cpu", type=str, help="Device identifier (e.g. 'cuda:0' or 'cpu')")
    parser.add_argument("--eval_set", default="test", type=str, help="Dataset split to evaluate on")

    args = parser.parse_args()
    config = TrainingConfig(**dict(args._get_kwargs()))

    # Load dataset
    data_dir = os.path.join(args.resources_dir, "datasets", args.dataset)
    logger.info(f"Loading dataset from {data_dir}\n")
    _, data = load_dataset(config, args.eval_set)

    # Load model
    model_dir = os.path.join(args.resources_dir, "saved_models", args.model_dir, args.model_version)

    logger.info(f"Loading model checkpoint from {model_dir}\n")
    if args.model == "encoder-decoder":
        model = EncoderDecoder.from_pretrained(model_dir)
    elif args.model == "cnn":
        model = CNN.from_pretrained(model_dir)
    # Set double precision (default Firedrake type)
    model.double()

    error, k_learned = evaluate(model, config, data)
    logger.info(f"\n\t Error (metric: {config.evaluation_metric}): {error:.4e}")

