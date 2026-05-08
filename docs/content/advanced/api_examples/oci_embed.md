+++
title = 'Object Storage Embedding'
weight = 10
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

## Overview

There are two API workflows for creating a vector store from documents in OCI Object Storage:

1. **Single-call** — `POST /v1/embed/oci/store` downloads and embeds in one request. Recommended when the only source is an OCI bucket.
2. **Two-step** — `POST /v1/oci/objects/download` followed by `POST /v1/embed/`. Use this when you need to combine OCI objects with other sources (local uploads, web URLs, SQL query results) before embedding.

## Single-call Workflow

Download and embed in one request.

**Endpoint:** `POST /v1/embed/oci/store`

| Parameter | Location | Description |
|---|---|---|
| `rate_limit` | Query | Embedding API rate limit in requests per minute (default: `0` for unlimited) |
| `client` | Header | Client identifier for scoping temp storage (default: `server`) |
| Request body | Body | `OciEmbedRequest` JSON object (see below) |

### OciEmbedRequest Fields

| Field | Type | Description |
|---|---|---|
| `bucket_name` | string | Name of the OCI Object Storage bucket |
| `auth_profile` | string | OCI profile name (case-insensitive). Default: `DEFAULT` |
| `objects` | array of strings | Object keys to embed. Omit or pass an empty list to embed every supported object in the bucket |
| `alias` | string | Identifiable alias for the vector store |
| `description` | string | Human-readable description of the table contents |
| `embedding_model` | object | `{"provider": "...", "id": "..."}` — the embedding model to use |
| `chunk_size` | integer | Maximum chunk size in characters (0 for default) |
| `chunk_overlap` | integer | Overlap between chunks in characters (0 for default) |
| `distance_strategy` | string | One of: `COSINE`, `EUCLIDEAN_DISTANCE`, `DOT_PRODUCT` |
| `index_type` | string | Vector index type: `HNSW`, `IVF`, or `HYB` |
| `parsing_mode` | string | Document parsing mode: `fast` or `deep` |

**Response:** `202 Accepted` with an `EmbedJobAccepted` body — poll `GET /v1/embed/jobs/{job_id}` for the terminal `EmbedProcessingResult`.

| Field | Type | Description |
|---|---|---|
| `job_id` | string | Identifier of the scheduled embed job |
| `status` | string | Initial status (`queued` or `running`) |
| `location` | string | Path to the job-status endpoint |

### Example — embed specific objects

```bash
curl -X POST "http://localhost:8000/v1/embed/oci/store?rate_limit=60" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -H "client: my-session" \
  -d '{
    "bucket_name": "rag-source-docs",
    "auth_profile": "DEFAULT",
    "objects": ["product-catalog.pdf", "release-notes/2026-q2.md"],
    "alias": "product-docs",
    "description": "Product documentation embedded for RAG",
    "embedding_model": {
      "provider": "oci",
      "id": "cohere.embed-english-v3.0"
    },
    "chunk_size": 1000,
    "chunk_overlap": 100,
    "distance_strategy": "COSINE",
    "index_type": "HNSW",
    "parsing_mode": "fast"
  }'
```

### Example — embed every supported object in the bucket

Omit `objects` (or pass `[]`) to embed every object whose extension is supported (`.pdf`, `.html`, `.md`, `.txt`, `.csv`, `.docx`, `.pptx`, `.xlsx`, `.png`, `.jpg`, `.jpeg`):

```bash
curl -X POST "http://localhost:8000/v1/embed/oci/store" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -H "client: my-session" \
  -d '{
    "bucket_name": "rag-source-docs",
    "auth_profile": "DEFAULT",
    "alias": "all-docs",
    "embedding_model": {
      "provider": "oci",
      "id": "cohere.embed-english-v3.0"
    },
    "chunk_size": 1000,
    "chunk_overlap": 100,
    "distance_strategy": "COSINE",
    "index_type": "HNSW"
  }'
```

### Polling for completion

The single-call endpoint is asynchronous — the 202 response carries the `job_id`. Poll the job-status endpoint until it reaches a terminal state:

```bash
curl "http://localhost:8000/v1/embed/jobs/$JOB_ID" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "client: my-session"
```

A successful job's `result` field carries the `EmbedProcessingResult`:

| Field | Type | Description |
|---|---|---|
| `message` | string | Status message |
| `total_chunks` | integer | Number of chunks created |
| `processed_files` | array | List of successfully processed files |
| `skipped_files` | array | List of files that were skipped |

## Two-step Workflow

Use this flow when you need to combine OCI objects with other sources (local uploads, web URLs, SQL query results) before embedding. Files from each source endpoint accumulate in the same per-client staging area; the embed call consumes everything that has been staged.

### Step 1: Download Objects from OCI Object Storage

Download one or more objects from an OCI Object Storage bucket to the server's staging directory.

**Endpoint:** `POST /v1/oci/objects/download/{bucket_name}/{auth_profile}`

| Parameter | Location | Description |
|---|---|---|
| `bucket_name` | Path | Name of the OCI Object Storage bucket |
| `auth_profile` | Path | OCI profile name (case-insensitive), as configured on the server |
| `client` | Header | Client identifier for scoping temp storage (default: `server`) |
| Request body | Body | JSON array of object key strings to download |

**Response:** JSON array of downloaded filenames.

#### Example

```bash
curl -X POST "http://localhost:8000/v1/oci/objects/download/my-documents/DEFAULT" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -H "client: my-session" \
  -d '["reports/quarterly-review.pdf", "data/metrics.csv"]'
```

You can call this endpoint multiple times to accumulate files from the same or different buckets before proceeding to Step 2.

### Step 2: Create and Populate the Vector Store

Process all staged files — splitting them into chunks, generating embeddings, and populating the vector store.

**Endpoint:** `POST /v1/embed`

| Parameter | Location | Description |
|---|---|---|
| `rate_limit` | Query | Embedding API rate limit in requests per minute (default: `0` for unlimited) |
| `client` | Header | Must match the `client` value used in Step 1 |
| Request body | Body | `VectorStoreConfig` JSON object (see below) |

#### VectorStoreConfig Fields

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

**Response:** `202 Accepted` with an `EmbedJobAccepted` body — same polling contract as the single-call workflow above.

#### Example

```bash
curl -X POST "http://localhost:8000/v1/embed?rate_limit=60" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -H "client: my-session" \
  -d '{
    "alias": "quarterly-reports",
    "description": "Q4 quarterly review documents and metrics",
    "embedding_model": {
      "provider": "oci",
      "id": "cohere.embed-english-v3.0"
    },
    "chunk_size": 1000,
    "chunk_overlap": 100,
    "distance_strategy": "COSINE",
    "index_type": "HNSW",
    "parsing_mode": "fast"
  }'
```

### Complete Example

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
      "provider": "oci",
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

- **Single-call vs two-step**: The single-call endpoint downloads directly into a per-request work directory, so it only embeds the objects from the named bucket — files staged via `/v1/embed/local/store`, `/v1/embed/web/store`, or `/v1/embed/sql/store` are *not* pulled into a single-call job. The two-step flow embeds every file currently staged for the client.
- **File cleanup**: In both workflows, staged files are automatically cleaned up after the embed job completes, whether it succeeds or fails.
- **Mixing sources**: Files from multiple sources can be accumulated before embedding via the two-step flow. In addition to OCI Object Storage downloads, you can upload local files via `POST /v1/embed/local/store` or scrape web content — all files are staged in the same directory scoped by the `client` header.
- **Client scoping**: The `client` header isolates temporary storage between different sessions. Use a consistent value across your download and embed calls within a single workflow.
