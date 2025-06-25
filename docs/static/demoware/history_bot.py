# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

"""This is a 30-minute history-bot"""
# spell-checker:ignore langchain, openai

import os
from colorama import Fore

# Langchain
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import InMemoryChatMessageHistory

# Establish client connection; could provide additional parameters (Temp, Penalties, etc)
MODEL = "gpt-4o-mini"
client = ChatOpenAI(api_key=os.environ.get("OPENAI_API_KEY", default=None), model=MODEL)
# Store Chat History
chat_history = InMemoryChatMessageHistory()


def get_openai_response(input_txt):
    """Interact with LLM"""
    system_prompt = "You are a helpful assistant. If you know the user's name, use it in your response."

    # Context Window
    qa_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            MessagesPlaceholder("chat_history"),
            ("user", input_txt),
        ]
    )
    chain = qa_prompt | client
    chain_with_history = RunnableWithMessageHistory(
        chain,
        lambda session_id: chat_history,
        input_messages_key="input",
        history_messages_key="chat_history",
    )
    return chain_with_history.invoke({"input": input_txt}, {"configurable": {"session_id": "unused"}})


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
        print(f"\n{Fore.BLACK}Bot: {response.content}\n")


if __name__ == "__main__":
    main()
