import torch


torch.set_float32_matmul_precision("high")

import argparse  # noqa: E402
import sys  # noqa: E402

from diffusers import DiffusionPipeline  # noqa: E402


sys.path.append(".")

CKPT_ID = "stabilityai/stable-diffusion-xl-base-1.0"
PROMPT = "ghibli style, a fantasy landscape with castles"


def load_pipeline(args):
    pipe = DiffusionPipeline.from_pretrained(CKPT_ID, torch_dtype=torch.float16, use_safetensors=True)
    pipe = pipe.to("cuda")

    if args.run_compile:
        pipe.unet.to(memory_format=torch.channels_last)
        print("Run torch compile")

        if args.compile_mode == "max-autotune" and args.change_comp_config:
            torch._inductor.config.conv_1x1_as_mm = True
            torch._inductor.config.coordinate_descent_tuning = True

        if args.do_quant:
            from torchao.quantization import quant_api

            torch._inductor.config.force_fuse_int_mm_with_mul = True
            quant_api.change_linear_weights_to_int8_dqtensors(pipe.unet)

        pipe.unet = torch.compile(pipe.unet, mode=args.compile_mode, fullgraph=True)

    pipe.set_progress_bar_config(disable=True)
    return pipe


def run_inference(pipe, args):
    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA], record_shapes=True
    ) as prof:
        _ = pipe(
            prompt=PROMPT,
            num_inference_steps=args.num_inference_steps,
            num_images_per_prompt=args.batch_size,
        )

    path = (
        CKPT_ID.replace("/", "_")
        + f"-bs@{args.batch_size}-steps@{args.num_inference_steps}-compile@{args.run_compile}-mode@{args.compile_mode}-change_comp_config@{args.change_comp_config}-do_quant@{args.do_quant}.json"
    )
    prof.export_chrome_trace(path)
    return path


def main(args) -> dict:
    pipeline = load_pipeline(args)
    trace_path = run_inference(pipeline, args)
    return trace_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch_size", type=int, default=1)
    parser.add_argument("--num_inference_steps", type=int, default=30)
    parser.add_argument("--run_compile", action="store_true")
    parser.add_argument(
        "--compile_mode", type=str, default="reduce-overhead", choices=["reduce-overhead", "max-autotune"]
    )
    parser.add_argument("--change_comp_config", action="store_true")
    parser.add_argument("--do_quant", action="store_true")
    args = parser.parse_args()

    if not args.run_compile:
        args.compile_mode = "NA"

    trace_path = main(args)
    print(f"Trace generated at: {trace_path}")