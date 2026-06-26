"""
classifier.py — Identify which Windows env vars look like LLM API keys.

Three confidence levels:
  - "high"     Auto-suggest for adoption (1-click)
  - "medium"   Show in Discover with explicit user confirmation
  - "low"      Skip — likely not an LLM key

The classifier is intentionally conservative. False negatives (missing a
real LLM key) are acceptable; the user can always add it manually. False
positives (showing OneDrive as LLM key) are not acceptable.

Run standalone to see how it classifies the env vars on this machine:
    python classifier.py
"""

from __future__ import annotations

import re
import sys
from typing import Dict, List

# 24 preset template names — always high confidence
PRESET_NAMES = {
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "MISTRAL_API_KEY",
    "COHERE_API_KEY", "GROQ_API_KEY", "PERPLEXITY_API_KEY", "XAI_API_KEY",
    "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "OPENROUTER_API_KEY", "TOGETHER_API_KEY",
    "FIREWORKS_API_KEY", "REPLICATE_API_TOKEN", "HF_TOKEN",
    "ANTHROPIC_VERTEX_API_KEY", "AZURE_OPENAI_API_KEY", "AWS_BEDROCK_API_KEY",
    "ANYSCALE_API_KEY", "SILICONFLOW_API_KEY", "ARK_API_KEY", "ZHIPUAI_API_KEY",
    "QIANFAN_API_KEY", "DASHSCOPE_API_KEY",
}

# High-confidence name patterns
NAME_PATTERNS_HIGH = [
    # Generic patterns — common naming conventions
    r".*_API_KEY$",
    r".*_TOKEN$",
    r".*_API_TOKEN$",
    # Provider-specific families
    r"^HF_.*",
    r"^HUGGING.*",
    r"^ANTHROPIC.*",
    r"^OPENAI.*",
    r"^OPEN_AI.*",
    r"^GOOGLE_API.*",
    r"^GEMINI.*",
    r"^GROQ.*",
    r"^TOGETHER.*",
    r"^OPENROUTER.*",
    r"^FIREWORKS.*",
    r"^REPLICATE.*",
    r"^MISTRAL.*",
    r"^COHERE.*",
    r"^PERPLEXITY.*",
    r"^XAI.*",
    r"^DEEPSEEK.*",
    r"^MOONSHOT.*",
    r"^KIMI.*",
    r"^SILICONFLOW.*",
    r"^SILICON_.*",
    r"^ARK_.*",
    r"^VOLC_.*",
    r"^ZHIPU.*",
    r"^GLM_.*",
    r"^BIGMODEL.*",
    r"^QIANFAN.*",
    r"^WENXIN.*",
    r"^DASHSCOPE.*",
    r"^QWEN.*",
    r"^TONGYI.*",
    r"^BEDROCK.*",
    r"^ANYSCALE.*",
    r"^TOGETHER_.*",
    r"^ANYSCALE_.*",
]

# Medium-confidence name patterns — needs additional verification
NAME_PATTERNS_MEDIUM = [
    r".*_KEY$",                # Generic *_KEY (could be OneDriveKey)
    r".*_SECRET$",             # *_SECRET (could be Azure client secret)
    r".*LLM.*",                # Contains "LLM"
    r".*_LLM_.*",              # _LLM_
    r".*GPT.*",                # Contains GPT
    r".*CLAUDE.*",             # Contains Claude
    r".*GEMINI.*",
    r".*CHATGPT.*",
]

