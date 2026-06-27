"""
providers.py — Provider registry for LLM-Keyring.

A central catalog of known LLM API providers. The user picks ONE of these
when binding a managed key to a provider — this binding is **persistent**,
tied to the key (not the key value), and editable via the UI.

Why a separate file?
  - Single source of truth for presets (used by Add modal, Discover, Chat)
  - Future-proof: when adding a new provider, just edit one list
  - Keeps main.py focused on HTTP/routing

Data shape per provider:
  - id:        stable internal key (matches env var convention e.g. "DEEPSEEK_API_KEY")
  - name:      user-facing display name
  - category:  International / Aggregator / Chinese
  - base_url:  default API endpoint ("" means user must provide)
  - models:    list of common model hints for this provider
"""

from __future__ import annotations

from typing import Dict, List, TypedDict


class ProviderSpec(TypedDict):
    id: str
    name: str
    category: str
    base_url: str
    models: List[str]


# All known providers. Adding a new one = add one entry here + nothing else.
PROVIDERS: List[ProviderSpec] = [
    # ============== International ==============
    {"id": "OPENAI_API_KEY",            "name": "OpenAI",                        "category": "International", "base_url": "https://api.openai.com/v1",                  "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]},
    {"id": "ANTHROPIC_API_KEY",         "name": "Anthropic (Claude)",            "category": "International", "base_url": "https://api.anthropic.com/v1",              "models": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"]},
    {"id": "GOOGLE_API_KEY",            "name": "Google Gemini",                 "category": "International", "base_url": "https://generativelanguage.googleapis.com/v1beta", "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]},
    {"id": "MISTRAL_API_KEY",           "name": "Mistral AI",                    "category": "International", "base_url": "https://api.mistral.ai/v1",                 "models": ["mistral-large-latest", "mistral-small-latest", "open-mistral-nemo"]},
    {"id": "COHERE_API_KEY",            "name": "Cohere",                        "category": "International", "base_url": "https://api.cohere.ai/v1",                  "models": ["command-r-plus", "command-r", "command-light"]},
    {"id": "GROQ_API_KEY",              "name": "Groq",                          "category": "International", "base_url": "https://api.groq.com/openai/v1",            "models": ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]},
    {"id": "PERPLEXITY_API_KEY",        "name": "Perplexity",                    "category": "International", "base_url": "https://api.perplexity.ai",                  "models": ["sonar-pro", "sonar", "llama-3.1-sonar-small-128k-online"]},
    {"id": "XAI_API_KEY",               "name": "xAI (Grok)",                    "category": "International", "base_url": "https://api.x.ai/v1",                       "models": ["grok-2", "grok-2-mini", "grok-beta"]},
    {"id": "DEEPSEEK_API_KEY",          "name": "DeepSeek",                      "category": "International", "base_url": "https://api.deepseek.com/v1",               "models": ["deepseek-chat", "deepseek-reasoner"]},
    {"id": "MOONSHOT_API_KEY",          "name": "Moonshot (Kimi)",               "category": "International", "base_url": "https://api.moonshot.cn/v1",                 "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]},
    {"id": "AGNES_API_KEY",             "name": "Agnes AI (新加坡全模态,免费)",      "category": "International", "base_url": "https://apihub.agnes-ai.com/v1",            "models": ["agnes-2.0-flash", "agnes-1.5-flash"]},

    # ============== Aggregator ==============
    {"id": "OPENROUTER_API_KEY",        "name": "OpenRouter",                    "category": "Aggregator",    "base_url": "https://openrouter.ai/api/v1",              "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.1-70b-instruct"]},
    {"id": "TOGETHER_API_KEY",          "name": "Together AI",                   "category": "Aggregator",    "base_url": "https://api.together.xyz/v1",               "models": ["meta-llama/Llama-3.1-70B-Instruct-Turbo", "Qwen/Qwen2.5-72B-Instruct-Turbo"]},
    {"id": "FIREWORKS_API_KEY",         "name": "Fireworks AI",                  "category": "Aggregator",    "base_url": "https://api.fireworks.ai/inference/v1",    "models": ["accounts/fireworks/models/llama-v3p1-70b-instruct", "accounts/fireworks/models/mixtral-8x7b-instruct"]},
    {"id": "REPLICATE_API_TOKEN",       "name": "Replicate",                     "category": "Aggregator",    "base_url": "https://api.replicate.com/v1",              "models": []},
    {"id": "HF_TOKEN",                  "name": "Hugging Face Hub",              "category": "Aggregator",    "base_url": "https://router.huggingface.co/v1",         "models": ["meta-llama/Llama-3.1-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"]},
    {"id": "ANTHROPIC_VERTEX_API_KEY",  "name": "Vertex AI (Claude)",            "category": "Aggregator",    "base_url": "https://us-central1-aiplatform.googleapis.com/v1", "models": ["claude-3-5-sonnet@20240620", "claude-3-opus@20240229"]},
    {"id": "AZURE_OPENAI_API_KEY",      "name": "Azure OpenAI",                  "category": "Aggregator",    "base_url": "",                                            "models": []},  # user must provide
    {"id": "AWS_BEDROCK_API_KEY",       "name": "AWS Bedrock",                   "category": "Aggregator",    "base_url": "",                                            "models": []},  # user must provide
    {"id": "ANYSCALE_API_KEY",          "name": "Anyscale Endpoints",            "category": "Aggregator",    "base_url": "https://api.endpoints.anyscale.com/v1",     "models": ["meta-llama/Llama-3-70b-chat-hf", "mistralai/Mistral-7B-Instruct-v0.1"]},

    # ============== Chinese ==============
    {"id": "SILICONFLOW_API_KEY",       "name": "硅基流动 (SiliconFlow)",        "category": "Chinese",       "base_url": "https://api.siliconflow.cn/v1",             "models": ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3", "Pro/Qwen/Qwen2-7B-Instruct"]},
    {"id": "ARK_API_KEY",               "name": "火山方舟 (Ark) / Coding Plan",  "category": "Chinese",       "base_url": "https://ark.cn-beijing.volces.com/api/v3", "models": ["doubao-pro-32k", "doubao-lite-32k"]},
    {"id": "ZHIPUAI_API_KEY",           "name": "智谱 BigModel",                 "category": "Chinese",       "base_url": "https://open.bigmodel.cn/api/paas/v4",     "models": ["glm-4-plus", "glm-4-flash", "glm-4"]},
    {"id": "QIANFAN_API_KEY",           "name": "百度千帆",                       "category": "Chinese",       "base_url": "https://qianfan.baidubce.com/v2",          "models": ["ernie-4.0-8k", "ernie-3.5-8k", "ernie-speed-8k"]},
    {"id": "DASHSCOPE_API_KEY",         "name": "阿里 DashScope (通义千问)",      "category": "Chinese",       "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "models": ["qwen-plus", "qwen-turbo", "qwen-max"]},

    # ============== MiniMax M3 (Token Plan) ==============
    # Note: MiniMax M3 is the MiniMax M-series model family. The
    # Token Plan SK prefix routes to api.minimax.io, but the user
    # (in real usage) uses api.minimaxi.com/v1 with the sk-cp- prefix.
    # Added here as a separate preset since the user uses it heavily.
    {"id": "MINIMAX_API_KEY",           "name": "MiniMax M3",                    "category": "Chinese",       "base_url": "https://api.minimaxi.com/v1",              "models": ["MiniMax-Text-01", "MiniMax-VL-01", "speech-01", "music-01"]},
]


def get_provider_by_id(provider_id: str) -> ProviderSpec | None:
    """Look up a provider by its id (e.g. 'DEEPSEEK_API_KEY'). Returns None if not found."""
    for p in PROVIDERS:
        if p["id"] == provider_id:
            return p
    return None


def get_providers_by_category() -> Dict[str, List[ProviderSpec]]:
    """Group providers by category for UI rendering."""
    grouped: Dict[str, List[ProviderSpec]] = {"International": [], "Aggregator": [], "Chinese": []}
    for p in PROVIDERS:
        grouped.setdefault(p["category"], []).append(p)
    return grouped