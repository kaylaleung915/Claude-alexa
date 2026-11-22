#!/usr/bin/env python3
"""Try the skill on your computer before deploying.

    pip install -r lambda/requirements.txt
    ANTHROPIC_API_KEY=sk-ant-... python3 test_lambda.py "why is the sky blue?"
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lambda"))
from lambda_function import lambda_handler  # noqa: E402


def alexa_request(query, attributes=None):
    return {
        "version": "1.0",
        "session": {
            "new": False,
            "sessionId": "test-session",
            "application": {"applicationId": "test-app"},
            "attributes": attributes or {},
            "user": {"userId": "test-user"},
        },
        "context": {"System": {
            "application": {"applicationId": "test-app"},
            "user": {"userId": "test-user"},
            "device": {"deviceId": "test-device", "supportedInterfaces": {}},
        }},
        "request": {
            "type": "IntentRequest",
            "requestId": "test-request",
            "timestamp": "2026-01-01T00:00:00Z",
            "locale": "en-US",
            "intent": {
                "name": "ClaudeQueryIntent",
                "confirmationStatus": "NONE",
                "slots": {"query": {"name": "query", "value": query, "confirmationStatus": "NONE"}},
            },
        },
    }


if __name__ == "__main__":
    questions = sys.argv[1:] or ["who are you?", "say that again but shorter"]
    attrs = {}
    for q in questions:
        out = lambda_handler(alexa_request(q, attrs), {})
        ssml = out["response"]["outputSpeech"]["ssml"]
        print(f"You:    {q}")
        print(f"Alexa:  {re.sub(r'<[^>]+>', '', ssml)}\n")
        attrs = out.get("sessionAttributes", {})
