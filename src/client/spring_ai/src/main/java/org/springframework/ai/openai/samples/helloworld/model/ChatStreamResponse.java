/*
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
*/
package org.springframework.ai.openai.samples.helloworld.model;


public class ChatStreamResponse {
    private String object;
    private ChatChoice[] choices;

    public ChatStreamResponse() {}

    public ChatStreamResponse(String object, ChatChoice[] choices) {
        this.object = object;
        this.choices = choices;
    }

    public String getObject() {
        return object;
    }

    public void setObject(String object) {
        this.object = object;
    }

    public ChatChoice[] getChoices() {
        return choices;
    }

    public void setChoices(ChatChoice[] choices) {
        this.choices = choices;
    }
}