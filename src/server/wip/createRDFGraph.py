# Code to construct an RDF Graph from ai-vector-search-users-guide.pdf
import PyPDF2
import re
from rdflib import Graph, URIRef, Literal, Namespace
from urllib.parse import quote
from difflib import SequenceMatcher

# Define namespaces
EX = Namespace("https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/ai-vector-search-users-guide.pdf#")
DC = Namespace("http://purl.org/dc/elements/1.1/")

# Load PDF
pdf_file = "UPDATE ME Local location of ai-vector-search-users-guide.pdf"
reader = PyPDF2.PdfReader(pdf_file)

# Create RDF graph
g = Graph()
g.bind("ex", EX)
g.bind("dc", DC)

# Step 1: Find the TOC page(s) - SAME AS BEFORE
toc_start = None
for i, page in enumerate(reader.pages):
    text = page.extract_text()
    if "Contents" in text:
        toc_start = i
        break

if toc_start is None:
    raise ValueError("Table of Contents not found in PDF.")

print(f"Found TOC at page {toc_start + 1}")

toc_lines = []
glossary_found = False

for i in range(toc_start, toc_start + 10):
    if i >= len(reader.pages):
        break
    text = reader.pages[i].extract_text()
    if not text:
        continue
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    start = 0
    for j, line in enumerate(lines):
        if "Contents" in line:
            start = j + 1
            break
    for line in lines[start:]:
        if "Glossary" in line and not glossary_found:
            glossary_found = True
            break
        elif glossary_found:
            break
        toc_lines.append(line)
    if glossary_found:
        break

print(f"Extracted {len(toc_lines)} TOC lines (up to but not including Glossary)")
headers = []
for line in toc_lines:
    cleaned = re.sub(r"^\s*\d+\s+", "", line)
    cleaned = re.sub(r"\s*[\d-]+\s*$", "", cleaned)
    cleaned = cleaned.strip()
    if cleaned:
        headers.append(cleaned)

print(f"Headers found: {headers}")


