/*
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
*/

package org.springframework.ai.openai.samples.helloworld;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.document.Document;
import org.springframework.ai.embedding.EmbeddingModel;
//import org.springframework.ai.openai.api.OpenAiApi.ChatCompletionRequest;

import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Lazy;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.springframework.ai.vectorstore.oracle.OracleVectorStore;

import jakarta.annotation.PostConstruct;

import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;


import java.util.List;
import java.util.ArrayList;
import java.util.Map;
import java.util.HashMap;

import java.time.Instant;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.ai.openai.samples.helloworld.model.*;

@RestController
class AIController {

	private final String modelOpenAI;
	private final String modelOllamaAI;
	private final ChatClient chatClient;
	private final OracleVectorStore vectorStore;
	private final EmbeddingModel embeddingModel;
	private final String legacyTable;
	private final String userTable;
	private final String contextInstr;
	private final String searchType;
	private final int TOPK;
	private JdbcTemplate jdbcTemplate;

	private static final Logger logger = LoggerFactory.getLogger(AIController.class);
	private static final int SLEEP = 50; // Wait in streaming between chunks
	private static final int STREAM_SIZE = 5; // chars in each chunk

	@Autowired
	private PromptBuilderService promptBuilderService;

	@Autowired
	private Helper helper;

	AIController(
			String modelOpenAI,
			String modelOllamaAI,
			@Lazy  ChatClient chatClient,
			EmbeddingModel embeddingModel,
			OracleVectorStore vectorStore,
			JdbcTemplate jdbcTemplate,
			String legacyTable,
			String userTable,
			String contextInstr,
			String searchType,
			int TOPK) {

		this.modelOpenAI = modelOpenAI;
		this.modelOllamaAI = modelOllamaAI;
		this.vectorStore = vectorStore;
		this.chatClient = chatClient;
		this.embeddingModel = embeddingModel;
		this.legacyTable = legacyTable;
		this.userTable = userTable;
		this.contextInstr = contextInstr;
		this.searchType = searchType;
		this.TOPK = TOPK;
		this.jdbcTemplate = jdbcTemplate;

	}


	/**
 	* Chat completion endpoint to interact with the LLM, without RAG,memory or system prompting.
 	* No compliant with Open AI API
	*
 	* @param message: the message to be routed to the LLM 
 	*/
	@GetMapping("/v1/service/llm")
	Map<String, String> completion(@RequestParam(value = "message", defaultValue = "Tell me a joke") String message) {

		return Map.of(
				"completion",
				chatClient.prompt()
						.user(message)
						.call()
						.content());
	}

	/**
 	* Create a new table with the Spring AI format from an existing vectorstore made by langchain 
	* If table already exists, it will not be overrided.
	*
 	*/
	@PostConstruct
	public void insertData() {
		String sqlUser = "SELECT USER FROM DUAL";
		String user = "";
		String sql = "";
		String newTable = legacyTable + "_SPRINGAI";

		user = jdbcTemplate.queryForObject(sqlUser, String.class);
		if (helper.doesTableExist(legacyTable, user,this.jdbcTemplate) != -1) {
			// RUNNING LOCAL
			logger.info("Running local with user: " + user);
			sql = "INSERT INTO " + user + "." + newTable + " (ID, CONTENT, METADATA, EMBEDDING) " +
					"SELECT ID, TEXT, METADATA, EMBEDDING FROM " + user + "." + legacyTable;
		} else {
			// RUNNING in OBAAS
			logger.info("Running on OBaaS with user: " + user);
			logger.info("copying langchain table from schema/user: " + userTable);
			sql = "INSERT INTO " + user + "." + newTable + " (ID, CONTENT, METADATA, EMBEDDING) " +
					"SELECT ID, TEXT, METADATA, EMBEDDING FROM "+ userTable+"." + legacyTable;
		}
		// Execute the insert
		logger.info("doesExist" + user + ": " + helper.doesTableExist(newTable, user,this.jdbcTemplate));
		if (helper.countRecordsInTable(newTable, user,this.jdbcTemplate) == 0) {
			// First microservice execution
			logger.info("Table " + user + "." + newTable + " doesn't exist: create from "+userTable+"." + legacyTable);
			jdbcTemplate.update(sql);
		} else {
			// Table conversion already done
			logger.info("Table " + user+"."+newTable + " exists: drop before if you want use with new contents " + userTable + "." + legacyTable);
		}
	}


