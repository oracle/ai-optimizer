# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

"""This is a 5-minute quick-bot"""
#spell-checker: ignore openai

import os
from colorama import Fore
import openai

# Set the API Key
openai.api_key = os.environ.get("OPENAI_API_KEY", default=None)
# Establish client connection; could provide additional parameters (Temp, Penalties, etc)
client = openai.OpenAI()


def get_openai_response(input_txt):
    """Interact with LLM"""

    # Set the System Prompt
    system_prompt = "You are a helpful assistant. If you know the user's name, use it in your response."

    # Invoke the Model
    response = client.chat.completions.create(
        # LLM Model
        model="gpt-3.5-turbo",
        # Context Window containing prompts
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_txt},
        ],
    )
    # Extract Response
    message = response.choices[0].message.content
    return message


def main():
    """Main"""
    print("Type 'exit' to end the conversation.")
    ## Chat Bot Loop; take input, print response
    while True:
        user_input = input(f"{Fore.BLUE}You: ")
        if user_input.lower() in ["bye", "exit"]:
            print("Bot: Goodbye! Have a great day!")
            break
        response = get_openai_response(user_input)
        print(f"\n{Fore.BLACK}Bot: {response}\n")


if __name__ == "__main__":
    main()
