"""Modal deployment — vLLM serving Mistral Small 3.1 (24B) with OpenAI-compatible API.

Deploy:
    modal deploy infra/modal_app.py

After deployment, set in your .env:
    MODAL_ENDPOINT_URL=https://<workspace>--vllm-inference-serve.modal.run/v1

The endpoint is OpenAI-compatible so the app's ``llm.py`` module connects
with ``openai.AsyncOpenAI(base_url=..., api_key="modal")``.
"""

import subprocess

import modal

MODEL_NAME = "Qwen/Qwen3-8B"
SERVED_MODEL_NAME = "Qwen/Qwen3-8B"
N_GPU = 1
VLLM_PORT = 8000
MINUTES = 60

vllm_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12"
    )
    .entrypoint([])
    .pip_install(
        "vllm>=0.6.0",
        "huggingface-hub",
    )
)

hf_cache_vol = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name("vllm-cache", create_if_missing=True)

app = modal.App("vllm-inference")


@app.function(
    image=vllm_image,
    gpu=f"L4:{N_GPU}",
    scaledown_window=5 * MINUTES,
    timeout=10 * MINUTES,
    volumes={
        "/root/.cache/huggingface": hf_cache_vol,
        "/root/.cache/vllm": vllm_cache_vol,
    },
)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=VLLM_PORT, startup_timeout=10 * MINUTES)
def serve():
    cmd = [
        "vllm",
        "serve",
        MODEL_NAME,
        "--served-model-name",
        SERVED_MODEL_NAME,
        "--host",
        "0.0.0.0",  # noqa: S104 — must bind all interfaces inside Modal container
        "--port",
        str(VLLM_PORT),
        "--tensor-parallel-size",
        str(N_GPU),
        "--max-model-len",
        "8192",
        "--enforce-eager",  # faster cold starts
        "--uvicorn-log-level=info",
    ]
    subprocess.Popen(cmd)  # noqa: S603
