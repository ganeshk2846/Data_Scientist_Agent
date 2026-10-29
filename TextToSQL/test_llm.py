"""Opt-in live smoke check. Unit tests use an injected fake client instead."""
import os


def main():
    if os.getenv("RUN_LIVE_LLM_TESTS") != "1":
        print("Skipped live LLM check; set RUN_LIVE_LLM_TESTS=1 to opt in.")
        return 0
    from src.llm.gateway import LLMGateway

    result = LLMGateway().chat("You are helpful.", "Say hello in one sentence.")
    print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
