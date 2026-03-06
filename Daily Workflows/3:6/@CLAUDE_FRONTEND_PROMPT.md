CLAUDE FRONTEND PROMPT (V2: Coffee & Claude Edition)
Role: Frontend Design Specialist (UI/UX focus only).

Objective: Perform a high-fidelity visual overhaul of the @/components and @/pages directories.

STEP 1: CONTEXT RETRIEVAL (The Coffee Phase) Before starting, read the following files to understand what Codex built and what Antigravity flagged:

Read @CLAUDE_TODO.md (Codex handoff).

Read @DESIGN_DEBT.md (Antigravity visual audit).

Read @architecture.md to ensure the "source of truth" is respected.

CRITICAL BOUNDARY:

DO NOT modify any useEffect, useContext, useQuery, or custom hooks.

DO NOT change API endpoint strings, data fetching logic, or state management architecture.

ONLY refactor the JSX/TSX return statements and Tailwind CSS classes.

Design Directive (2026 Modern Aesthetic):

Layout: Transition to a Bento Box grid with gap-6 spacing and rounded-2xl corners.

Glassmorphism: Use bg-background/60 with backdrop-blur-xl and border-border/50 for all card elements.

Typography: Implement a strict hierarchy using tracking-tight for headers and text-muted-foreground for secondary data.

Micro-interactions: Add framer-motion for subtle enter/exit animations (e.g., initial={{ opacity: 0, scale: 0.95 }}).

Icons: Standardize all iconography using lucide-react.

Task: Start with the main dashboard component identified in the docs. Show me a diff of the UI changes only. If you need to change a prop name to match a new UI component, ask me first.
