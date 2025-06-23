package org.springframework.ai.openai.samples.helloworld;

import org.springframework.stereotype.Service;

import java.util.Iterator;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.chat.prompt.PromptTemplate;
import org.springframework.ai.document.Document;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.oracle.OracleVectorStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Lazy;
import org.springframework.jdbc.core.JdbcTemplate;

@Service
public class RagService {

    private final String modelOpenAI;
    private final String modelOllamaAI;
    private final ChatClient chatClient;
    private final OracleVectorStore vectorStore;
    private final EmbeddingModel embeddingModel;
    private final String legacyTable;
    private final String contextInstr;
    private final String searchType;
    private final int TOPK;
    private JdbcTemplate jdbcTemplate;

    private static final Logger logger = LoggerFactory.getLogger(RagService.class);
    private static final int SLEEP = 50; // Wait in streaming between chunks
    private static final int STREAM_SIZE = 5; // chars in each chunk

    @Autowired
    private PromptBuilderService promptBuilderService;

    RagService(
            String modelOpenAI,
            String modelOllamaAI,
            @Lazy ChatClient chatClient,
            EmbeddingModel embeddingModel,
            OracleVectorStore vectorStore,
            JdbcTemplate jdbcTemplate,
            String legacyTable,
            String contextInstr,
            String searchType,
            int TOPK) {
        this.modelOpenAI = modelOpenAI;
        this.modelOllamaAI = modelOllamaAI;
        this.vectorStore = vectorStore;
        this.chatClient = chatClient;
        this.embeddingModel = embeddingModel;
        this.legacyTable = legacyTable;
        this.contextInstr = contextInstr;
        this.searchType = searchType;
        this.TOPK = TOPK;
        this.jdbcTemplate = jdbcTemplate;
    }

    @Tool(description = "Use this tool to answer any question that may benefit from up-to-date or domain-specific information.")
    public String getRag(String question) {

        // Implementation
        Prompt prompt = promptBuilderService.buildPrompt(question, contextInstr, TOPK);
        logger.info("prompt message: " + prompt.getContents());
        String contentResponse = chatClient.prompt(prompt).call().content();
    
        return (contentResponse);
    }
}
