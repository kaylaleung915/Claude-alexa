"""Alexa skill that answers with Claude (Anthropic API).

Based on k4l1sh/alexa-gpt (MIT), rewritten to call Anthropic instead of OpenAI.
"""
import logging
import os
import re
from xml.sax.saxutils import escape

import requests
import ask_sdk_core.utils as ask_utils
from ask_sdk_core.dispatch_components import AbstractExceptionHandler, AbstractRequestHandler
from ask_sdk_core.skill_builder import SkillBuilder

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
# Paste your Anthropic API key here (from https://console.anthropic.com/settings/keys),
# or set an ANTHROPIC_API_KEY environment variable if you host this on your own Lambda.
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY")

# Haiku is the fastest Claude model, which matters because Alexa gives up after ~8 seconds.
# Swap in "claude-sonnet-5-5" for smarter (but slower, pricier) answers.
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")

SYSTEM_PROMPT = (
    "You are Claude, talking to someone through an Amazon Echo speaker. "
    "Your answer will be read aloud, so reply in plain spoken sentences: no markdown, "
    "no bullet points, no headings, no emojis, no links. "
    "Keep it short, ideally under 60 words, unless the person asks for more detail."
)

MAX_TOKENS = 400
HISTORY_TURNS = 10      # how many past question/answer pairs to send back to Claude
TIMEOUT_SECONDS = 7     # stay under Alexa's ~8 second limit

API_URL = "https://api.anthropic.com/v1/messages"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------
def ask_claude(chat_history, question):
    """Send the conversation to Claude and return its reply as plain text."""
    messages = []
    for past_q, past_a in chat_history[-HISTORY_TURNS:]:
        messages.append({"role": "user", "content": past_q})
        messages.append({"role": "assistant", "content": past_a})
    messages.append({"role": "user", "content": question})

    try:
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": SYSTEM_PROMPT,
                "messages": messages,
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        return "Sorry, Claude took too long to answer. Try asking a shorter question."
    except requests.RequestException as e:
        logger.error("Request to Anthropic failed: %s", e)
        return "Sorry, I couldn't reach Claude right now."

    if resp.status_code == 401:
        return "Your Anthropic API key isn't working. Check the key in the skill's code."
    if not resp.ok:
        logger.error("Anthropic API error %s: %s", resp.status_code, resp.text)
        return f"Sorry, Claude returned an error, code {resp.status_code}."

    data = resp.json()
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    return text.strip() or "Sorry, I didn't get an answer back."


def to_speech(text):
    """Strip leftover markdown and escape characters that would break Alexa's SSML."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)   # code blocks
    text = re.sub(r"[*_#`>]+", "", text)                 # markdown symbols
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [link](url) -> link
    text = re.sub(r"\s+", " ", text).strip()
    return escape(text)  # & < > would otherwise make Alexa reject the response


# ---------------------------------------------------------------------------
# Alexa handlers
# ---------------------------------------------------------------------------
class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        handler_input.attributes_manager.session_attributes["chat_history"] = []
        speak = "Claude is listening. What would you like to ask?"
        return handler_input.response_builder.speak(speak).ask("What would you like to ask?").response


class ClaudeQueryIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("ClaudeQueryIntent")(handler_input)

    def handle(self, handler_input):
        slots = handler_input.request_envelope.request.intent.slots or {}
        query = slots["query"].value if "query" in slots else None
        if not query:
            return (handler_input.response_builder
                    .speak("Sorry, I didn't catch that. What's your question?")
                    .ask("What's your question?").response)

        session = handler_input.attributes_manager.session_attributes
        history = [tuple(pair) for pair in session.get("chat_history", [])]

        answer = ask_claude(history, query)
        history.append((query, answer))
        session["chat_history"] = history[-HISTORY_TURNS:]

        return (handler_input.response_builder
                .speak(to_speech(answer))
                .ask("Anything else? Or say stop to finish.").response)


class ClearContextIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("ClearContextIntent")(handler_input)

    def handle(self, handler_input):
        handler_input.attributes_manager.session_attributes["chat_history"] = []
        speak = "Okay, I've cleared our conversation. What would you like to talk about?"
        return handler_input.response_builder.speak(speak).ask(speak).response


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        speak = ("Just ask me anything and Claude will answer. "
                 "Say start over to clear the conversation, or stop to leave.")
        return handler_input.response_builder.speak(speak).ask("What would you like to ask?").response


class CancelOrStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input)
                or ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        return handler_input.response_builder.speak("Goodbye.").set_should_end_session(True).response


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.error(exception, exc_info=True)
        speak = "Sorry, something went wrong. Please try again."
        return handler_input.response_builder.speak(speak).ask(speak).response


sb = SkillBuilder()
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(ClaudeQueryIntentHandler())
sb.add_request_handler(ClearContextIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