# Blacklist — these are NEVER treated as LLM keys, even if they match
EXCLUDE_PATTERNS = [
    # Microsoft / Windows / Office
    r"^ONEDRIVE.*",
    r"^OFFICE.*",
    r"^MICROSOFT.*",
    r"^MS_.*",
    r"^WINDOWS.*",
    r"^WIN_.*",
    # Azure AD / OAuth — system-managed
    r".*AZURE_.*_CLIENT_SECRET$",
    r".*AZURE_.*_CLIENT_ID$",
    r".*AZURE_.*_TENANT.*",
    r".*_BEARER_TOKEN$",
    r".*_REFRESH_TOKEN$",
    r".*_ID_TOKEN$",
    r".*_ACCESS_TOKEN$",
    r".*_SESSION_TOKEN$",
    r".*_OAUTH.*",
    # Standard Windows env vars
    r"^PATH$",
    r"^PATHEXT$",
    r"^TEMP$",
    r"^TMP$",
    r"^USERNAME$",
    r"^USERPROFILE$",
    r"^APPDATA$",
    r"^LOCALAPPDATA$",
    r"^HOMEDRIVE$",
    r"^HOMEPATH$",
    r"^OS$",
    r"^PROCESSOR.*",
    r"^SYSTEMROOT$",
    r"^WINDIR$",
    r"^PROGRAMDATA$",
    r"^PROGRAMFILES.*",
    r"^PROGRAMW6432$",
    r"^COMMONPROGRAMFILES.*",
    r"^COMSPEC$",
    r"^NUMBER_OF_PROCESSORS$",
    r"^SESSIONNAME$",
    r"^LOGONSERVER$",
    r"^USERDOMAIN.*",
    r"^DRIVERDATA$",
    r"^ALLUSERSPROFILE$",
    r"^PUBLIC$",
    r"^PSMODULEPATH$",
    r"^VSCMD_.*",
    r"^VSINSTALLDIR$",
    r"^VSLANG$",
    # Shells / build tools
    r"^CARGO_.*",
    r"^GOPATH$",
    r"^GOROOT$",
    r"^JAVA_.*",
    r"^NODE_.*",
    r"^NPM_.*",
    r"^PYTHON.*",
    r"^PIP_.*",
    r"^CONDA_.*",
    r"^VIRTUAL_ENV$",
    r"^DOCKER_.*",
    r"^KUBERNETES.*",
    r"^KUBE_.*",
    r"^AWS_.*_SESSION$",       # AWS CLI session vars (not API keys)
    r"^AWS_PROFILE$",
    r"^AWS_REGION$",
    r"^AWS_DEFAULT_.*",
    # VCS / dev
    r"^GIT_.*",
    r"^SSH_.*",
    r"^HOME$",
    r"^SHELL$",
    r"^LANG$",
    r"^LC_.*",
    r"^TERM$",
    r"^DISPLAY$",
    r"^EDITOR$",
    # App-specific stuff that's clearly not LLM
    r"^MAGICK_.*",             # ImageMagick
    r"^CHROME_.*",
    r"^FIREFOX_.*",
    r"^INTELLIJ_.*",
    r"^JETBRAINS_.*",
    r"^VSCODE_.*",
]

# Known LLM API key value prefixes
VALUE_PREFIXES = [
    "sk-",      # OpenAI, Anthropic, Many Chinese providers
    "sk_",      # Stripe-like (some LLM providers)
    "gho_",     # GitHub OAuth
    "ghp_",     # GitHub PAT
    "ghs_",     # GitHub Server
    "ghr_",     # GitHub Refresh
    "hf_",      # Hugging Face
    "pplx-",    # Perplexity
    "xai-",     # xAI (Grok)
    "ms-",      # Mistral
    "co-",      # Cohere
    "key-",     # Generic
    "gsk_",     # Groq
    "csk-",     # Cohere (new)
    "ppl-",     # Perplexity (alt)
    "r8_",      # Replicate
    "tvly-",    # Tavily
    "fc-",      # Fireworks
]