# IMPROVED CONTENT EXTRACTION FUNCTION
def improved_extract_section_content(reader, headers):
    """Extract content with much better header matching strategies"""
    print("\n=== IMPROVED Content Extraction ===")

    sections = {}

    # Extract all text from PDF
    print("Extracting all PDF text...")
    full_text = ""

    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text()
            if text:
                full_text += f"\n{text.strip()}"
        except Exception as e:
            print(f"Error extracting page {i + 1}: {e}")

    print(f"Total text length: {len(full_text):,} characters")

    # Helper functions
    def create_header_variations(header):
        variations = []
        variations.append(header)
        variations.append(header.lower())

        # Remove "About" prefix
        no_about = re.sub(r"^about\s+", "", header, flags=re.IGNORECASE)
        if no_about != header:
            variations.append(no_about)
            variations.append(no_about.lower())

        # Remove common words
        clean_header = re.sub(r"\b(the|a|an|and|or|of|in|on|at|to|for|with|by)\b", " ", header.lower())
        clean_header = re.sub(r"\s+", " ", clean_header).strip()
        variations.append(clean_header)

        # Key words only
        key_words = re.findall(r"\b\w{4,}\b", header.lower())
        if key_words:
            variations.append(" ".join(key_words))

        # First few words
        words = header.split()
        if len(words) > 1:
            variations.append(" ".join(words[:3]))
            variations.append(" ".join(words[:2]))

        # Remove duplicates
        unique_variations = []
        for v in variations:
            if v and v not in unique_variations:
                unique_variations.append(v)

        return unique_variations

    # Process each header
    print(f"\nProcessing {len(headers)} headers...")

    for i, header in enumerate(headers):
        print(f"\nHeader {i + 1}/{len(headers)}: '{header}'")

        variations = create_header_variations(header)
        best_content = ""
        best_score = 0

        # Try each variation
        for variation in variations:
            if len(variation) < 3:
                continue

            pattern = re.escape(variation)
            matches = list(re.finditer(pattern, full_text, re.IGNORECASE))

            for match in matches:
                start_pos = match.start()
                end_pos = min(start_pos + 2000, len(full_text))

                content_after = full_text[match.end() : end_pos]

                # Find natural break point
                lines = content_after.split("\n")
                natural_end = len(content_after)

                for j, line in enumerate(lines[2:], 2):
                    line = line.strip()
                    if (
                        len(line) > 10
                        and (line[0].isupper() or line[0].isdigit())
                        and not line.endswith(".")
                        and len(line.split()) < 10
                    ):
                        natural_end = sum(len(lines[k]) + 1 for k in range(j))
                        break

                section_content = content_after[:natural_end].strip()

                if len(section_content) > 50:  # Lower threshold
                    score = len(section_content) + (1000 - start_pos) / 1000

                    if score > best_score:
                        best_score = score
                        best_content = section_content

        # Fuzzy matching if nothing found
        if not best_content:
            paragraphs = [p.strip() for p in full_text.split("\n\n") if len(p.strip()) > 30]
            key_terms = re.findall(r"\b\w{3,}\b", header.lower())  # Lower threshold: 3+ chars

            for paragraph in paragraphs[:50]:
                if len(key_terms) == 0:
                    continue

                paragraph_lower = paragraph.lower()
                matches = sum(1 for term in key_terms if term in paragraph_lower)

                if matches >= max(1, len(key_terms) // 3):  # Even more lenient
                    score = matches * 10 + len(paragraph) / 100

                    if score > best_score:
                        best_score = score
                        best_content = paragraph

        # Store result
        if best_content:
            # Clean content
            best_content = re.sub(r"\n\s*\n", "\n\n", best_content)
            best_content = best_content.strip()
            sections[header] = best_content
            print(f"  ✅ SUCCESS: {len(best_content)} characters")
        else:
            sections[header] = ""
            print(f"  ❌ FAILED: No content found")

    successful = sum(1 for content in sections.values() if content)
    print(f"\n=== EXTRACTION SUMMARY ===")
    print(f"Successful: {successful}/{len(headers)}")
    print(f"Total chars: {sum(len(content) for content in sections.values()):,}")

    return sections


# Extract content using improved method
sections = improved_extract_section_content(reader, headers)

# Add headers and content to RDF
print("\n=== Adding to RDF Graph ===")
for header in headers:
    safe_header = quote(header.replace(" ", "_"), safe="")
    header_uri = EX[f"TOC_Header_{safe_header}"]

    g.add((EX.Document, EX.hasHeader, header_uri))
    g.add((header_uri, DC.title, Literal(header)))

    content = sections.get(header, "")
    if content:
        g.add((header_uri, EX.hasContent, Literal(content)))
        g.add((header_uri, EX.hasWordCount, Literal(len(content.split()))))
        g.add((header_uri, EX.hasCharCount, Literal(len(content))))

        summary = content[:200] + "..." if len(content) > 200 else content
        g.add((header_uri, EX.hasSummary, Literal(summary)))
        print(f"✓ Added content for: {header}")
    else:
        g.add((header_uri, EX.hasContent, Literal("")))
        g.add((header_uri, EX.hasWordCount, Literal(0)))


# Create chunks with LOWER threshold
def create_content_chunks(sections, max_chunk_size=1000):
    print("\n=== Creating Content Chunks ===")

    chunks = {}
    total_chunks = 0

    for header, content in sections.items():
        if not content or len(content) < 30:  # MUCH lower threshold
            continue

        sentences = re.split(r"[.!?]+", content)
        header_chunks = []
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(current_chunk) + len(sentence) > max_chunk_size and current_chunk:
                header_chunks.append(current_chunk.strip())
                current_chunk = sentence
            else:
                current_chunk += " " + sentence if current_chunk else sentence

        if current_chunk.strip():
            header_chunks.append(current_chunk.strip())

        chunks[header] = header_chunks
        total_chunks += len(header_chunks)

        print(f"  {header}: {len(header_chunks)} chunks")

        # Add chunks to RDF
        safe_header = quote(header.replace(" ", "_"), safe="")
        header_uri = EX[f"TOC_Header_{safe_header}"]

        for i, chunk in enumerate(header_chunks):
            chunk_uri = EX[f"Chunk_{safe_header}_{i}"]
            g.add((header_uri, EX.hasChunk, chunk_uri))
            g.add((chunk_uri, EX.hasText, Literal(chunk)))
            g.add((chunk_uri, EX.hasChunkIndex, Literal(i)))
            g.add((chunk_uri, EX.hasChunkSize, Literal(len(chunk))))
            g.add((chunk_uri, EX.belongsToSection, header_uri))

    print(f"Total content chunks created: {total_chunks}")
    return chunks


# Create chunks
content_chunks = create_content_chunks(sections)


# Create sophisticated semantic relationships
def create_semantic_relationships():
    """Create relationships based on content similarity and mentions"""
    print("\n=== Creating Semantic Relationships ===")

    # First, let's see what headers we actually have
    print("Available headers:")
    for i, header in enumerate(headers):
        print(f"  {i}: {header}")

    # Define comprehensive relationship patterns for Oracle Vector Search docs
    relationship_patterns = {
        "prerequisite": [
            (r"overview of oracle ai vector search", r"get started"),
            (r"why use oracle ai vector search", r"get started"),
            (r"get started", r"generate vector embeddings"),
            (r"oracle ai database release updates", r"get started"),
            (r"conventions", r"overview of oracle ai vector search"),
            (r"preface", r"overview"),
            (r"introduction", r"get started"),
            (r"what.*new", r"get started"),
            (r"install", r"configur"),
            (r"setup", r"configur"),
            (r"basic", r"advanced"),
            (r"fundamental", r"advance"),
        ],
        "related": [
            (r"vector", r"search"),
            (r"vector", r"index"),
            (r"index", r"query"),
            (r"performance", r"tuning"),
            (r"performance", r"optimiz"),
            (r"security", r"authentication"),
            (r"sql", r"query"),
            (r"api", r"function"),
            (r"vector", r"embed"),
            (r"embed", r"store"),
            (r"store", r"index"),
            (r"index", r"search"),
            (r"search", r"query"),
            (r"query", r"hybrid"),
            (r"hybrid", r"rag"),
            (r"sql", r"function"),
            (r"pl/sql", r"package"),
            (r"generate", r"example"),
            (r"similarity", r"distance"),
            (r"accuracy", r"precision"),
            (r"memory", r"pool"),
            (r"parallel", r"performance"),
            (r"batch", r"bulk"),
            (r"load", r"import"),
            (r"export", r"backup"),
            (r"monitor", r"performance"),
            (r"troubleshoot", r"debug"),
            (r"error", r"exception"),
            (r"view", r"table"),
            (r"column", r"datatype"),
            (r"dimension", r"embedding"),
            (r"cluster", r"partition"),
        ],
        "part_of": [
            (r"about vector generation", r"generate vector embeddings"),
            (r"about sql functions to generate embeddings", r"generate vector embeddings"),
            (r"about pl/sql packages to generate embeddings", r"generate vector embeddings"),
            (r"about chainable utility functions and common use cases", r"generate vector embeddings"),
            (r"about vector helper procedures", r"generate vector embeddings"),
            (r"about in-memory neighbor graph vector index", r"create vector indexes and hybrid vector indexes"),
            (r"about neighbor partition vector index", r"create vector indexes and hybrid vector indexes"),
            (r"guidelines for using vector indexes", r"create vector indexes and hybrid vector indexes"),
            (r"v\$vector_index", r"vector index and hybrid vector index views"),
            (r"v\$vector_memory_pool", r"vector memory pool views"),
            (r"example.*vector", r"vector.*example"),
            (r"syntax.*sql", r"sql.*reference"),
            (r"parameter.*function", r"function.*reference"),
            (r"procedure.*pl/sql", r"pl/sql.*package"),
            (r"error.*code", r"troubleshooting"),
            (r"best.*practice", r"guideline"),
            (r"performance.*tip", r"optimization"),
            (r"security.*consideration", r"security"),
        ],
        "implements": [
            (r"example", r"concept"),
            (r"tutorial", r"concept"),
            (r"how.*to", r"procedure"),
            (r"step.*by.*step", r"procedure"),
            (r"walkthrough", r"procedure"),
            (r"demonstration", r"example"),
        ],
        "references": [
            (r"syntax", r"reference"),
            (r"parameter", r"reference"),
            (r"specification", r"reference"),
            (r"api.*reference", r"function"),
            (r"view.*reference", r"system.*view"),
        ],
    }

    relationships_created = 0

    # Analyze header pairs for relationships
    print("\nAnalyzing header pairs...")
    for i, header1 in enumerate(headers):
        for j, header2 in enumerate(headers):
            if i >= j:  # Avoid duplicates and self-references
                continue

            header1_lower = header1.lower()
            header2_lower = header2.lower()

            # Check for relationship patterns
            for rel_type, patterns in relationship_patterns.items():
                for pattern1, pattern2 in patterns:
                    match1_in_h1 = re.search(pattern1, header1_lower)
                    match2_in_h2 = re.search(pattern2, header2_lower)
                    match2_in_h1 = re.search(pattern2, header1_lower)
                    match1_in_h2 = re.search(pattern1, header2_lower)

                    if (match1_in_h1 and match2_in_h2) or (match2_in_h1 and match1_in_h2):
                        uri1 = EX[f"TOC_Header_{quote(header1.replace(' ', '_'), safe='')}"]
                        uri2 = EX[f"TOC_Header_{quote(header2.replace(' ', '_'), safe='')}"]

                        if rel_type == "prerequisite":
                            if match1_in_h1 and match2_in_h2:
                                g.add((uri1, EX.prerequisiteFor, uri2))
                                relationships_created += 1
                                print(f"  ✓ Prerequisite: '{header1}' prerequisite for '{header2}'")
                            else:
                                g.add((uri2, EX.prerequisiteFor, uri1))
                                relationships_created += 1
                                print(f"  ✓ Prerequisite: '{header2}' prerequisite for '{header1}'")
                        elif rel_type in ["implements", "references"]:
                            # Directional relationships
                            if match1_in_h1 and match2_in_h2:
                                g.add((uri1, EX[rel_type], uri2))
                                relationships_created += 1
                                print(f"  ✓ {rel_type.title()}: '{header1}' {rel_type} '{header2}'")
                            else:
                                g.add((uri2, EX[rel_type], uri1))
                                relationships_created += 1
                                print(f"  ✓ {rel_type.title()}: '{header2}' {rel_type} '{header1}'")
                        else:
                            # Symmetric relationships (related, part_of)
                            g.add((uri1, EX[rel_type], uri2))
                            g.add((uri2, EX[rel_type], uri1))
                            relationships_created += 2
                            print(f"  ✓ {rel_type.title()}: '{header1}' <-> '{header2}'")

                        break  # Don't create multiple relationships of same type between same headers

    # Also add content-based relationships for sections with actual content
    print("\nAdding content-based relationships...")
    content_relationships = 0

    for i, header1 in enumerate(headers):
        for j, header2 in enumerate(headers):
            if i >= j:
                continue

            content1 = sections.get(header1, "").lower()
            content2 = sections.get(header2, "").lower()

            if len(content1) < 100 or len(content2) < 100:
                continue

            # Find mentions of header2 concepts in header1 content and vice versa
            header1_terms = set(re.findall(r"\b\w{4,}\b", header1.lower()))
            header2_terms = set(re.findall(r"\b\w{4,}\b", header2.lower()))

            # Check if header1 content mentions header2 terms
            h2_mentions_in_h1 = sum(1 for term in header2_terms if term in content1)
            h1_mentions_in_h2 = sum(1 for term in header1_terms if term in content2)

            if h2_mentions_in_h1 >= 2 or h1_mentions_in_h2 >= 2:
                uri1 = EX[f"TOC_Header_{quote(header1.replace(' ', '_'), safe='')}"]
                uri2 = EX[f"TOC_Header_{quote(header2.replace(' ', '_'), safe='')}"]
                g.add((uri1, EX.mentions, uri2))
                g.add((uri2, EX.mentions, uri1))
                content_relationships += 2
                print(f"  ✓ Mentions: '{header1}' <-> '{header2}' (content cross-reference)")

    print(f"\nTotal pattern-based relationships created: {relationships_created}")
    print(f"Total content-based relationships created: {content_relationships}")
    print(f"Grand total relationships: {relationships_created + content_relationships}")

    return relationships_created + content_relationships


# Execute the comprehensive relationship creation
if headers:
    create_semantic_relationships()

# Save results
g.serialize("vectorsearchuserguide.nt", format="nt")
print(f"\nRDF triples written to vectorsearchuserguide.nt")
print(f"Total triples: {len(g)}")

# Final summary
successful_sections = sum(1 for content in sections.values() if content)
total_chunks = sum(len(chunks) for chunks in content_chunks.values())
total_content = sum(len(content) for content in sections.values())

print(f"\n=== FINAL RESULTS ===")
print(f"Headers processed: {len(headers)}")
print(f"Sections with content: {successful_sections}")
print(f"Total content chunks: {total_chunks}")
print(f"Total content: {total_content:,} characters")
print(f"RDF triples: {len(g)}")

if total_chunks > 0:
    print("🎉 SUCCESS! You now have chunks for your chatbot!")
else:
    print("❌ Still no chunks created. The PDF might have unusual formatting.")
    print("Consider manually inspecting the PDF text structure.")
