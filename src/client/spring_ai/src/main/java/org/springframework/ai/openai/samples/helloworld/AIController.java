/*
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
*/

package org.springframework.ai.openai.samples.helloworld;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.chat.prompt.PromptTemplate;
import org.springframework.ai.document.Document;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.reader.ExtractedTextFormatter;
import org.springframework.ai.reader.pdf.PagePdfDocumentReader;
import org.springframework.ai.reader.pdf.config.PdfDocumentReaderConfig;
import org.springframework.ai.transformer.splitter.TokenTextSplitter;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.ai.vectorstore.oracle.OracleVectorStore;

import jakarta.annotation.PostConstruct;

import org.springframework.core.io.Resource;
import org.springframework.jdbc.core.JdbcTemplate;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.ArrayList;
import java.util.Map;
import java.util.HashMap;

import java.util.Iterator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@RestController
class AIController {

	@Autowired
	private final OracleVectorStore vectorStore;

	@Autowired
	private final EmbeddingModel embeddingModel;

	@Autowired
	private final ChatClient chatClient;

	@Value("${aims.vectortable.name}")
	private String legacyTable;

	@Value("${aims.context_instr}")
	private String contextInstr;

	@Value("${aims.rag_params.search_type}")
	private String searchType;

	@Value("${aims.rag_params.top_k}")
	private int TOPK;

	@Autowired
	private JdbcTemplate jdbcTemplate;

	private static final Logger logger = LoggerFactory.getLogger(AIController.class);

	AIController(ChatClient chatClient, EmbeddingModel embeddingModel, OracleVectorStore vectorStore) {

		this.chatClient = chatClient;
		this.embeddingModel = embeddingModel;
		this.vectorStore = vectorStore;

	}

	@GetMapping("/service/llm")
	Map<String, String> completion(@RequestParam(value = "message", defaultValue = "Tell me a joke") String message) {

		return Map.of(
				"completion",
				chatClient.prompt()
						.user(message)
						.call()
						.content());
	}

	@PostConstruct
	public void insertData() {
		String sqlUser = "SELECT USER FROM DUAL";
		String user = "";
		String sql = "";
		String newTable = legacyTable+"_SPRINGAI";

		user = jdbcTemplate.queryForObject(sqlUser, String.class);
		if (doesTableExist(legacyTable,user)!=-1) {
			// RUNNING LOCAL
			logger.info("Running local with user: " + user);
			sql = "INSERT INTO " + user + "." + newTable + " (ID, CONTENT, METADATA, EMBEDDING) " +
					"SELECT ID, TEXT, METADATA, EMBEDDING FROM " + user + "." + legacyTable;
		} else {
			// RUNNING in OBAAS
			logger.info("Running on OBaaS with user: " + user);
			sql = "INSERT INTO " + user + "." + newTable+ " (ID, CONTENT, METADATA, EMBEDDING) " +
					"SELECT ID, TEXT, METADATA, EMBEDDING FROM ADMIN." + legacyTable;
		}
		// Execute the insert
		logger.info("doesExist"+  user + ": "+ doesTableExist(newTable,user));
		if (countRecordsInTable(newTable,user)==0) {
			// First microservice execution
			logger.info("Table " + user + "." + newTable+ " doesn't exist: create from ADMIN/USER." + legacyTable);
			jdbcTemplate.update(sql);
		} else {
			// Table conversion already done
			logger.info("Table +"+ newTable+" exists: drop before if you want use with new contents " + legacyTable);
		}
	}

	public int countRecordsInTable(String tableName, String schemaName) {
		// Dynamically construct the SQL query with the table and schema names
		String sql = String.format("SELECT COUNT(*) FROM %s.%s", schemaName.toUpperCase(), tableName.toUpperCase());
		logger.info("Checking if table is empty: " + tableName + " in schema: " + schemaName);
		
		try {
			// Execute the query and get the count of records in the table
			Integer count = jdbcTemplate.queryForObject(sql, Integer.class);
			
			// Return the count if it's not null, otherwise return -1
			return count != null ? count : -1;
		} catch (Exception e) {
			logger.error("Error checking table record count: " + e.getMessage());
			return -1; // Return -1 in case of an error
		}
	}