def classify(name: str, value: str) -> Dict:
    """
    Classify an env var as a potential LLM key.

    Returns:
        dict with keys:
            - confidence: "high" | "medium" | "low" | "excluded"
            - reasons: List of human-readable explanations
            - auto_adopt: True if confident enough to suggest one-click adoption
            - score: numeric score (for debugging)
    """
    reasons = []
    score = 0

    # Step 1: Blacklist — if excluded, never treat as LLM
    for pat in EXCLUDE_PATTERNS:
        if re.match(pat, name, re.IGNORECASE):
            return {
                "confidence": "excluded",
                "reasons": [f"excluded by rule: {pat}"],
                "auto_adopt": False,
                "score": -1,
            }

    # Step 2: Exact preset match — high confidence
    if name in PRESET_NAMES:
        return {
            "confidence": "high",
            "reasons": [f"matches preset template: {name}"],
            "auto_adopt": True,
            "score": 10,
        }

    # Step 3: High-confidence name patterns
    for pat in NAME_PATTERNS_HIGH:
        if re.match(pat, name, re.IGNORECASE):
            score += 2
            reasons.append(f"name matches: {pat}")
            break  # Don't double-count multiple high patterns on same name

    # Step 4: Medium-confidence name patterns
    for pat in NAME_PATTERNS_MEDIUM:
        if re.match(pat, name, re.IGNORECASE):
            score += 1
            reasons.append(f"name matches (medium): {pat}")

    # Step 5: Value prefix detection
    if value and len(value) >= 20:
        for prefix in VALUE_PREFIXES:
            if value.startswith(prefix):
                score += 2
                reasons.append(f"value has known LLM prefix: '{prefix}'")
                break

    # Step 6: Decide
    if score >= 3:
        confidence = "high"
        auto_adopt = True
    elif score >= 1:
        confidence = "medium"
        auto_adopt = False
    else:
        confidence = "low"
        auto_adopt = False
        reasons.append("no LLM-like features detected")

    return {
        "confidence": confidence,
        "reasons": reasons,
        "auto_adopt": auto_adopt,
        "score": score,
    }


def main():
    """Read the user's env vars and show classification results."""
    try:
        from env_manager import read_all_user_env
    except ImportError:
        sys.path.insert(0, ".")
        from env_manager import read_all_user_env

    env = read_all_user_env()

    # Group by confidence
    buckets = {
        "high": [],
        "medium": [],
        "low": [],
        "excluded": [],
    }

    for name, value in sorted(env.items()):
        result = classify(name, value)
        result["name"] = name
        result["value_preview"] = (value[:8] + "****" + value[-4:]) if len(value) > 12 else "****"
        result["length"] = len(value)
        buckets[result["confidence"]].append(result)

    # Print summary
    print("=" * 70)
    print(f"  LLM-Keyring Classifier — scanned {len(env)} user env vars")
    print("=" * 70)

    icons = {"high": "🟢", "medium": "🟡", "low": "⚪", "excluded": "⚫"}
    titles = {
        "high": "HIGH CONFIDENCE (auto-adoptable)",
        "medium": "MEDIUM CONFIDENCE (please verify)",
        "low": "LOW CONFIDENCE (likely not LLM)",
        "excluded": "EXCLUDED (system / non-LLM)",
    }

    for confidence in ["high", "medium", "low", "excluded"]:
        items = buckets[confidence]
        print()
        print(f"{icons[confidence]} {titles[confidence]}: {len(items)}")
        print("-" * 70)
        for item in items[:20]:  # Show first 20 per bucket
            reasons = "; ".join(item["reasons"][:2]) if item["reasons"] else ""
            print(f"  {item['name']:35s} = {item['value_preview']:18s} ({item['length']:>4d} chars)  [{reasons}]")
        if len(items) > 20:
            print(f"  ... and {len(items) - 20} more")

    print()
    print("=" * 70)
    total_llm_like = len(buckets["high"]) + len(buckets["medium"])
    print(f"  📊 Summary: {total_llm_like} LLM-like keys found "
          f"({len(buckets['high'])} high, {len(buckets['medium'])} medium)")
    print(f"           {len(buckets['low']) + len(buckets['excluded'])} non-LLM skipped")
    print("=" * 70)


if __name__ == "__main__":
    main()