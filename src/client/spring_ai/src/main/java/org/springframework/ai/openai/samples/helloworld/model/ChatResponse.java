/*
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
*/
package org.springframework.ai.openai.samples.helloworld.model;


import java.util.List;

public class ChatResponse {

    private String id; //chatcmpl-B9MBs8CjcvOU2jLn4n570S5qMJKcT
    private String object; //chat.completion
    private String created; // 1741569952,
    private String model;  //gpt-4.1-2025-04-14",
    private List<ChatChoice> choices; // message

    public ChatResponse(String id, String object, String created, String model, List<ChatChoice> choices) {
        this.id = id;
        this.object = object;
        this.created = created;
        this.model = model;
        this.choices = choices;
    }

    public ChatResponse() {}


    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public String getCreated() {
        return created;
    }

    public void setCreated(String created) {
        this.created = created;
    }

    public String getModel() {
        return model;
    }

    public void setModel(String model) {
        this.model = model;
    }

    public List<ChatChoice> getChoices() {
        return choices;
    }

    public void setChoices(List<ChatChoice> choices) {
        this.choices = choices;
    }

   
 
    public String getObject() {
        return object;
    }

    public void setObject(String object) {
        this.object = object;
    }
}