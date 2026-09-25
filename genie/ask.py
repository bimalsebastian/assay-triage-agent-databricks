"""Ask Genie One a question via the Databricks Genie One MCP server and print it.

Genie One is a SINGLE workspace-wide MCP endpoint (/api/2.0/mcp/genie) that
routes each natural-language question to the right data itself — there is no
Genie space to pick. Uses the same client the app uses (genie_mcp.GenieOneMCP).

Env: WORKSPACE_HOST, GENIE_BEARER (SP or U2M OAuth token — Unity Catalog scopes
the answer to what that identity may access).

Usage:
  python ask.py "Which compounds are flagged, and do any correlate clinically?"
"""
import os
import sys

from genie_mcp import GenieOneMCP

HOST = os.environ["WORKSPACE_HOST"].rstrip("/")
BEARER = os.environ["GENIE_BEARER"]


def main():
    question = sys.argv[1]
    client = GenieOneMCP(HOST, lambda: BEARER)
    r = client.ask(question)
    print(f"Q: {question}")
    print(f"status: {r['status']}")
    if r.get("text"):
        print("answer:\n" + r["text"])
    if r.get("deep_link"):
        print(f"\nopen in Genie One: {r['deep_link']}")


if __name__ == "__main__":
    main()
