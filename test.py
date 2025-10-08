"""Test script to extract supported models from litellm."""

import json

import litellm


# Below providers do not maintain a model list with litellm
SKIP_PROVIDERS = {"ollama", "ollama_chat"}
result = []

for provider in sorted([p.value for p in litellm.provider_list]):
    models = []
    if provider not in SKIP_PROVIDERS:
        for model in litellm.models_by_provider.get(provider, []):
            try:
                details = litellm.get_model_info(model)
                if provider == "openai":
                    API_BASE = "https://api.openai.com/v1"
                else:
                    provider_info = litellm.get_llm_provider(model)
                    API_BASE = provider_info[3] if len(provider_info) > 3 and provider_info[3] else None

                model_entry = {k: v for k, v in details.items() if v is not None}
                if API_BASE:
                    model_entry["api_base"] = API_BASE

                models.append(model_entry)
            except Exception:  # pylint: disable=broad-exception-caught
                models.append({"key": model})

    result.append({"provider": provider, "models": models})

print(json.dumps(result, indent=2))

# Print distinct "mode" values
modes = set()
for item in result:
    for model in item["models"]:
        if "mode" in model:
            modes.add(model["mode"])

print(f"\nDistinct mode values: {sorted(modes)}")
