/*
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
*/
package org.springframework.ai.openai.samples.helloworld;

import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class Helper {
    private static final Logger logger = LoggerFactory.getLogger(PromptBuilderService.class);

    private static final int SLEEP = 50; // Wait in streaming between chunks
    private static final int STREAM_SIZE = 5; // chars in each chunk

    public Helper() {
    }

    public int countRecordsInTable(String tableName, String schemaName, JdbcTemplate jdbcTemplate) {
        // Dynamically construct the SQL query with the table and schema names
        String sql = String.format("SELECT COUNT(*) FROM %s.%s", schemaName.toUpperCase(), tableName.toUpperCase());
        LOGGER.info("Checking if table is empty: " + tableName + " in schema: " + schemaName);

        try {
            // Execute the query and get the count of records in the table
            Integer count = jdbcTemplate.queryForObject(sql, Integer.class);

            // Return the count if it's not null, otherwise return -1
            return count != null ? count : -1;
        } catch (Exception e) {
            LOGGER.error("Error checking table record count: " + e.getMessage());
            return -1; // Return -1 in case of an error
        }
    }

	public int doesTableExist(String tableName, String schemaName, JdbcTemplate jdbcTemplate ) {
		String sql = "SELECT COUNT(*) FROM all_tables WHERE table_name = ? AND owner = ?";
		LOGGER.info("Checking if table exists: " + tableName + " in schema: " + schemaName);

		try {
			// Query the system catalog to check for the existence of the table in the given
			// schema
			Integer count = jdbcTemplate.queryForObject(sql, Integer.class, tableName.toUpperCase(),
					schemaName.toUpperCase());

			if (count != null && count > 0) {
				return count;
			} else {
				return -1;
			}
		} catch (Exception e) {
			LOGGER.error("Error checking table existence: " + e.getMessage());
			return -1;
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

    public String getModel(String modelOpenAI, String modelOllamaAI) {
        String modelId = "custom";
        if (!"_".equals(modelOpenAI)) {
            modelId = modelOpenAI;
        } else if (!"_".equals(modelOllamaAI)) {
            modelId = modelOllamaAI;
        }
        return modelId;
    }

    public double[] floatToDouble(float[] floatArray) {
        double[] doubleArray = new double[floatArray.length];

        for (int i = 0; i < floatArray.length; i++) {
            doubleArray[i] = floatArray[i]; // implicit widening cast per element
        }
        return doubleArray;
    }
}
