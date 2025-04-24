# Set Values
export PROVIDER="{provider}"

if [[ "{provider}" == "ollama" ]]; then
    PREFIX="OL"; UNSET_PREFIX="OP"
    export OPENAI_CHAT_MODEL=""
    unset OPENAI_EMBEDDING_MODEL
    unset OPENAI_URL
    export OLLAMA_BASE_URL="{ll_model[url]}"
    export OLLAMA_CHAT_MODEL="{ll_model[model]}"
    export OLLAMA_EMBEDDING_MODEL="{rag[model]}"
else
    PREFIX="OP"; UNSET_PREFIX="OL"
    export OPENAI_CHAT_MODEL="{ll_model[model]}"
    export OPENAI_EMBEDDING_MODEL="{rag[model]}"
    export OPENAI_URL="{ll_model[url]}"
    export OLLAMA_CHAT_MODEL=""
    unset OLLAMA_EMBEDDING_MODEL
fi

TEMPERATURE="{ll_model[temperature]}"
FREQUENCY_PENALTY="{ll_model[frequency_penalty]}"
PRESENCE_PENALTY="{ll_model[presence_penalty]}"
MAX_TOKENS="{ll_model[max_completion_tokens]}"
TOP_P="{ll_model[top_p]}"
COMMON_VARS=("TEMPERATURE" "FREQUENCY_PENALTY" "PRESENCE_PENALTY" "MAX_TOKENS" "TOP_P")

# Loop through the common variables and export them
for var in "${{COMMON_VARS[@]}}"; do
    export ${{PREFIX}}_${{var}}="${{!var}}"
    unset ${{UNSET_PREFIX}}_${{var}}
done

# env_vars
export SPRING_AI_OPENAI_API_KEY=${{OPENAI_API_KEY}}
export DB_DSN="jdbc:oracle:thin:@{database_config[dsn]}"
export DB_USERNAME="{database_config[user]}"
export DB_PASSWORD="{database_config[password]}"
export DISTANCE_TYPE="{rag[distance_metric]}"
export INDEX_TYPE="{rag[index_type]}"
export CONTEXT_INSTR="{ctx_prompt}"
export TOP_K="{rag[top_k]}"

export VECTOR_STORE="{rag[vector_store]}"
mvn spring-boot:run -P {provider}