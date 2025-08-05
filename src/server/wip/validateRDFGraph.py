# A set of Validation tests for RDF graph for Chatbot use
from rdflib import Graph
import re
import statistics


def validate_chatbot_rdf_graph(rdf_file="vectorsearchuserguide.nt"):
    """Comprehensive validation of RDF graph for chatbot readiness"""

    print("🔍 VALIDATING RDF GRAPH FOR CHATBOT USE")
    print("=" * 50)

    # Load the graph
    g = Graph()
    g.parse(rdf_file, format="nt")

    validation_results = {"total_score": 0, "max_score": 0, "issues": [], "strengths": []}

    # ===== TEST 1: BASIC STRUCTURE =====
    print("\n📋 TEST 1: Basic Graph Structure")
    validation_results["max_score"] += 20

    # Count headers
    headers_query = """
    PREFIX ex: <https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/ai-vector-search-users-guide.pdf#>
    PREFIX dc: <http://purl.org/dc/elements/1.1/>

    SELECT (COUNT(?header) AS ?header_count)
    WHERE {
        ?header dc:title ?title .
    }
    """
    header_count = int(list(g.query(headers_query))[0].header_count)

    # Count chunks
    chunks_query = """
    PREFIX ex: <https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/ai-vector-search-users-guide.pdf#>

    SELECT (COUNT(?chunk) AS ?chunk_count)
    WHERE {
        ?chunk ex:hasText ?text .
    }
    """
    chunk_count = int(list(g.query(chunks_query))[0].chunk_count)

    print(f"✓ Headers: {header_count}")
    print(f"✓ Chunks: {chunk_count}")
    print(f"✓ Total triples: {len(g)}")

    if header_count > 50:
        validation_results["total_score"] += 10
        validation_results["strengths"].append(f"Rich content structure ({header_count} headers)")
    elif header_count > 20:
        validation_results["total_score"] += 7
    else:
        validation_results["issues"].append(f"Low header count ({header_count})")

    if chunk_count > 1000:
        validation_results["total_score"] += 10
        validation_results["strengths"].append(f"Excellent chunk density ({chunk_count} chunks)")
    elif chunk_count > 100:
        validation_results["total_score"] += 5
    else:
        validation_results["issues"].append(f"Insufficient chunks for good retrieval ({chunk_count})")

    # ===== TEST 2: CONTENT QUALITY =====
    print("\n📝 TEST 2: Content Quality Analysis")
    validation_results["max_score"] += 25

    content_analysis_query = """
    PREFIX ex: <https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/ai-vector-search-users-guide.pdf#>
    PREFIX dc: <http://purl.org/dc/elements/1.1/>

    SELECT ?title ?word_count ?char_count (COUNT(?chunk) AS ?chunk_count)
    WHERE {
        ?header dc:title ?title .
        ?header ex:hasWordCount ?word_count .
        ?header ex:hasCharCount ?char_count .
        ?header ex:hasChunk ?chunk .
    }
    GROUP BY ?title ?header ?word_count ?char_count
    ORDER BY DESC(?word_count)
    """

    content_results = list(g.query(content_analysis_query))

    if content_results:
        word_counts = [int(row.word_count) for row in content_results]
        chunk_counts = [int(row.chunk_count) for row in content_results]

        avg_words = statistics.mean(word_counts)
        median_words = statistics.median(word_counts)
        avg_chunks_per_section = statistics.mean(chunk_counts)

        print(f"✓ Average words per section: {avg_words:.1f}")
        print(f"✓ Median words per section: {median_words:.1f}")
        print(f"✓ Average chunks per section: {avg_chunks_per_section:.1f}")

        # Quality scoring
        if avg_words > 200:
            validation_results["total_score"] += 10
            validation_results["strengths"].append(f"Rich content depth (avg {avg_words:.0f} words/section)")
        elif avg_words > 50:
            validation_results["total_score"] += 5
        else:
            validation_results["issues"].append(f"Shallow content (avg {avg_words:.0f} words/section)")

        if 2 <= avg_chunks_per_section <= 50:
            validation_results["total_score"] += 10
            validation_results["strengths"].append(
                f"Good chunking balance ({avg_chunks_per_section:.1f} chunks/section)"
            )
        else:
            validation_results["issues"].append(f"Chunking imbalance ({avg_chunks_per_section:.1f} chunks/section)")

        # Check for sections with no content
        empty_sections = sum(1 for count in word_counts if count == 0)
        if empty_sections == 0:
            validation_results["total_score"] += 5
            validation_results["strengths"].append("All sections have content")
        else:
            validation_results["issues"].append(f"{empty_sections} sections have no content")

    # ===== TEST 3: CHUNK ANALYSIS =====
    print("\n🧩 TEST 3: Chunk Characteristics")
    validation_results["max_score"] += 20

    chunk_analysis_query = """
    PREFIX ex: <https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/ai-vector-search-users-guide.pdf#>

    SELECT ?text ?size
    WHERE {
        ?chunk ex:hasText ?text .
        ?chunk ex:hasChunkSize ?size .
    }
    """

    chunk_results = list(g.query(chunk_analysis_query))

    if chunk_results:
        chunk_sizes = [int(row.size) for row in chunk_results]
        chunk_texts = [str(row.text) for row in chunk_results]

        avg_chunk_size = statistics.mean(chunk_sizes)
        median_chunk_size = statistics.median(chunk_sizes)
        min_chunk_size = min(chunk_sizes)
        max_chunk_size = max(chunk_sizes)

        print(f"✓ Average chunk size: {avg_chunk_size:.0f} characters")
        print(f"✓ Median chunk size: {median_chunk_size:.0f} characters")
        print(f"✓ Size range: {min_chunk_size} - {max_chunk_size} characters")

        # Optimal chunk size for embeddings (300-1500 chars)
        if 300 <= avg_chunk_size <= 1500:
            validation_results["total_score"] += 10
            validation_results["strengths"].append(f"Optimal chunk size for embeddings ({avg_chunk_size:.0f} chars)")
        else:
            validation_results["issues"].append(f"Suboptimal chunk size ({avg_chunk_size:.0f} chars)")

        # Check chunk size consistency
        if max_chunk_size / min_chunk_size < 10:  # Less than 10x difference
            validation_results["total_score"] += 5
            validation_results["strengths"].append("Consistent chunk sizes")
        else:
            validation_results["issues"].append("High chunk size variability")

        # Sample chunk quality (adapted for technical content)
        sample_chunks = chunk_texts[:20]  # Check more samples
        quality_chunks = 0

        for chunk in sample_chunks:
            # More lenient quality criteria for technical documentation
            word_count = len(chunk.split())
            has_technical_content = bool(
                re.search(
                    r"\b(vector|database|sql|query|index|search|function|table|column|data|oracle|embedding|api)\b",
                    chunk.lower(),
                )
            )
            has_meaningful_text = word_count >= 8 and len(chunk.strip()) >= 50
            not_just_header = not (chunk.isupper() or len(chunk.split()) <= 3)

            if has_meaningful_text and not_just_header and (has_technical_content or "." in chunk):
                quality_chunks += 1

        chunk_quality_score = (quality_chunks / len(sample_chunks)) * 5
        validation_results["total_score"] += chunk_quality_score

        print(f"✓ Chunk quality score: {quality_chunks}/{len(sample_chunks)} samples passed")
        print(f"  Sample chunks analyzed: {len(sample_chunks)}")

        # Show a few sample chunks for debugging
        print(f"  Sample chunk examples:")
        for i, chunk in enumerate(sample_chunks[:3]):
            preview = chunk[:100].replace("\n", " ") + "..." if len(chunk) > 100 else chunk
            print(f"    {i + 1}: {preview}")

        if quality_chunks < len(sample_chunks) * 0.5:
            validation_results["issues"].append(
                f"Low chunk quality ({quality_chunks}/{len(sample_chunks)} passed technical content test)"
            )
        else:
            validation_results["strengths"].append(
                f"Good technical chunk quality ({quality_chunks}/{len(sample_chunks)} passed)"
            )

    # ===== TEST 4: SEMANTIC RELATIONSHIPS =====
    print("\n🔗 TEST 4: Semantic Relationships")
    validation_results["max_score"] += 15

    relationships_query = """
    PREFIX ex: <https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/ai-vector-search-users-guide.pdf#>

    SELECT ?relationship (COUNT(*) AS ?rel_count)
    WHERE {
        ?s ?relationship ?o .
        FILTER(STRSTARTS(STR(?relationship), STR(ex:)))
        FILTER(?relationship != ex:hasHeader && ?relationship != ex:hasChunk &&
               ?relationship != ex:hasContent && ?relationship != ex:hasText &&
               ?relationship != ex:hasWordCount && ?relationship != ex:hasCharCount &&
               ?relationship != ex:hasSummary && ?relationship != ex:hasChunkIndex &&
               ?relationship != ex:hasChunkSize && ?relationship != ex:belongsToSection)
    }
    GROUP BY ?relationship
    ORDER BY DESC(?rel_count)
    """

    rel_results = list(g.query(relationships_query))

    total_relationships = sum(int(row[1]) for row in rel_results)  # Fixed: use row[1] for count
    relationship_types = len(rel_results)

    print(f"✓ Total semantic relationships: {total_relationships}")
    print(f"✓ Relationship types: {relationship_types}")

    for row in rel_results:
        rel_name = str(row[0]).split("#")[-1]  # Fixed: use row[0] for relationship
        print(f"  - {rel_name}: {row[1]}")  # Fixed: use row[1] for count

    if total_relationships > 100:
        validation_results["total_score"] += 10
        validation_results["strengths"].append(f"Rich semantic connections ({total_relationships})")
    elif total_relationships > 20:
        validation_results["total_score"] += 5
    else:
        validation_results["issues"].append(f"Few semantic relationships ({total_relationships})")

    if relationship_types >= 3:
        validation_results["total_score"] += 5
        validation_results["strengths"].append(f"Diverse relationship types ({relationship_types})")

    # ===== TEST 5: CHATBOT READINESS =====
    print("\n🤖 TEST 5: Chatbot-Specific Readiness")
    validation_results["max_score"] += 20

    # Check for searchable content
    searchable_chunks_query = """
    PREFIX ex: <https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/ai-vector-search-users-guide.pdf#>
    PREFIX dc: <http://purl.org/dc/elements/1.1/>

    SELECT ?title ?chunk_text
    WHERE {
        ?header dc:title ?title .
        ?header ex:hasChunk ?chunk .
        ?chunk ex:hasText ?chunk_text .
        ?header ex:hasWordCount ?words .
        FILTER(?words > 50)
    }
    LIMIT 20
    """

    searchable_results = list(g.query(searchable_chunks_query))

    # Check for technical content indicators
    technical_terms = ["vector", "embedding", "index", "query", "search", "database", "sql", "function"]
    chunks_with_tech_terms = 0

    for row in searchable_results:
        chunk_text = str(row.chunk_text).lower()
        if any(term in chunk_text for term in technical_terms):
            chunks_with_tech_terms += 1

    tech_coverage = chunks_with_tech_terms / len(searchable_results) if searchable_results else 0

    print(f"✓ Searchable chunks sampled: {len(searchable_results)}")
    print(f"✓ Technical content coverage: {tech_coverage:.1%}")

    if tech_coverage > 0.7:
        validation_results["total_score"] += 10
        validation_results["strengths"].append(f"High technical content coverage ({tech_coverage:.1%})")
    elif tech_coverage > 0.3:
        validation_results["total_score"] += 5
    else:
        validation_results["issues"].append(f"Low technical content coverage ({tech_coverage:.1%})")

    # Check for question-answerable content
    question_indicators = ["how to", "example", "procedure", "step", "guide", "configure", "create", "use"]
    actionable_chunks = 0

    for row in searchable_results:
        chunk_text = str(row.chunk_text).lower()
        if any(indicator in chunk_text for indicator in question_indicators):
            actionable_chunks += 1

    actionable_coverage = actionable_chunks / len(searchable_results) if searchable_results else 0

    print(f"✓ Actionable content coverage: {actionable_coverage:.1%}")

    if actionable_coverage > 0.4:
        validation_results["total_score"] += 10
        validation_results["strengths"].append(f"Good actionable content ({actionable_coverage:.1%})")
    elif actionable_coverage > 0.2:
        validation_results["total_score"] += 5
    else:
        validation_results["issues"].append(f"Limited actionable content ({actionable_coverage:.1%})")

    # ===== FINAL ASSESSMENT =====
    print("\n" + "=" * 50)
    print("🎯 FINAL CHATBOT READINESS ASSESSMENT")
    print("=" * 50)

    score_percentage = (validation_results["total_score"] / validation_results["max_score"]) * 100

    print(
        f"Overall Score: {validation_results['total_score']}/{validation_results['max_score']} ({score_percentage:.1f}%)"
    )

    if score_percentage >= 85:
        grade = "🏆 EXCELLENT"
        recommendation = "Your RDF graph is outstanding for chatbot use!"
    elif score_percentage >= 70:
        grade = "✅ GOOD"
        recommendation = "Your RDF graph is well-suited for chatbot use with minor optimizations."
    elif score_percentage >= 50:
        grade = "⚠️ FAIR"
        recommendation = "Your RDF graph needs some improvements for optimal chatbot performance."
    else:
        grade = "❌ POOR"
        recommendation = "Your RDF graph requires significant improvements before chatbot deployment."

    print(f"Grade: {grade}")
    print(f"Recommendation: {recommendation}")

    if validation_results["strengths"]:
        print(f"\n💪 STRENGTHS:")
        for strength in validation_results["strengths"]:
            print(f"  ✓ {strength}")

    if validation_results["issues"]:
        print(f"\n⚠️ AREAS FOR IMPROVEMENT:")
        for issue in validation_results["issues"]:
            print(f"  • {issue}")

    # Specific chatbot recommendations
    print(f"\n🚀 CHATBOT IMPLEMENTATION RECOMMENDATIONS:")
    print(f"  1. Create embeddings for {chunk_count} chunks using sentence-transformers")
    print(f"  2. Use semantic relationships for context-aware responses")
    print(f"  3. Implement hybrid search (vector + keyword)")
    print(f"  4. Consider chunk re-ranking based on technical relevance")
    print(f"  5. Use section headers for response context and citations")

    return {
        "score": validation_results["total_score"],
        "max_score": validation_results["max_score"],
        "percentage": score_percentage,
        "grade": grade,
        "strengths": validation_results["strengths"],
        "issues": validation_results["issues"],
    }


# Run the validation
if __name__ == "__main__":
    results = validate_chatbot_rdf_graph("vectorsearchuserguide.nt")

    print(f"\n📊 SUMMARY:")
    print(f"Ready for chatbot deployment: {'YES' if results['percentage'] >= 70 else 'NEEDS WORK'}")
