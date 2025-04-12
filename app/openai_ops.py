import logging
import time
from typing import Optional, Union, Dict, List, Any

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
    
    response_message = messages.data[0]
    
    # Process each content item looking for text with citations
    for content_item in response_message.content:
        if content_item.type == "text":
            text_content = content_item.text
            processed_text = process_citations(client, text_content, logger)
            return processed_text
    
    return "No text content found in the assistant's response"

def process_citations(client, text_content, logger):
    """
    Process citations in text and format them as footnotes
    """
    message_value = text_content.value
    annotations = text_content.annotations if hasattr(text_content, "annotations") else []
    
    # No annotations means no citations to process
    if not annotations:
        return message_value
    
    try:
        # Track unique file citations to avoid duplicates
        file_citations = {}
        citation_indices = {}
        
        # First pass: catalog all unique file citations
        for annotation in annotations:
            if hasattr(annotation, 'file_citation'):
                file_id = annotation.file_citation.file_id
                if file_id not in file_citations:
                    cited_file = client.files.retrieve(file_id)
                    file_citations[file_id] = cited_file.filename
                    citation_indices[file_id] = len(citation_indices) + 1
            elif hasattr(annotation, 'file_path'):
                file_id = annotation.file_path.file_id
                if file_id not in file_citations:
                    cited_file = client.files.retrieve(file_id)
                    file_citations[file_id] = cited_file.filename
                    citation_indices[file_id] = len(citation_indices) + 1
        
        # Second pass: replace annotations with citation indices
        for annotation in annotations:
            idx = None
            if hasattr(annotation, 'file_citation'):
                idx = citation_indices[annotation.file_citation.file_id]
            elif hasattr(annotation, 'file_path'):
                idx = citation_indices[annotation.file_path.file_id]
                
            if idx is not None:
                message_value = message_value.replace(annotation.text, f' [{idx}]')
        
        # Generate the unique citations list
        citations = []
        for file_id, filename in file_citations.items():
            idx = citation_indices[file_id]
            citations.append(f'[{idx}] Citation from {filename}')
        
        # Add citations if there are any
        if citations:
            message_value += '\n\n' + '\n'.join(citations)
            
    except Exception as e:
        logger.error(f"Error processing citations: {str(e)}")
        return text_content.value
        
    return message_value

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
