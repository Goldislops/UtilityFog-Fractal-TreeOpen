
# SpecKit Framework

This directory contains the complete specification-driven development framework for the UtilityFog-Fractal-TreeOpen project.

## Workflow Methodology

Our development follows a systematic **Specify → Plan → Tasks → Implement** approach:

### 1. **Specify** (`*.spec.md`)
- Complete feature specifications with clear requirements
- User stories and acceptance criteria
- Technical constraints and dependencies
- Success metrics and validation criteria

### 2. **Plan** (`plan.*.md`)
- Technical implementation strategy
- Architecture decisions and trade-offs
- Resource requirements and timeline
- Risk assessment and mitigation

### 3. **Tasks** (`tasks.*.md`)
- Granular, actionable tasks with unique IDs
- Clear acceptance criteria for each task
- Dependencies and priority ordering
- Effort estimates and assignee guidance

### 4. **Implement**
- Create GitHub issues from tasks using templates
- Link PRs to specific Task IDs in commit messages
- Validate implementation against acceptance criteria
- Maintain traceability from spec to code

## Document Structure

```
specs/
├── SPEC_README.md              # This methodology guide
├── {feature-name}.spec.md      # Feature specifications
├── plan.{feature-name}.md      # Implementation plans
└── tasks.{feature-name}.md     # Granular task breakdowns
```

## Cross-References

All documents are cross-linked for full traceability:
- Specs reference their corresponding plans and tasks
- Plans reference back to specs and forward to tasks
- Tasks reference both specs and plans
- GitHub issues/PRs reference Task IDs

## Validation

The SpecKit validation CI automatically:
- Validates task structure and formatting
- Checks PR references to Task IDs
- Provides advisory feedback (no build failures)
- Maintains specification integrity

## Getting Started

1. Read the [Fractal Tree MVP Specification](./fractal-tree-mvp.spec.md)
2. Review the [Technical Implementation Plan](./plan.fractal-tree-mvp.md)
3. Browse [Granular Tasks](./tasks.fractal-tree-mvp.md)
4. Create issues using `.github/ISSUE_TEMPLATE/spec-task.yml`
5. Link PRs using the provided PR template

