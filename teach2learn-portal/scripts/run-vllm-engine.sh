#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly profile="${1:?profile name is required}"
readonly vllm_bin="${VLLM_BIN:-/data/scratch/sanyam_jain_2022/vllm-portal-env/bin/vllm}"
readonly adapter_root="${INFERENCE_ADAPTER_ROOT:-/data/scratch/sanyam_jain_2022/mistral_finetune/gemma2_s9b}"

case "$profile" in
  qwen3)
    gpu=0; port=18101; model_id="Qwen/Qwen3-8B"; cache_repo="models--Qwen--Qwen3-8B"; output="outputs_qwen3_8b_lora_no_quant"; memory=0.50 ;;
  qwen2.5)
    gpu=0; port=18105; model_id="Qwen/Qwen2.5-7B-Instruct"; cache_repo="models--Qwen--Qwen2.5-7B-Instruct"; output="outputs_qwen25_7b_lora_no_quant"; memory=0.42 ;;
  gemma2)
    gpu=1; port=18102; model_id="google/gemma-2-9b-it"; cache_repo="models--google--gemma-2-9b-it"; output="outputs_gemma2_9b_it_lora_no_quant"; memory=0.88 ;;
  mistral)
    gpu=2; port=18103; model_id="mistralai/Mistral-7B-Instruct-v0.3"; cache_repo="models--mistralai--Mistral-7B-Instruct-v0.3"; output="outputs_mistral7b_lora_no_quant"; memory=0.88 ;;
  granite)
    gpu=3; port=18104; model_id="ibm-granite/granite-3.3-8b-instruct"; cache_repo="models--ibm-granite--granite-3.3-8b-instruct"; output="outputs_granite33_8b_lora_no_quant"; memory=0.88 ;;
  *) echo "unknown profile: $profile" >&2; exit 2 ;;
esac

readonly ref_file="${HOME}/.cache/huggingface/hub/${cache_repo}/refs/main"
if [[ ! -f "$ref_file" ]]; then
  echo "missing cached model revision for ${model_id}" >&2
  exit 1
fi
IFS= read -r revision < "$ref_file" || [[ -n "$revision" ]]
readonly model="${HOME}/.cache/huggingface/hub/${cache_repo}/snapshots/${revision}"
if [[ ! -f "${model}/config.json" ]]; then
  echo "missing cached model snapshot for ${model_id}" >&2
  exit 1
fi

loras=(
  "${profile}_cp=${adapter_root}/${output}/CP_dataset/final_adapter"
  "${profile}_dsa=${adapter_root}/${output}/DSA_dataset/final_adapter"
  "${profile}_oop_java=${adapter_root}/${output}/oops_dataset/final_adapter"
  "${profile}_os=${adapter_root}/${output}/OS_dataset/final_adapter"
)

export CUDA_VISIBLE_DEVICES="$gpu"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
exec "$vllm_bin" serve "$model" \
  --host 127.0.0.1 \
  --port "$port" \
  --dtype bfloat16 \
  --gpu-memory-utilization "$memory" \
  --max-model-len 4096 \
  --max-num-seqs 16 \
  --max-num-batched-tokens 8192 \
  --performance-mode interactivity \
  --async-scheduling \
  --cudagraph-capture-sizes 1 2 4 8 16 \
  --generation-config vllm \
  --disable-uvicorn-access-log \
  --enable-prefix-caching \
  --enable-lora \
  --max-lora-rank 32 \
  --max-loras 4 \
  --max-cpu-loras 4 \
  --lora-modules "${loras[@]}"
