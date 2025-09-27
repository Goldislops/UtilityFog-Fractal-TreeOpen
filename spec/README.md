# Specification Directory

This directory contains formal specifications for the UtilityFog-Fractal-TreeOpen project. Our specification philosophy emphasizes living documentation that evolves with the codebase, ensuring behavioral contracts remain synchronized with implementation.

We use SpeckKit for specification validation, supporting both interface contracts (defining component boundaries and invariants) and property-based specifications (capturing mathematical relationships and behavioral properties). Specifications serve as executable documentation, enabling automated validation of system behavior and facilitating confident refactoring.

## Running Validation Locally

To validate specifications locally:

```bash
# Using Node.js (if package.json has speckit:validate script)
npm run speckit:validate

# Using Python CLI (fallback)
pip install speckit
speckit validate

# Manual validation of specific files
speckit validate spec/examples/fractal_tree.contract.yaml
speckit validate spec/examples/serialization.property.yaml
```

Validation runs automatically on pull requests and pushes that modify files under `/spec/**`.
