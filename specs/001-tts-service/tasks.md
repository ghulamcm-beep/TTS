# Tasks: TTS Service

**Input**: Design documents from `/specs/001-tts-service/`
**Prerequisites**: spec.md (required), plan.md (required)

**Tests**: Included for production reliability

**Organization**: Tasks grouped by user story for independent implementation

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Create project structure per plan.md (src/tts/, tests/, models/)
- [X] T002 [P] Initialize Python project with requirements.txt (pymongo, nats-py, sounddevice, pydantic, pytest)
- [X] T003 [P] Create Dockerfile for TTS service (Python 3.11, PulseAudio, sounddevice deps)
- [X] T004 [P] Create docker-compose.yml (MongoDB, NATS, PulseAudio services)
- [X] T005 [P] Configure pytest with asyncio support (pytest.ini)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T006 [P] Create config.py with environment variables (MONGODB_URI, NATS_URI, PULSE_SERVER, VIRTUAL_MIC, PIPER_MODEL_PATH)
- [X] T007 [P] Create models/tts_queue.py with Pydantic schema (TTSQueueDocument class)
- [X] T008 Setup MongoDB connection with change stream support
- [X] T009 Setup NATS connection with subscription support
- [X] T010 Create logging infrastructure (structured JSON logging)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - TTS Queue Processing (Priority: P1) 🎯 MVP

**Goal**: Listen to MongoDB queue, synthesize speech, play audio

**Independent Test**: Insert document → Audio plays → Status updates

### Tests for User Story 1

- [X] T011 [P] [US1] Contract test: MongoDB schema validation in tests/contract/test_mongodb_schema.py
- [X] T012 [P] [US1] Integration test: Queue insert triggers synthesis in tests/integration/test_queue_to_audio.py

### Implementation for User Story 1

- [X] T013 [P] [US1] Create src/tts/synthesizer.py (Piper subprocess manager, auto-start, auto-restart)
- [X] T014 [P] [US1] Create src/tts/audio_player.py (sounddevice OutputStream wrapper, play/stop methods)
- [X] T015 [US1] Create src/tts/tts_queue.py (MongoDB change stream listener, text extraction)
- [X] T016 [US1] Create src/tts/status_updater.py (MongoDB status updates: pending→playing→completed)
- [X] T017 [US1] Create src/tts/main.py (service entry point, orchestrate queue→synth→playback)
- [X] T018 [US1] Add error handling for Piper crashes, MongoDB errors

**Checkpoint**: US1 complete - Can insert text into MongoDB and hear audio from virtual_mic

---

## Phase 4: User Story 2 - Interruption via NATS (Priority: P1)

**Goal**: Stop audio within 50ms of NATS interrupt signal

**Independent Test**: TTS speaking → Publish interrupt → Audio stops <50ms

### Tests for User Story 2

- [X] T019 [P] [US2] Contract test: NATS message format in tests/contract/test_nats_protocol.py
- [X] T020 [P] [US2] Integration test: Interrupt stops audio in tests/integration/test_interruption_flow.py
- [X] T021 [US2] Unit test: Interrupt handler sets stop event in tests/unit/test_interrupt_handler.py

### Implementation for User Story 2

- [X] T022 [P] [US2] Create src/tts/interrupt_handler.py (NATS subscriber, asyncio.Event for stop signal)
- [X] T023 [US2] Modify audio_player.py to support instant stop (check interrupt event during playback)
- [X] T024 [US2] Modify main.py to handle interrupt during synthesis (cancel Piper output)
- [X] T025 [US2] Update status_updater.py to set status=interrupted on interrupt

**Checkpoint**: US2 complete - Interruption works with <50ms latency

---

## Phase 5: User Story 3 - Status Updates (Priority: P2)

**Goal**: Track TTS lifecycle in MongoDB with timestamps

**Independent Test**: Query document → Observe status transitions

### Tests for User Story 3

- [X] T026 [P] [US3] Unit test: Status updater sets correct timestamps in tests/unit/test_status_updater.py

### Implementation for User Story 3

- [X] T027 [US3] Enhance status_updater.py with all transitions (pending, playing, completed, interrupted, failed)
- [X] T028 [US3] Add timestamp fields (started_at, completed_at, interrupted_at)
- [X] T029 [US3] Add error_message field for failed status
- [X] T030 [US3] Add logging for all status transitions

