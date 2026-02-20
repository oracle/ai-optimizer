/*
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
*/
package org.springframework.ai.openai.samples.helloworld;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.chat.prompt.PromptTemplate;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.oracle.OracleVectorStore;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

@Component
public class PromptBuilderService {

    private static final Logger logger = LoggerFactory.getLogger(PromptBuilderService.class);

    private final OracleVectorStore vectorStore;

    public PromptBuilderService(OracleVectorStore vectorStore) {
        this.vectorStore = vectorStore;
    }

    public Prompt buildPrompt(String message, String contextInstr, int topK) {
        String template = """
                DOCUMENTS:
                {documents}

                QUESTION:
                {question}

                INSTRUCTIONS:""";

        // That's a standard RAG instruction, provided for convenience to change the contextInstr coming by the Oracle AI Optimizer export
        String defaultInstr = """
                Answer the users question using the DOCUMENTS text above.
                Keep your answer ground in the facts of the DOCUMENTS.
                If the DOCUMENTS doesn’t contain the facts to answer the QUESTION, return:
                I'm sorry but I haven't enough information to answer.
                """;

        template += "\n" + contextInstr;

        List<Document> similarDocuments = vectorStore.similaritySearch(
                SearchRequest.builder().query(message).topK(topK).build());

        StringBuilder context = createContext(similarDocuments);

        PromptTemplate promptTemplate = new PromptTemplate(template);
        Prompt prompt = promptTemplate.create(Map.of("documents", context, "question", message));

        LOGGER.info("Generated Prompt:\n{}", prompt.toString());

        return prompt;
    }

    private StringBuilder createContext(List<Document> documents) {
        String START = "\n<article>\n";
        String STOP = "\n</article>\n";

        StringBuilder context = new StringBuilder();
        for (Document doc : documents) {
            context.append(doc.getId()).append(".");
            context.append(START).append(doc.getFormattedContent()).append(STOP);
        }
        return context;
    }
}