	/**
 	* Chat completion endpoint to interact with the LLM, with RAG support.
 	* Compliant with Open AI API
	* It works also in stream 
	*
 	* @param message: the message to be routed to the LLM along the prompt/context
	* @return the llm response in one shot or in streaming
 	*/
	@PostMapping(value = "/v1/chat/completions", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	public ResponseBodyEmitter streamCompletions(@RequestBody ChatRequest request) {
		ResponseBodyEmitter bodyEmitter = new ResponseBodyEmitter();
		String userMessageContent;

		for (Map<String, String> message : request.getMessages()) {
			if ("user".equals(message.get("role"))) {

				String content = message.get("content");
				if (content != null && !content.trim().isEmpty()) {
					userMessageContent = content;
					logger.info("user message: " + userMessageContent);
					Prompt prompt = promptBuilderService.buildPrompt(userMessageContent, contextInstr, TOPK);
					logger.info("prompt message: " + prompt.getContents());
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
								List<String> chunks = helper.chunkString(contentResponse);
								for (String token : chunks) {

									ChatMessage messageAnswer = new ChatMessage("assistant", token);
									ChatChoice choice = new ChatChoice(messageAnswer);
									ChatStreamResponse chunk = new ChatStreamResponse("chat.completion.chunk",
											new ChatChoice[] { choice });

									bodyEmitter.send("data: " + mapper.writeValueAsString(chunk) + "\n\n");
									Thread.sleep(SLEEP);
								}

								bodyEmitter.send("data: [DONE]\n\n");
							} else {
								logger.info("Request isn't a Stream");
								String id = "chatcmpl-" + helper.generateRandomToken(28);
								String object = "chat.completion";
								String created = String.valueOf(Instant.now().getEpochSecond());
								String model = helper.getModel(this.modelOpenAI,this.modelOllamaAI);
								ChatMessage messageAnswer = new ChatMessage("assistant", contentResponse);
								List<ChatChoice> choices = List.of(new ChatChoice(messageAnswer));
								bodyEmitter.send(new ChatResponse(id, object, created, model, choices));
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

	/**
 	* Similarity search 
	*
 	* @param message: the message to be routed to the LLM along the prompt/context
	* @param topK: the number of chunks to be included in the context
	* @return the list of the nearest topK chunks
 	*/
	@GetMapping("/v1/service/search")
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

	/**
 	* Store new chunks, sent as a list of strings in the request body 
	*
 	* @param chunks: the list of chunks
	* @return the list of vector embeddings created and stored along the chunks
 	*/
	@PostMapping("/v1/service/store-chunks")
	List<List<Double>> store(@RequestBody List<String> chunks) {
		List<List<Double>> allVectors = new ArrayList<>();
		List<Document> documents = chunks.stream()
				.map(chunk -> {
					double[] vector = helper.floatToDouble(embeddingModel.embed(chunk));
					Double[] sVector = java.util.Arrays.stream(vector)
							.mapToObj(Double::valueOf)
							.toArray(Double[]::new);
					allVectors.add(java.util.Arrays.asList(sVector));
					return Document.builder()
							.text(chunk)
							.metadata("source", "user-added")
							.build();
				})
				.collect(Collectors.toList());

		vectorStore.doAdd(documents);

		return allVectors;
	}
	
	/**
 	* List of model
	*
 	* @param requestBody: the message to be routed to the LLM along the prompt/context
	* @return in this case it will be returned a list with only one model on which is based this microservice
 	*/
	@GetMapping("/v1/models")
	Map<String, Object> models(@RequestBody(required = false) Map<String, String> requestBody) {
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


}
