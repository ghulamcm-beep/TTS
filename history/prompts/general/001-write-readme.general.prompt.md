---
id: 001
title: Write README for TTS Service
stage: general
date: 2026-02-24
surface: agent
model: claude-sonnet-4-6
feature: none
branch: 11
user: architext
command: (conversational — "my readme is empty")
labels: ["documentation","readme","tts"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - README.md
tests:
  - none
---

## Prompt

my readme is empty

## Response snapshot

Explored the project codebase to understand the TTS microservice architecture, tech stack, and operational details. Wrote a comprehensive README.md covering:
- Architecture diagram (MongoDB → ElevenLabs → PulseAudio + NATS interrupt)
- Quick start with Docker Compose
- Full environment variable reference table
- Local development setup with uv
- Key design decisions (streaming-first, Change Streams, NATS interrupts, GridFS caching, graceful degradation)
- Tech stack summary

## Outcome

- ✅ Impact: README.md populated from empty to production-ready documentation
- 🧪 Tests: none
- 📁 Files: README.md
- 🔁 Next prompts: add badges (CI, Docker, license), add contributing guide, expand architecture section with sequence diagram
- 🧠 Reflection: Codebase exploration via subagent was effective for gathering all details needed to write accurate documentation without guessing

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): add shields.io badges for Python version, Docker, and license
