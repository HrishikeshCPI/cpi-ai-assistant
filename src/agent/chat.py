"""
Gemini-powered chat agent for CPI integration queries.
Uses manual tool declarations and manual function calling with Neo4j-backed tools.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from src.agent import tools

# Load .env file
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY not found in .env file. "
        "Please add: GEMINI_API_KEY=your_key_here"
    )

# Initialize Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

# System instruction for the agent
SYSTEM_INSTRUCTION = (
    "You are a CPI integration assistant. Answer questions about SAP Cloud Platform "
    "Integration iFlows, resources, and systems using the available tools. "
    "Answer only using tool results. If a tool returns empty or not found, say so clearly "
    "- don't guess or make up information. Be concise and technical. "
    "IMPORTANT: For each question, call the appropriate tool to get fresh data. "
    "Do not reuse data from earlier in the conversation unless the question is clearly "
    "a follow-up about the same specific iFlow or resource already named by the user in that follow-up."
)


# Manually define tool schemas (avoiding parameterized generic type hints)
TOOLS = [
    genai.types.Tool(
        function_declarations=[
            genai.types.FunctionDeclaration(
                name="find_iflows_using_resource",
                description="Find all iFlows that use a specific resource file",
                parameters=genai.types.Schema(
                    type="object",
                    properties={
                        "filename": genai.types.Schema(
                            type="string",
                            description="The name of the resource file (e.g., script1.groovy, MM_Convert.mmap)",
                        )
                    },
                    required=["filename"],
                ),
            ),
            genai.types.FunctionDeclaration(
                name="get_resource_detail",
                description="Get detailed information about a specific resource file",
                parameters=genai.types.Schema(
                    type="object",
                    properties={
                        "filename": genai.types.Schema(
                            type="string",
                            description="The name of the resource file (e.g., script1.groovy, MM_Convert.mmap)",
                        )
                    },
                    required=["filename"],
                ),
            ),
            genai.types.FunctionDeclaration(
                name="describe_iflow",
                description="Describe a specific iFlow integration, including its structure and resources",
                parameters=genai.types.Schema(
                    type="object",
                    properties={
                        "artifact_id": genai.types.Schema(
                            type="string",
                            description="The artifact ID of the iFlow (e.g., NorthWind_Customer_OData_Git)",
                        )
                    },
                    required=["artifact_id"],
                ),
            ),
            genai.types.FunctionDeclaration(
                name="get_iflow_diagram",
                description="Return a Mermaid flowchart diagram for an iFlow, showing steps, resources, and system connections",
                parameters=genai.types.Schema(
                    type="object",
                    properties={
                        "artifact_id": genai.types.Schema(
                            type="string",
                            description="The artifact ID of the iFlow (e.g., NorthWind_Customer_OData_Git)",
                        )
                    },
                    required=["artifact_id"],
                ),
            ),
            genai.types.FunctionDeclaration(
                name="get_iflow_systems",
                description="Get a list of external systems that an iFlow connects to",
                parameters=genai.types.Schema(
                    type="object",
                    properties={
                        "artifact_id": genai.types.Schema(
                            type="string",
                            description="The artifact ID of the iFlow (e.g., NorthWind_Customer_OData_Git)",
                        )
                    },
                    required=["artifact_id"],
                ),
            ),
            genai.types.FunctionDeclaration(
                name="list_all_iflows",
                description="List all iFlows in the graph with their IDs and versions",
                parameters=genai.types.Schema(
                    type="object",
                    properties={},
                    required=[],
                ),
            ),
            genai.types.FunctionDeclaration(
                name="find_iflows_by_protocol",
                description="Find all iFlows that use a specific communication protocol or component type",
                parameters=genai.types.Schema(
                    type="object",
                    properties={
                        "protocol": genai.types.Schema(
                            type="string",
                            description="The protocol or component type (e.g., SOAP, HTTP, OData, JMS)",
                        )
                    },
                    required=["protocol"],
                ),
            ),
            genai.types.FunctionDeclaration(
                name="find_resources_by_complexity",
                description="List resources (scripts/mappings) matching a complexity level",
                parameters=genai.types.Schema(
                    type="object",
                    properties={
                        "complexity": genai.types.Schema(
                            type="string",
                            description="Complexity level: 'trivial', 'moderate', or 'business-logic'",
                        )
                    },
                    required=["complexity"],
                ),
            ),
            genai.types.FunctionDeclaration(
                name="search_iflows_by_keyword",
                description="Find iFlows whose id or step names contain a keyword (case-insensitive)",
                parameters=genai.types.Schema(
                    type="object",
                    properties={
                        "keyword": genai.types.Schema(
                            type="string",
                            description="Keyword to search for (e.g., 'Customer', 'Attachment', 'SalesOrder')",
                        )
                    },
                    required=["keyword"],
                ),
            ),
            genai.types.FunctionDeclaration(
                name="get_unused_resources",
                description="List resources (scripts/mappings/schemas) that no Step actually uses",
                parameters=genai.types.Schema(
                    type="object",
                    properties={},
                    required=[],
                ),
            ),
            genai.types.FunctionDeclaration(
                name="get_iflow_step_count_ranked",
                description="Rank all iFlows by number of steps (descending) - proxy for structural complexity",
                parameters=genai.types.Schema(
                    type="object",
                    properties={},
                    required=[],
                ),
            ),
        ]
    )
]

# Map tool names to actual Python functions
TOOL_FUNCTIONS = {
    "find_iflows_using_resource": tools.find_iflows_using_resource,
    "get_resource_detail": tools.get_resource_detail,
    "describe_iflow": tools.describe_iflow,
    "get_iflow_diagram": tools.get_iflow_diagram,
    "get_iflow_systems": tools.get_iflow_systems,
    "list_all_iflows": tools.list_all_iflows,
    "find_iflows_by_protocol": tools.find_iflows_by_protocol,
    "find_resources_by_complexity": tools.find_resources_by_complexity,
    "search_iflows_by_keyword": tools.search_iflows_by_keyword,
    "get_unused_resources": tools.get_unused_resources,
    "get_iflow_step_count_ranked": tools.get_iflow_step_count_ranked,
}


def create_chat():
    """
    Create a new Gemini chat session with tools configured.
    
    Returns:
        A chat object that maintains conversation history automatically.
    """
    # Create chat with manual tool declarations
    chat = client.chats.create(
        model="gemini-3.5-flash-lite",
        config=genai.types.GenerateContentConfig(
            tools=TOOLS,
            system_instruction=SYSTEM_INSTRUCTION,
        ),
    )
    return chat


def chat_turn(chat, user_message: str) -> str:
    """
    Send a message to the chat and get a response.
    Manually handles function calls by dispatching to Python functions in tools.py
    
    Args:
        chat: The chat object (maintains history automatically)
        user_message: User's text input
    
    Returns:
        The assistant's response text
    """
    try:
        # Send initial message
        response = chat.send_message(user_message)
        
        # Loop until we get a final text response (no more function calls)
        while response.function_calls:
            # Process each function call
            function_responses = []
            
            for function_call in response.function_calls:
                func_name = function_call.name
                func_args = function_call.args
                
                # Look up the Python function
                if func_name not in TOOL_FUNCTIONS:
                    result = {"error": f"Unknown function: {func_name}"}
                else:
                    try:
                        # Call the Python function with the provided arguments
                        func = TOOL_FUNCTIONS[func_name]
                        result = func(**func_args)
                        # Gemini function responses must use a dictionary payload.
                        if not isinstance(result, dict):
                            result = {"result": result}
                    except Exception as exc:
                        result = {"error": str(exc)}
                
                # Wrap result in function response
                function_responses.append(
                    genai.types.Part.from_function_response(
                        name=func_name,
                        response=result,
                    )
                )
            
            # Send function results back to continue the conversation
            response = chat.send_message(function_responses)
        
        # Return the final text response
        return response.text
    except Exception as exc:
        return f"Error: {exc}"


def main():
    """
    REPL loop for interactive chat with the CPI integration assistant.
    """
    print("CPI Integration Assistant")
    print("=" * 60)
    print("Ask questions about iFlows, resources, and systems.")
    print("Type 'exit' to quit.\n")

    # Create a single chat session that persists across turns
    chat = create_chat()

    while True:
        try:
            user_input = input("You: ").strip()
        except EOFError:
            break

        if user_input.lower() == "exit":
            print("Goodbye!")
            break

        if not user_input:
            continue

        response = chat_turn(chat, user_input)
        print(f"\nAssistant: {response}\n")


if __name__ == "__main__":
    main()
