+++
title = 'Object Storage Embedding'
weight = 10
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

## Overview

Creating a vector store from documents stored in OCI Object Storage is a two-step API workflow:

1. **Download** objects from an OCI bucket to the server's temporary staging area.
2. **Embed** the downloaded files into a new vector store.

This separation is intentional — you can accumulate files from multiple downloads (or mix in files from other sources like local uploads) before triggering the embed step.

## Step 1: Download Objects from OCI Object Storage

Download one or more objects from an OCI Object Storage bucket to the server's staging directory.

**Endpoint:** `POST /v1/oci/objects/download/{bucket_name}/{auth_profile}`

| Parameter | Location | Description |
|---|---|---|
| `bucket_name` | Path | Name of the OCI Object Storage bucket |
| `auth_profile` | Path | OCI profile name (case-insensitive), as configured on the server |
| `client` | Header | Client identifier for scoping temp storage (default: `server`) |
| Request body | Body | JSON array of object key strings to download |

**Response:** JSON array of downloaded filenames.

### Example

```bash
curl -X POST "http://localhost:8000/v1/oci/objects/download/my-documents/DEFAULT" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -H "client: my-session" \
  -d '["reports/quarterly-review.pdf", "data/metrics.csv"]'
```

You can call this endpoint multiple times to accumulate files from the same or different buckets before proceeding to Step 2.

## Step 2: Create and Populate the Vector Store

Process all staged files — splitting them into chunks, generating embeddings, and populating the vector store.

**Endpoint:** `POST /v1/embed`

| Parameter | Location | Description |
|---|---|---|
| `rate_limit` | Query | Embedding API rate limit in requests per minute (default: `0` for unlimited) |
| `client` | Header | Must match the `client` value used in Step 1 |
| Request body | Body | `VectorStoreConfig` JSON object (see below) |

### VectorStoreConfig Fields

| Field | Type | Description |
|---|---|---|
| `alias` | string | Identifiable alias for the vector store |
| `description` | string | Human-readable description of the table contents |
| `embedding_model` | object | `{"provider": "...", "id": "..."}` — the embedding model to use |
| `chunk_size` | integer | Maximum chunk size in characters (0 for default) |
| `chunk_overlap` | integer | Overlap between chunks in characters (0 for default) |
| `distance_strategy` | string | One of: `COSINE`, `EUCLIDEAN_DISTANCE`, `DOT_PRODUCT` |
| `index_type` | string | Vector index type: `HNSW`, `IVF`, or `HYB` |
| `parsing_mode` | string | Document parsing mode: `fast` or `deep` |

**Response:** `EmbedProcessingResult` JSON object:

| Field | Type | Description |
|---|---|---|
| `message` | string | Status message |
| `total_chunks` | integer | Number of chunks created |
| `processed_files` | array | List of successfully processed files |
| `skipped_files` | array | List of files that were skipped |

### Example

```bash
curl -X POST "http://localhost:8000/v1/embed?rate_limit=60" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -H "client: my-session" \
  -d '{
    "alias": "quarterly-reports",
    "description": "Q4 quarterly review documents and metrics",
    "embedding_model": {
      "provider": "ocigenai",
      "id": "cohere.embed-english-v3.0"
    },
    "chunk_size": 1000,
    "chunk_overlap": 100,
    "distance_strategy": "COSINE",
    "index_type": "HNSW",
    "parsing_mode": "fast"
  }'
```

## Complete Example

A full end-to-end workflow downloading from two buckets and embedding:

```bash
API_URL="http://localhost:8000"
API_KEY="YOUR_API_KEY"
CLIENT="my-session"

# Download documents from the first bucket
curl -X POST "$API_URL/v1/oci/objects/download/reports-bucket/DEFAULT" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -H "client: $CLIENT" \
  -d '["2024/q4-review.pdf", "2024/q4-financials.pdf"]'

# Download documents from a second bucket
curl -X POST "$API_URL/v1/oci/objects/download/data-bucket/DEFAULT" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -H "client: $CLIENT" \
  -d '["metrics/summary.csv"]'

# Embed all accumulated files into a vector store
curl -X POST "$API_URL/v1/embed?rate_limit=60" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -H "client: $CLIENT" \
  -d '{
    "alias": "q4-knowledge-base",
    "description": "Q4 2024 reports and supporting data",
    "embedding_model": {
      "provider": "ocigenai",
      "id": "cohere.embed-english-v3.0"
    },
    "chunk_size": 1000,
    "chunk_overlap": 100,
    "distance_strategy": "COSINE",
    "index_type": "HNSW",
    "parsing_mode": "fast"
  }'
```

## Notes

- **File cleanup**: Staged files are automatically cleaned up after the embed endpoint completes, whether it succeeds or fails.
- **Mixing sources**: Files from multiple sources can be accumulated before embedding. In addition to OCI Object Storage downloads, you can upload local files via `POST /v1/embed/local/store` or scrape web content — all files are staged in the same directory scoped by the `client` header.
- **Client scoping**: The `client` header isolates temporary storage between different sessions. Use a consistent value across your download and embed calls within a single workflow.