	public int doesTableExist(String tableName, String schemaName) {
		String sql = "SELECT COUNT(*) FROM all_tables WHERE table_name = ? AND owner = ?";
		logger.info("Checking if table exists: " + tableName + " in schema: " + schemaName);

		try {
			// Query the system catalog to check for the existence of the table in the given
			// schema
			Integer count = jdbcTemplate.queryForObject(sql, Integer.class, tableName.toUpperCase(),
					schemaName.toUpperCase());
			
			if (count != null && count > 0) { return count;}
			else {return -1;}
		} catch (Exception e) {
			logger.error("Error checking table existence: " + e.getMessage());
			return -1;
		}
	}

	public Prompt promptEngineering(String message, String contextInstr) {

		String template = """
				DOCUMENTS:
				{documents}

				QUESTION:
				{question}

				INSTRUCTIONS:""";

		String default_Instr = """
					Answer the users question using the DOCUMENTS text above.
				Keep your answer ground in the facts of the DOCUMENTS.
				If the DOCUMENTS doesn’t contain the facts to answer the QUESTION, return:
				I'm sorry but I haven't enough information to answer.
				""";
		
		//This template doesn't work with agent pattern, but only via RAG 
		//The contextInstr coming from AI Optimizer can't be used here: default only
		template = template + "\n" + default_Instr;

		List<Document> similarDocuments = this.vectorStore.similaritySearch(
				SearchRequest.builder().query(message).topK(TOPK).build());

		StringBuilder context = createContext(similarDocuments);

		PromptTemplate promptTemplate = new PromptTemplate(template);

		Prompt prompt = promptTemplate.create(Map.of("documents", context, "question", message));

		logger.info(prompt.toString());

		return prompt;

	}

	StringBuilder createContext(List<Document> similarDocuments) {
		String START = "\n<article>\n";
		String STOP = "\n</article>\n";

		Iterator<Document> iterator = similarDocuments.iterator();
		StringBuilder context = new StringBuilder();
		while (iterator.hasNext()) {
			Document document = iterator.next();
			context.append(document.getId() + ".");
			context.append(START + document.getFormattedContent() + STOP);
		}
		return context;
	}

	@PostMapping("/chat/completions")
	Map<String, Object> completionRag(@RequestBody Map<String, String> requestBody) {

		String message = requestBody.getOrDefault("message", "Tell me a joke");
		Prompt prompt = promptEngineering(message, contextInstr);
		logger.info(prompt.getContents());
		try {
			String content = chatClient.prompt(prompt).call().content();
			Map<String, Object> messageMap = Map.of("content", content);
			Map<String, Object> choicesMap = Map.of("message", messageMap);
			List<Map<String, Object>> choicesList = List.of(choicesMap);

			return Map.of("choices", choicesList);

		} catch (Exception e) {
			logger.error("Error while fetching completion", e);
			return Map.of("error", "Failed to fetch completion");
		}
	}

	@GetMapping("/service/search")
	List<Map<String, Object>> search(@RequestParam(value = "message", defaultValue = "Tell me a joke") String query,
			@RequestParam(value = "topk", defaultValue = "5") Integer topK) {

		List<Document> similarDocs = vectorStore.similaritySearch(SearchRequest.builder()
			.query(query)
			.topK(topK)
			.build());

		List<Map<String, Object>> resultList = new ArrayList<>();
		for (Document d : similarDocs) {
			Map<String, Object> metadata = d.getMetadata();
			Map doc = new HashMap<>();
			doc.put("id", d.getId());
			resultList.add(doc);
		}
		;
		return resultList;
	}
}
