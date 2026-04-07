/*
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
*/

package org.springframework.ai.openai.samples.helloworld;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.annotation.Value;

@Configuration
public class Config {

    @Bean
    public ChatClient chatClient(ChatClient.Builder builder) {
        return builder.build();
    }

    // Optional: Centralize property values if used in multiple places
    @Bean
    public String modelOpenAI(@Value("${spring.ai.openai.chat.options.model}") String modelOpenAI) {
        return modelOpenAI;
    }

    @Bean
    public String modelOllamaAI(@Value("${spring.ai.ollama.chat.options.model}") String modelOllamaAI) {
        return modelOllamaAI;
    }

    @Bean
    public String legacyTable(@Value("${aims.vectortable.name}") String table) {
        return table;
    }
    
    @Bean
    public String userTable(@Value("${aims.vectortable.user}") String user) {
        return user;
    }


    @Bean
    public String contextInstr(@Value("${aims.sys_instr}") String instr) {
        return instr;
    }

    @Bean
    public String searchType(@Value("${aims.rag_params.search_type}") String searchType) {
        return searchType;
    }

    @Bean
    public Integer topK(@Value("${aims.rag_params.top_k}") int topK) {
        return topK;
    }
   
}



