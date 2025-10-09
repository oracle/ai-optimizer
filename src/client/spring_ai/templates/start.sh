# Set Values
export PROVIDER="{provider}"

if [[ "{provider}" == "ollama" ]]; then
    PREFIX="OL"; UNSET_PREFIX="OP"
    export OPENAI_CHAT_MODEL=""
    unset OPENAI_EMBEDDING_MODEL
    unset OPENAI_URL
    export OLLAMA_BASE_URL="{ll_model[api_base]}"
    export OLLAMA_CHAT_MODEL="{ll_model[id]}"
    export OLLAMA_EMBEDDING_MODEL="{vector_search[id]}"
else
    PREFIX="OP"; UNSET_PREFIX="OL"
    export OPENAI_CHAT_MODEL="{ll_model[id]}"
    export OPENAI_EMBEDDING_MODEL="{vector_search[id]}"
    export OPENAI_URL="{ll_model[api_base]}"
    export OLLAMA_CHAT_MODEL=""
    unset OLLAMA_EMBEDDING_MODEL
fi

TEMPERATURE="{ll_model[temperature]}"
FREQUENCY_PENALTY="{ll_model[frequency_penalty]}"
PRESENCE_PENALTY="{ll_model[presence_penalty]}"
MAX_TOKENS="{ll_model[max_tokens]}"
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
export DISTANCE_TYPE="{vector_search[distance_metric]}"
export INDEX_TYPE="{vector_search[index_type]}"
export SYS_INSTR="{sys_prompt}"
export TOP_K="{vector_search[top_k]}"

export VECTOR_STORE="{vector_search[vector_store]}"
mvn spring-boot:run -P {provider}