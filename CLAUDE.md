# AgenticHR

See [Workflow Requirements](#workflow-requirements) before starting any task.

## Language
- Always respond in Chinese (中文) unless explicitly asked otherwise.

## Workflow Requirements
- For any milestone/feature work (M2.x tasks): ALWAYS follow design-doc-first then TDD. Do not skip to implementation.
- After code changes, run `pnpm test` and `pnpm typecheck` before claiming completion.
- Before merging to master, check for untracked files and uncommitted lockfile changes; stash/clean as needed.

## Core Layer Constraints
- Do not edit files under `core/` without explicit user approval — documented architectural boundary.

## Verification Before Concluding
- When diagnosing API/endpoint/model issues, test ALL plausible endpoint+auth combinations before concluding something is broken or invalid.

<!-- TEAMAGENT:START - 自动管理，请勿手动编辑 -->
## TeamAgent 经验
暂无经验，使用过程中会自动积累。
<!-- TEAMAGENT:END -->
