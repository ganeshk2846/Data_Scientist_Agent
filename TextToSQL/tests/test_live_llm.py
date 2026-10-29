import os

import pytest
from dotenv import load_dotenv

load_dotenv()

LIVE_CONFIGURED = os.getenv("RUN_LIVE_LLM_TESTS") == "1" and bool(os.getenv("LLM_API_KEY")) and bool(os.getenv("LLM_BASE_URL"))


@pytest.mark.skipif(not LIVE_CONFIGURED, reason="live LLM test is opt-in and requires LLM_API_KEY plus LLM_BASE_URL")
def test_live_llm_smoke():
    from src.llm.gateway import LLMGateway

    result = LLMGateway().chat("You are helpful.", "Say hello in one sentence.")
    assert result.text
