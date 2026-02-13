/*
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
*/

const chatBotUrl = 'http://127.0.0.1:8000/v1/chat/completions';
const api_key = "abc";

document.addEventListener('DOMContentLoaded', () => {
    const openChatBtn = document.getElementById('open-chat-btn');
    const closeChatBtn = document.getElementById('close-chat-btn');
    const chatWidget = document.getElementById('chat-widget');
    const sendBtn = document.getElementById('send-btn');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');

    openChatBtn.addEventListener('click', () => {
        chatWidget.classList.remove('chat-hidden');
        openChatBtn.style.display = 'none';
    });

    closeChatBtn.addEventListener('click', () => {
        chatWidget.classList.add('chat-hidden');
        openChatBtn.style.display = 'block';
    });


    sendBtn.addEventListener('click', async () => {
        const userMessage = chatInput.value;
        if (userMessage.trim()) {
            appendMessage(userMessage, 'user-message');
            chatInput.value = '';

            const botResponse = await getBotResponse(userMessage);
            appendMessage(botResponse, 'bot-message');
        }
    });


    function appendMessage(message, className) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', className);
        messageElement.textContent = message;
        chatMessages.appendChild(messageElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;  // Auto-scroll to the bottom
    }

    async function getBotResponse(userMessage) {
        const apiUrl = chatBotUrl;
        const messagePayload = {
            model: "",
            messages: [
                {
                    role: "user",
                    content: userMessage
                }
            ]
        };



        try {
            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + api_key
                },
                body: JSON.stringify(messagePayload)
            });

            const data = await response.json();
            //return data.answer;
            return data.choices[0].text + "\n Source: " + data.sources[0];
        } catch (error) {
            console.error('Error fetching API:', error);
            return "Sorry, I couldn't connect to the server.";
        }
    }
});





