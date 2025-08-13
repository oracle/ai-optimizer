def register(mcp, auth):
    @mcp.tool()
    @auth.get("/hello", operation_id="say_hello")
    def greet(name: str = "World") -> str:
        """Say hello to someone."""
        return f"Hello, {name}!"
