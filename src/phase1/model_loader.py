"""
Singleton loader for the local LLM via llama-cpp-python.
Provides generate() and safe_generate() (with retry) wrappers.
"""
from __future__ import annotations

from phase1 import config
from logger import get_logger

log = get_logger(__name__)


class ModelLoader:
    """Thread-unsafe singleton — fine for a single-process CLI tool."""

    _models = {}

    # ── Multi-Model Loader ────────────────────────────────────────────────
    @classmethod
    def load_model(cls, model_name: str, model_path: str = None):
        if model_name not in cls._models:
            from llama_cpp import Llama  # deferred import so config loads first

            # Auto-resolve path if not provided
            if not model_path:
                if getattr(config, "PHASE1_MODEL_NAME", None) == model_name:
                    model_path = config.PHASE1_MODEL_PATH
                else:
                    from phase2 import config as p2
                    if getattr(p2, "PHASE2_MODEL_NAME", None) == model_name:
                        model_path = p2.PHASE2_MODEL_PATH
                    else:
                        raise ValueError(f"Unknown model_name: {model_name}")

            log.info("Loading model: %s", model_name)
            cls._models[model_name] = Llama(
                model_path=model_path,
                n_ctx=config.MODEL_CONTEXT,
                n_threads=config.MODEL_THREADS,
                n_gpu_layers=config.MODEL_GPU_LAYERS,
                seed=config.MODEL_SEED,
                verbose=False,
            )
            log.info("Model %s ready.", model_name)
        return cls._models[model_name]

    # ── Raw generation ────────────────────────────────────────────────────
    @classmethod
    def generate_with_model(
        cls,
        model_name: str,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        model = cls.load_model(model_name)

        # Resolve top_p dynamically
        top_p = 0.9
        if getattr(config, "PHASE1_MODEL_NAME", None) == model_name:
            top_p = getattr(config, "PHASE1_TOP_P", 0.9)
        else:
            try:
                from phase2 import config as p2
                if getattr(p2, "PHASE2_MODEL_NAME", None) == model_name:
                    top_p = getattr(p2, "PHASE2_TOP_P", 0.92)
            except ImportError:
                pass

        response = model(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=1.1,
            stop=["</s>"],
        )
        return response["choices"][0]["text"].strip()

    # ── Safe generation with retry ────────────────────────────────────────
    @classmethod
    def safe_generate(
        cls,
        model_name: str,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
        retries: int = 2,
    ) -> str | None:
        """
        Generate with automatic retry on empty output or runtime errors.

        Returns the generated text on success, or None if all attempts fail.
        Callers should always check for None before using the result.
        """
        for attempt in range(retries + 1):
            try:
                result = cls.generate_with_model(
                    model_name, prompt, 
                    max_tokens=max_tokens, 
                    temperature=temperature
                )
                if result and result.strip():
                    return result.strip()
                log.warning(
                    "%s: empty output on attempt %d/%d",
                    model_name, attempt + 1, retries + 1,
                )
            except Exception as exc:
                log.warning(
                    "%s: error on attempt %d/%d: %s",
                    model_name, attempt + 1, retries + 1, exc,
                )

        log.error("%s: all %d attempts failed", model_name, retries + 1)
        return None
