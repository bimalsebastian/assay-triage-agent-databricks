"""Ask a Genie room a question via the Databricks Managed MCP server and print it.

Uses the SAME unified client the app uses (genie_mcp.GenieMCP), so preclinical
and clinical rooms are queried through one interface — pass the space id (or a
second CLI arg) to pick the room.

Env: WORKSPACE_HOST, GENIE_SPACE_ID (default room), GENIE_BEARER (SP or U2M
OAuth token, so queries run as the scoped identity, not personal creds).

Usage:
  python ask.py "Which compounds are currently flagged?"
  python ask.py "How many compounds per correlation state?" <clinical_space_id>
"""
import os
import sys

from genie_mcp import GenieMCP

HOST = os.environ["WORKSPACE_HOST"].rstrip("/")
BEARER = os.environ["GENIE_BEARER"]


def main():
    question = sys.argv[1]
    space_id = sys.argv[2] if len(sys.argv) > 2 else os.environ["GENIE_SPACE_ID"]
    client = GenieMCP(HOST, lambda: BEARER)
    r = client.ask(space_id, question)
    print(f"Q: {question}")
    print(f"room (space): {space_id}")
    print(f"status: {r['status']}")
    if r["sql"]:
        print("generated SQL:\n  " + r["sql"].replace("\n", "\n  "))
    if r["rows"] is not None:
        preview = r["rows"][:6] if isinstance(r["rows"], list) else r["rows"]
        print(f"result rows (up to 6): {preview}")
    if r["text"]:
        print(f"answer: {r['text']}")


if __name__ == "__main__":
    main()
