# Mirae Guides — For AI Agents

> **If you are Kimi Code, Claude Code, or any AI assistant setting up this project:**
> Read these files in order. They contain the complete knowledge base for the Mirae OpenClaw zero-token deployment.

## File Index

| #   | File                    | Purpose                                           | Read When...                  |
| --- | ----------------------- | ------------------------------------------------- | ----------------------------- |
| 00  | `00-DEPLOYMENT.md`      | Complete setup guide for new VPS                  | Setting up from scratch       |
| 01  | `01-SOUL.md`            | Bot personality + tool calling rules              | Understanding bot behavior    |
| 02  | `02-AGENTS.md`          | System rules + restart procedures + patch history | Maintenance & troubleshooting |
| 03  | `03-PATCH_HISTORY.md`   | Consolidated patch notes v1-v15                   | Understanding what was fixed  |
| 04  | `04-TROUBLESHOOTING.md` | Common issues and fixes                           | Something is broken           |
| 05  | `05-SETUP_CHECKLIST.md` | Quick copy-paste checklist                        | New VPS deployment            |

## Quick Start for Another Agent

1. Clone: `git clone https://github.com/dextee/Mirae.git`
2. Read `00-DEPLOYMENT.md` Section 2: "What to Replace for Your Own Bot/Server"
3. Read `01-SOUL.md` to understand the bot's rules
4. Follow `05-SETUP_CHECKLIST.md` for step-by-step setup

## Critical Paths (Memorize These)

| Path                                                               | Purpose                                      |
| ------------------------------------------------------------------ | -------------------------------------------- |
| `/root/openclaw-zero-token/`                                       | Project root                                 |
| `/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json` | Active config                                |
| `/root/.openclaw/workspace/`                                       | Bot workspace (SOUL.md, AGENTS.md live here) |
| `/root/.openclaw/workspace/leads/`                                 | Lead CSV output                              |
| `/opt/searxng/`                                                    | SearXNG installation                         |
| `/root/.config/chrome-openclaw-debug/`                             | Chrome profile with auth cookies             |

## Source of Truth

These guides are maintained in the `guides/` folder of `https://github.com/dextee/Mirae`.
Last updated: 2026-04-24
