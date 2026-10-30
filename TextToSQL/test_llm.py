"""Opt-in live smoke check using local Ollama deepseek-r1:7b."""

import os
import sys

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except OSError:
        pass


def main():
    if os.getenv("RUN_LIVE_LLM_TESTS") != "1":
        print("Skipped live LLM check; set RUN_LIVE_LLM_TESTS=1 to opt in.")
        return 0
    from src.llm.gateway import LLMGateway

    gateway = LLMGateway(model="deepseek-r1:7b")
    result = gateway.chat("You are helpful.", "Say hello in one sentence.")
    print("Local Ollama deepseek-r1:7b response:")
    print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
