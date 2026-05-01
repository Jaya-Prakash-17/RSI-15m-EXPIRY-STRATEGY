# GSD & Project Safety Protocol

This document serves as a permanent "memory" for Antigravity and other AI agents to prevent the accidental deletion of critical local infrastructure.

## 🛑 DO NOT DELETE List
The following directories and files are **CRITICAL** for the project's operation and AI "skills":

1.  **.agent/**: Contains the GSD (Get Shit Done) MCP tools, skills, and memory.
2.  **node-local/**: Contains the specific Node.js runtime (`v22.12.0`) required by the MCP scripts.
3.  **.code-review-graph/**: Contains the pre-built knowledge graph for the codebase.
4.  **.env**: Contains local environment variables and API secrets.
5.  **run_gsd.ps1**: The activation script for the GSD environment.

## 🧹 Cleanup Workflow
When the user asks to "clean up" or "remove unwanted files," follow this exact sequence:

1.  **Preview First**: Run `git clean -ndX` to see what would be removed.
2.  **Filter Results**: Manually verify that none of the **Protected Paths** are in the list.
3.  **Execute with Exclusions**: Use the `-e` flag to protect critical paths:
    ```powershell
    git clean -fdX -e .agent/ -e node-local/ -e .env -e .code-review-graph/
    ```
4.  **Confirm**: If in doubt, ask for confirmation before deleting any directory that starts with a dot (`.`).

---
*Last Updated: 2026-05-01*
