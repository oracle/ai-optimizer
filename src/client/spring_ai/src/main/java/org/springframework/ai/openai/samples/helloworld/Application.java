/*
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
*/

package org.springframework.ai.openai.samples.helloworld;

import org.springframework.ai.embedding.EmbeddingModel; 
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.vectorstore.oracle.OracleVectorStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.core.JdbcTemplate;

@SpringBootApplication
public class Application {

    @Value("${aims.vectortable.name}")
	private String legacyTable;

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    OracleVectorStore vectorStore(EmbeddingModel ec, JdbcTemplate t) {
        OracleVectorStore ovs = OracleVectorStore.builder(t,ec)
            .tableName(legacyTable+"_SPRINGAI")
            .initializeSchema(true)
            .build();
        return ovs;
    }

}