**Checkpoint**: US3 complete - Full observability of TTS lifecycle

---

## Phase 6: User Story 4 - Piper Model Management (Priority: P2)

**Goal**: Robust Piper subprocess lifecycle management

**Independent Test**: Kill Piper → Auto-restart → Next synthesis succeeds

### Tests for User Story 4

- [X] T031 [P] [US4] Unit test: Piper auto-restart on crash in tests/unit/test_synthesizer.py

### Implementation for User Story 4

- [X] T032 [US4] Enhance synthesizer.py with crash detection (monitor exit code, stdout closed)
- [X] T033 [US4] Add Piper health check before synthesis (ping subprocess)
- [X] T034 [US4] Implement retry logic (max 3 retries on Piper failure)
- [X] T035 [US4] Add timeout handling (first chunk timeout 10s, next chunk timeout 0.5s)

**Checkpoint**: US4 complete - Piper robust against crashes and timeouts

---

## Phase 7: User Story 5 - Error Handling & Recovery (Priority: P3)

**Goal**: Graceful recovery from infrastructure failures

**Independent Test**: Simulate failures → Service recovers automatically

### Tests for User Story 5

- [X] T036 [P] [US5] Integration test: MongoDB reconnection in tests/integration/test_error_recovery.py
- [X] T037 [P] [US5] Integration test: NATS reconnection in tests/integration/test_error_recovery.py

### Implementation for User Story 5

- [X] T038 [US5] Add MongoDB reconnection logic (exponential backoff, max 5 retries)
- [X] T039 [US5] Add NATS reconnection logic (max_retries config)
- [X] T040 [US5] Add PulseAudio device detection (fail gracefully if virtual_mic unavailable)
- [X] T041 [US5] Create error reporting (log all errors with context, update status=failed)

**Checkpoint**: US5 complete - Production-ready error recovery

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final improvements and documentation

- [X] T042 [P] Create README.md with setup instructions
- [X] T043 [P] Add .env.example file with all environment variables
- [X] T044 [P] Create models download script (download Piper model on first run)
- [ ] T045 Code cleanup and refactoring
- [ ] T046 [P] Add Prometheus metrics endpoint (optional, for monitoring)
- [X] T047 [P] Run full integration test suite
- [ ] T048 [P] Verify Docker build succeeds
- [X] T049 [P] Document NATS protocol for other services
- [X] T050 [P] Document MongoDB schema for other services

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Phase 1 - BLOCKS all user stories
- **User Stories (Phase 3-7)**: All depend on Phase 2 completion
- **Polish (Phase 8)**: Depends on all user stories

### User Story Dependencies

- **US1 (P1)**: Foundation complete → Can implement independently
- **US2 (P1)**: Foundation complete → Can implement in parallel with US1
- **US3 (P2)**: US1 complete → Integrates with queue processing
- **US4 (P2)**: US1 complete → Enhances synthesizer
- **US5 (P3)**: All above complete → Cross-cutting concern

### Within Each User Story

- Tests before implementation (TDD)
- Models before services
- Services before main orchestration
- Core implementation before error handling

### Parallel Opportunities

- Phase 1: All tasks marked [P] can run in parallel
- Phase 2: All tasks marked [P] can run in parallel
- US1 & US2: Can be developed in parallel by different developers
- Tests within a story marked [P] can run in parallel

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: US1
4. **STOP and VALIDATE**: Insert document → Hear audio
5. Deploy if ready

### Incremental Delivery

1. Foundation → US1 → Test → Deploy (MVP: text→speech)
2. US2 → Test → Deploy (Interruption support)
3. US3 → Test → Deploy (Status tracking)
4. US4 → Test → Deploy (Piper robustness)
5. US5 → Test → Deploy (Error recovery)

### Critical Path

```
Phase 1 → Phase 2 → US1 → US2 → Production Ready
                         ↓
                    US3, US4, US5 (polish)
```

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story
- Each user story independently testable
- Verify tests fail before implementing
- Commit after each task
- Stop at checkpoints to validate
- Docker build must succeed before merge
