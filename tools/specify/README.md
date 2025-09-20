# Specify Tool Integration

This tool provides integration with the Specify API for taxonomy management within the UtilityFog ecosystem.

## 🔄 Mock/Live Mode Operation

The CI pipeline automatically switches between mock and live modes:

### Mock Mode (Default)
- **When**: No `SPECIFY_API_TOKEN` secret is configured
- **Behavior**: Uses mock responses for all API calls
- **Purpose**: Safe development and testing without hitting live API
- **Status**: 🟡 MOCK MODE active

### Live Mode
- **When**: `SPECIFY_API_TOKEN` secret is configured in GitHub
- **Behavior**: Makes real API calls to Specify
- **Purpose**: Production integration and live data validation
- **Status**: 🔴 LIVE MODE active

## 🚀 Setup

1. **Development (Mock Mode)**:
   ```bash
   cd tools/specify
   npm install
   npm run test:mock
   ```

2. **Production (Live Mode)**:
   - Set `SPECIFY_API_TOKEN` in GitHub repository secrets
   - CI will automatically switch to live mode
   - All tests will run against real Specify API

## 📁 Structure

```
tools/specify/
├── src/
│   ├── index.ts          # Main entry point
│   ├── client.ts         # Specify API client
│   ├── mock-client.ts    # Mock implementation
│   └── test-setup.ts     # Test configuration
├── tests/
│   ├── mock.test.ts      # Mock mode tests
│   └── live.test.ts      # Live mode tests
└── package.json
```

## 🧪 Testing

- `npm run test:mock` - Run tests with mock responses
- `npm run test:live` - Run tests against live API (requires token)
- `npm test` - Run all tests in current mode

## 🔧 Configuration

The tool automatically detects the mode based on environment:
- `SPECIFY_API_TOKEN` present → Live mode
- `SPECIFY_API_TOKEN` absent → Mock mode

No manual configuration needed - the CI pipeline handles everything!
