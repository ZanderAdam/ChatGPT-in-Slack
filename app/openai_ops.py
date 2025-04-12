import logging
import time
from typing import Optional, Union

from openai import OpenAI
from openai.lib.azure import AzureOpenAI

from slack_bolt import BoltContext

def generate_assistant_response(
    *,
    context: BoltContext,
    logger: logging.Logger,
    prompt: str,
    timeout_seconds: int,
) -> str:
    client = create_openai_client(context)
    
    thread = client.beta.threads.create()
    
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=prompt,
    )
    
    assistant_id = context.get("OPENAI_ASSISTANT_ID")
    
    if assistant_id is None:
        logger.error("No assistant ID provided in context")
        return "Error: No assistant ID provided"
    
    start_time = time.time()
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant_id,
        timeout=timeout_seconds,
    )
    
    while run.status in ["queued", "in_progress"]:
        spent_seconds = time.time() - start_time
        if timeout_seconds < spent_seconds:
            raise TimeoutError()
        
        time.sleep(1)
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
    
    if run.status != "completed":
        logger.error(f"Run failed with status {run.status}")
        if run.status == "failed":
            logger.error(f"Failure reason: {run.last_error}")
        return f"Error: The operation failed with status: {run.status}"
    
    messages = client.beta.threads.messages.list(
        thread_id=thread.id,
        order="desc",
        limit=1,
    )
    
    spent_time = time.time() - start_time
    logger.debug(f"Response generation took {spent_time} seconds")
    
    if len(messages.data) == 0:
        return "No response received from the assistant"
    
    for content_item in messages.data[0].content:
        if content_item.type == "text":
            return content_item.text.value
    
    return "No text content found in the assistant's response"

def create_openai_client(context: BoltContext) -> Union[OpenAI, AzureOpenAI]:
    if context.get("OPENAI_API_TYPE") == "azure":
        return AzureOpenAI(
            api_key=context.get("OPENAI_API_KEY"),
            api_version=context.get("OPENAI_API_VERSION"),
            azure_endpoint=context.get("OPENAI_API_BASE"),
            azure_deployment=context.get("OPENAI_DEPLOYMENT_ID"),
        )
    else:
        return OpenAI(
            api_key=context.get("OPENAI_API_KEY"),
            base_url=context.get("OPENAI_API_BASE"),
        )
