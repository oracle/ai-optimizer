import json
import os
from dotenv import load_dotenv
import arxiv
from typing import List
from mcp.server.fastmcp import FastMCP
import textwrap

# --- Configuration and Setup ---
load_dotenv()
PAPER_DIR = "papers"
# Initialize FastMCP server with a name
mcp = FastMCP("research")
_paper_cache = {}

# --- Tool Definitions ---

@mcp.tool()
def search_papers(topic: str, max_results: int = 5) -> List[str]:
    """
    Searches for papers on arXiv based on a topic and saves their metadata.
    
    Args:
        topic (str): The topic to search for.
        max_results (int): Maximum number of results to retrieve.
        
    Returns:
        List[str]: A list of the paper IDs found and saved.
    """
    client_arxiv = arxiv.Client()
    search = arxiv.Search(
        query=topic,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance
    )
    papers = list(client_arxiv.results(search))
    
    if not papers:
        # It's good practice to print feedback on the server side
        print(f"Server: No papers found for topic '{topic}'")
        return []

    path = os.path.join(PAPER_DIR, topic.lower().replace(" ", "_"))
    os.makedirs(path, exist_ok=True)
    file_path = os.path.join(path, "papers_info.json")

    try:
        with open(file_path, "r") as json_file:
            papers_info = json.load(json_file)
    except (FileNotFoundError, json.JSONDecodeError):
        papers_info = {}

    paper_ids = []
    for paper in papers:
        paper_id = paper.get_short_id()
        paper_ids.append(paper_id)
        papers_info[paper_id] = {
            'title': paper.title,
            'authors': [author.name for author in paper.authors],
            'summary': paper.summary,
            'pdf_url': paper.pdf_url,
            'published': str(paper.published.date())
        }
    
    with open(file_path, "w") as json_file:
        json.dump(papers_info, json_file, indent=2)
    
    print(f"Server: Saved {len(paper_ids)} papers to {file_path}")
    return paper_ids

@mcp.tool()
def extract_info(paper_id: str) -> str:
    """
    Retrieves saved information for a specific paper ID from all topics.
    Uses an in-memory cache for performance.
    
    Args:
        paper_id (str): The ID of the paper to look for.
        
    Returns:
        str: JSON string with paper information if found, else an error message.
    """
    # 1. First, check the cache for an exact match
    if paper_id in _paper_cache:
        return json.dumps(_paper_cache[paper_id], indent=2)

    # 2. If not in cache, perform the expensive file search (your original logic)
    for item in os.listdir(PAPER_DIR):
        item_path = os.path.join(PAPER_DIR, item)
        if os.path.isdir(item_path):
            file_path = os.path.join(item_path, "papers_info.json")
            if os.path.isfile(file_path):
                try:
                    with open(file_path, "r") as json_file:
                        papers_info = json.load(json_file)
                        
                        # Search logic (can be simplified if we populate cache first)
                        for key, value in papers_info.items():
                            # Add every paper from this file to the cache to avoid re-reading this file
                            if key not in _paper_cache:
                                _paper_cache[key] = value

                except (FileNotFoundError, json.JSONDecodeError):
                    continue

    # 3. Now that the cache is populated from relevant files, check again.
    # This handles version differences as well.
    if paper_id in _paper_cache:
        return json.dumps(_paper_cache[paper_id], indent=2)

    base_id = paper_id.split('v')[0]
    for key, value in _paper_cache.items():
        if key.startswith(base_id):
            return json.dumps(value, indent=2)

    return f"Error: No saved information found for paper ID {paper_id}."

# --- Resource Definitions ---

@mcp.resource("papers://folders")
def get_available_folders() -> str:
    """Lists all available topic folders that contain saved paper information."""
    print(f"Server: Listing available topic folders in {PAPER_DIR}")
    folders = []
    if os.path.exists(PAPER_DIR):
        for topic_dir in os.listdir(PAPER_DIR):
            if os.path.isdir(os.path.join(PAPER_DIR, topic_dir)):
                folders.append(topic_dir)
    
    content = "# Available Research Topics\n\n"
    if folders:
        content += "You can retrieve info for any of these topics using `@<topic_name>`.\n\n"
        for folder in folders:
            content += f"- `{folder}`\n"
    else:
        content += "No topic folders found. Use `search_papers` to create one."
    print(f"Server: Found {len(folders)} topic folders.")
    return content

@mcp.resource("papers://{topic}")
def get_topic_papers(topic: str) -> str:
    """Gets detailed information about all saved papers for a specific topic."""
    print(f"Server: Retrieving papers for topic '{topic}'")
    topic_dir = topic.lower().replace(" ", "_")
    papers_file = os.path.join(PAPER_DIR, topic_dir, "papers_info.json")
    
    if not os.path.exists(papers_file):
        return f"# No papers found for topic: {topic}"
    
    with open(papers_file, 'r') as f:
        papers_data = json.load(f)
    
    content = f"# Papers on {topic.replace('_', ' ').title()}\n\n"
    for paper_id, info in papers_data.items():
        content += f"## {info['title']} (`{paper_id}`)\n"
        content += f"- **Authors**: {', '.join(info['authors'])}\n"
        content += f"- **Summary**: {info['summary'][:200]}...\n---\n"
    print(f"Server: Found {len(papers_data)} papers for topic '{topic}'")
    return content

# --- Prompt Definition ---

@mcp.prompt()
def generate_search_prompt(topic: str) -> str:
    """Generates a system prompt to guide an AI in researching a topic."""
    return textwrap.dedent(f"""
        You are a research assistant. Your goal is to provide a comprehensive overview of a topic.
        When asked about '{topic}', follow these steps:
        1. Use the `search_papers` tool to find relevant papers.
        2. For each paper ID returned, use the `extract_info` tool to get its details.
        3. Synthesize the information from all papers into a cohesive summary.
        4. Present the key findings, common themes, and any differing conclusions.
        Do not present the raw JSON. Format the final output for readability.
    """)

# --- Main Execution Block ---

if __name__ == "__main__":
    # This is the original, simple, and correct way to run the server.
    # It will not crash.
    print("Research MCP Server running on stdio...")
    mcp.run(transport='stdio')
