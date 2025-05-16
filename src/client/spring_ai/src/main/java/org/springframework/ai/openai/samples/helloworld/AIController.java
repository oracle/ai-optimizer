/*
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
*/

package org.springframework.ai.openai.samples.helloworld;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.ChatClient.ChatClientRequestSpec;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.chat.prompt.PromptTemplate;
import org.springframework.ai.document.Document;
import org.springframework.ai.embedding.EmbeddingModel;
//import org.springframework.ai.openai.api.OpenAiApi.ChatCompletionRequest;
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
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.springframework.ai.vectorstore.oracle.OracleVectorStore;

import jakarta.annotation.PostConstruct;

import org.springframework.core.io.Resource;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.ArrayList;
import java.util.Map;
import java.util.HashMap;
import java.security.SecureRandom;
import java.time.Instant;


import java.util.Iterator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;


import org.springframework.ai.openai.samples.helloworld.model.*;


@RestController
class AIController {

	@Value("${spring.ai.openai.chat.options.model}")
	private String modelOpenAI;

	@Value("${spring.ai.ollama.chat.options.model}")
	private String modelOllamaAI;

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
	private static final int SLEEP = 50; 		// Wait in streaming between chunks
	private static final int STREAM_SIZE = 5;    // chars in each chunk
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
		
		//This template doesn't work with re-phrasing/grading pattern, but only via Vector Search 
		//The contextInstr coming from Oracle ai optimizer and toolkit can't be used here: default only
		//Modifiy it to include re-phrasing/grading if you wish.

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


@PostMapping(value = "/chat/completions", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public ResponseBodyEmitter streamCompletions(@RequestBody ChatRequest request) {
	ResponseBodyEmitter bodyEmitter = new ResponseBodyEmitter();
	String userMessageContent;

	for (Map<String, String> message : request.getMessages()) {
		if ("user".equals(message.get("role"))) {
			
				String content = message.get("content");
				if (content != null && !content.trim().isEmpty()) {
					userMessageContent = content;
					logger.info("user message: "+userMessageContent);
					Prompt prompt = promptEngineering(userMessageContent, contextInstr);
					logger.info("prompt message: "+prompt.getContents());
					String contentResponse = chatClient.prompt(prompt).call().content();
					logger.info("-------------------------------------------------------");
					logger.info("- VECTOR SEARCH RETURN                                -");
					logger.info("-------------------------------------------------------");
					logger.info(contentResponse);
					new Thread(() -> {
						try {
							ObjectMapper mapper = new ObjectMapper();
				
							if (request.isStream()) {
								logger.info("Request is a Stream");
								List<String> chunks= chunkString(contentResponse);
								for (String token : chunks) {
									
									ChatMessage  messageAnswer = new ChatMessage("assistant", token);
									ChatChoice choice = new ChatChoice(messageAnswer);
									ChatStreamResponse chunk = new ChatStreamResponse("chat.completion.chunk", new ChatChoice[]{choice});
									
									bodyEmitter.send("data: " + mapper.writeValueAsString(chunk) + "\n\n");
									Thread.sleep(SLEEP);
								}
								
								bodyEmitter.send("data: [DONE]\n\n");
							} else {
								logger.info("Request isn't a Stream");
								String id="chatcmpl-"+generateRandomToken(28);
								String object="chat.completion";
								String created=String.valueOf(Instant.now().getEpochSecond());
								String model=getModel();
								ChatMessage  messageAnswer = new ChatMessage("assistant", contentResponse);
								List<ChatChoice> choices = List.of(new ChatChoice(messageAnswer));
								bodyEmitter.send(new ChatResponse(id, object,created, model, choices));
							}
							bodyEmitter.complete();
						} catch (Exception e) {
							bodyEmitter.completeWithError(e);
						}
					}).start();
				
					return bodyEmitter;

				}
			break; 
		}
	}
	

	return bodyEmitter;
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

	@GetMapping("/models")
	Map<String, Object> models(@RequestBody (required = false) Map<String, String> requestBody) {
		String modelId = "custom";
		logger.info("models request");
		if (!"".equals(modelOpenAI)) {
			modelId = modelOpenAI;
		} else if (!"".equals(modelOllamaAI)) {
			modelId = modelOllamaAI;
		} 
		logger.info("model");
		
		
		logger.info(chatClient.prompt().toString());
		try {
			Map<String, Object> model = new HashMap<>();
			model.put("id", modelId);
        	model.put("object", "model");
        	model.put("created", 0000000000L);
        	model.put("owned_by", "no-info");

        	List<Map<String, Object>> dataList = new ArrayList<>();
        	dataList.add(model);

        	Map<String, Object> response = new HashMap<>();
        	response.put("object", "list");
        	response.put("data", dataList);

			return response;

		} catch (Exception e) {
			logger.error("Error while fetching completion", e);
			return Map.of("error", "Failed to fetch completion");
		}
	}


	public List<String> chunkString(String input) {
		List<String> chunks = new ArrayList<>();
		int chunkSize = STREAM_SIZE; 
	
		for (int i = 0; i < input.length(); i += chunkSize) {
			int end = Math.min(input.length(), i + chunkSize);
			chunks.add(input.substring(i, end));
		}
	
		return chunks;
	}

	public String generateRandomToken(int length) {
		String CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    	SecureRandom random = new SecureRandom();
        StringBuilder sb = new StringBuilder(length);
        for (int i = 0; i < length; i++) {
            int index = random.nextInt(CHARACTERS.length());
            sb.append(CHARACTERS.charAt(index));
        }
        return sb.toString();
    }

	public String getModel(){
		String modelId="custom";
		if (!"".equals(modelOpenAI)) {
			modelId = modelOpenAI;
		} else if (!"".equals(modelOllamaAI)) {
			modelId = modelOllamaAI;
		} 
		return modelId;
	}
}




