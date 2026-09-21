# Project Guidelines

- **Architecture Documentation Maintenance:** Whenever the program's core architecture, workflow, or important AI processes are changed, you must automatically update the `project_process_summary.md` file located at the root of the project (`c:\AI\gw_ai\project_process_summary.md`) to reflect the latest changes.
- **Attachment Parsing Accuracy Preservation:** The current logic in `processor.py` for parsing attachments (especially dropping empty rows/columns and converting Excel to Markdown tables) has achieved high accuracy. You must STRICTLY PRESERVE this logic. If the user requests any modifications that might negatively impact this accuracy, you MUST proactively warn the user and seek explicit confirmation before proceeding.
