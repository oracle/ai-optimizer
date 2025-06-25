# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

"""This is a 1-day GUI Bot"""
# spell-checker:ignore langchain, openai, streamlit

import os

# Streamlit
import streamlit as st
from streamlit import session_state as state

# Langchain
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import InMemoryChatMessageHistory

# Establish client connection; could provide additional parameters (Temp, Penalties, etc)
MODEL = "gpt-4o-mini"
client = ChatOpenAI(api_key=os.environ.get("OPENAI_API_KEY", default=None), temperature=0.5, model=MODEL)
# Store Chat History
if "chat_history" not in state:
    state.chat_history = InMemoryChatMessageHistory()


def get_openai_response(input_txt):
    """Interact with LLM"""
    system_prompt = "You are a helpful assistant. If you know the user's name, use it in your response."

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
        lambda session_id: state.chat_history,
        input_messages_key="input",
        history_messages_key="chat_history",
    )
    return chain_with_history.invoke({"input": input_txt}, {"configurable": {"session_id": "unused"}})


# Regurgitate Chat History
for msg in state.chat_history.messages:
    st.chat_message(msg.type).write(msg.content)

user_input = st.chat_input("Ask your question here...")
if user_input:
    st.chat_message("user").write(user_input)
    response = get_openai_response(user_input)
    st.chat_message("ai").write(response.content)
