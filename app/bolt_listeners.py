import json
import logging
import re
from slack_bolt import App, Ack, BoltContext, BoltResponse
from slack_bolt.request.payload_utils import is_event
from slack_sdk.web import WebClient

from app.env import OPENAI_TIMEOUT_SECONDS, SYSTEM_TEXT
from app.openai_ops import generate_assistant_response
from app.slack_constants import DEFAULT_LOADING_TEXT, TIMEOUT_ERROR_MESSAGE
from app.slack_ops import (
    find_parent_message,
    is_this_app_mentioned,
    post_wip_message,
)
from app.sensitive_info_redaction import redact_string

from openai import APITimeoutError

def just_ack(ack: Ack):
    ack()

def respond_to_app_mention(
    context: BoltContext,
    payload: dict,
    client: WebClient,
    logger: logging.Logger,
):
    thread_ts = payload.get("thread_ts")
    if thread_ts is not None:
        parent_message = find_parent_message(client, context.channel_id, thread_ts)
        if parent_message is not None and is_this_app_mentioned(
            context, parent_message
        ):
            return

    wip_reply = None
    openai_api_key = context.get("OPENAI_API_KEY")
    try:
        if openai_api_key is None:
            client.chat_postMessage(
                channel=context.channel_id,
                text="To use this app, please configure your OpenAI API key first",
            )
            return

        user_id = context.actor_user_id or context.user_id
        msg_text = re.sub(f"<@{context.bot_user_id}>\\s*", "", payload["text"])
        msg_text = redact_string(msg_text)
        
        wip_reply = post_wip_message(
            client=client,
            channel=context.channel_id,
            thread_ts=payload["ts"],
            loading_text=DEFAULT_LOADING_TEXT,
            messages=[{"role": "system", "content": SYSTEM_TEXT}],
            user=context.user_id,
        )
        
        response = generate_assistant_response(
            context=context,
            logger=logger,
            prompt=msg_text,
            timeout_seconds=OPENAI_TIMEOUT_SECONDS,
        )
        
        client.chat_update(
            channel=context.channel_id,
            ts=wip_reply["message"]["ts"],
            text=response,
        )

    except (APITimeoutError, TimeoutError):
        if wip_reply is not None:
            text = (
                (
                    wip_reply.get("message", {}).get("text", "")
                    if wip_reply is not None
                    else ""
                )
                + "\n\n"
                + TIMEOUT_ERROR_MESSAGE
            )
            client.chat_update(
                channel=context.channel_id,
                ts=wip_reply["message"]["ts"],
                text=text,
            )
    except Exception as e:
        text = (
            (
                wip_reply.get("message", {}).get("text", "")
                if wip_reply is not None
                else ""
            )
            + "\n\n"
            + f":warning: Failed to start a conversation with ChatGPT: {e}"
        )
        logger.exception(text, e)
        if wip_reply is not None:
            client.chat_update(
                channel=context.channel_id,
                ts=wip_reply["message"]["ts"],
                text=text,
            )

def respond_to_new_message(
    context: BoltContext,
    payload: dict,
    client: WebClient,
    logger: logging.Logger,
):
    if payload.get("bot_id") is not None and payload.get("bot_id") != context.bot_id:
        return

    openai_api_key = context.get("OPENAI_API_KEY")
    if openai_api_key is None:
        return

    wip_reply = None
    try:
        is_in_dm_with_bot = payload.get("channel_type") == "im"
        is_thread_for_this_app = False
        thread_ts = payload.get("thread_ts")
        if is_in_dm_with_bot is False and thread_ts is None:
            return

        if is_in_dm_with_bot is True and thread_ts is None:
            is_thread_for_this_app = True
        else:
            messages_in_context = client.conversations_replies(
                channel=context.channel_id,
                ts=thread_ts,
                include_all_metadata=True,
                limit=1000,
            ).get("messages", [])
            if is_in_dm_with_bot is True:
                is_thread_for_this_app = True
            else:
                the_parent_message_found = False
                for message in messages_in_context:
                    if message.get("ts") == thread_ts:
                        the_parent_message_found = True
                        is_thread_for_this_app = is_this_app_mentioned(context, message)
                        break
                if the_parent_message_found is False:
                    parent_message = find_parent_message(
                        client, context.channel_id, thread_ts
                    )
                    if parent_message is not None:
                        is_thread_for_this_app = is_this_app_mentioned(
                            context, parent_message
                        )

        if is_thread_for_this_app is False:
            return

        msg_text = redact_string(payload.get("text", ""))
        
        wip_reply = post_wip_message(
            client=client,
            channel=context.channel_id,
            thread_ts=thread_ts if thread_ts else payload["ts"],
            loading_text=DEFAULT_LOADING_TEXT,
            messages=[{"role": "system", "content": SYSTEM_TEXT}],
            user=context.actor_user_id or context.user_id,
        )

        response = generate_assistant_response(
            context=context,
            logger=logger,
            prompt=msg_text,
            timeout_seconds=OPENAI_TIMEOUT_SECONDS,
        )
        
        client.chat_update(
            channel=context.channel_id,
            ts=wip_reply["message"]["ts"],
            text=response,
        )

    except (APITimeoutError, TimeoutError):
        if wip_reply is not None:
            text = (
                (
                    wip_reply.get("message", {}).get("text", "")
                    if wip_reply is not None
                    else ""
                )
                + "\n\n"
                + TIMEOUT_ERROR_MESSAGE
            )
            client.chat_update(
                channel=context.channel_id,
                ts=wip_reply["message"]["ts"],
                text=text,
            )
    except Exception as e:
        text = (
            (
                wip_reply.get("message", {}).get("text", "")
                if wip_reply is not None
                else ""
            )
            + "\n\n"
            + f":warning: Failed to reply: {e}"
        )
        logger.exception(text, e)
        if wip_reply is not None:
            client.chat_update(
                channel=context.channel_id,
                ts=wip_reply["message"]["ts"],
                text=text,
            )

def register_listeners(app: App):
    app.event("app_mention")(ack=just_ack, lazy=[respond_to_app_mention])
    app.event("message")(ack=just_ack, lazy=[respond_to_new_message])

MESSAGE_SUBTYPES_TO_SKIP = ["message_changed", "message_deleted"]

def before_authorize(
    body: dict,
    payload: dict,
    logger: logging.Logger,
    next_,
):
    if (
        is_event(body)
        and payload.get("type") == "message"
        and payload.get("subtype") in MESSAGE_SUBTYPES_TO_SKIP
    ):
        logger.debug(
            "Skipped the following middleware and listeners "
            f"for this message event (subtype: {payload.get('subtype')})"
        )
        return BoltResponse(status=200, body="")
    next_()
