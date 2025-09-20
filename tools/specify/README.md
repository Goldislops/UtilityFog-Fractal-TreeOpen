# Specify Design Token Integration

This directory contains the integration tools for [Specify](https://specify.app/) design tokens within the UtilityFog project. Specify enables seamless design-to-code workflows by managing design tokens centrally and distributing them across platforms.

## 🚀 3-Step Quick Start

### Step 1: Environment Setup
```bash
# Copy the environment template
cp .env.example .env

# Edit the configuration with your Specify credentials
nano .env  # or your preferred editor
```

**Required Configuration:**
- `SPECIFY_API_TOKEN`: Your Specify API token (get from [Specify Dashboard](https://app.specify.app/))
- `SPECIFY_REPOSITORY_ID`: Your repository ID from Specify
- `SPECIFY_ORGANIZATION_ID`: Your organization ID from Specify

### Step 2: Install Dependencies
```bash
# From the project root
pip install -r requirements-dev.txt

# Or install Specify CLI globally
npm install -g @specify/cli
```

### Step 3: Generate Design Tokens
```bash
# Development mode (uses mock data)
SPECIFY_MODE=mock python generate_tokens.py

# Production mode (uses live Specify API)
SPECIFY_MODE=live python generate_tokens.py

# Or use the CLI directly
specify pull --repository-id YOUR_REPO_ID --token YOUR_TOKEN
```

## 📁 Directory Structure

```
tools/specify/
├── .env.example          # Environment configuration template
├── README.md            # This file
├── generate_tokens.py   # Token generation script
├── mock-tokens.json     # Mock data for development
├── specify-ci.yml       # CI workflow configuration
└── output/             # Generated design tokens
    ├── tokens.css      # CSS custom properties
    ├── tokens.scss     # Sass variables
    ├── tokens.js       # JavaScript/TypeScript tokens
    └── tokens.json     # Raw JSON tokens
```

## 🔧 Configuration Options

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `SPECIFY_API_TOKEN` | Your Specify API token | - | Yes (live mode) |
| `SPECIFY_REPOSITORY_ID` | Repository ID from Specify | - | Yes (live mode) |
| `SPECIFY_ORGANIZATION_ID` | Organization ID from Specify | - | Yes (live mode) |
| `SPECIFY_MODE` | Operation mode: `mock` or `live` | `mock` | No |
| `OUTPUT_FORMAT` | Output formats (comma-separated) | `css,scss,js,json` | No |
| `OUTPUT_DIRECTORY` | Where to save generated tokens | `./output` | No |
| `LOG_LEVEL` | Logging verbosity | `info` | No |

### Mock vs Live Mode

**Mock Mode (`SPECIFY_MODE=mock`)**
- Uses local `mock-tokens.json` file
- No API calls to Specify
- Perfect for development and testing
- No authentication required

**Live Mode (`SPECIFY_MODE=live`)**
- Fetches real design tokens from Specify API
- Requires valid API credentials
- Used in production builds
- Respects API rate limits

## 🎨 Design Token Categories

The integration supports all Specify design token types:

### Colors
- Primary, secondary, accent colors
- Semantic colors (success, warning, error)
- Neutral grays and backgrounds

### Typography
- Font families, weights, sizes
- Line heights and letter spacing
- Responsive typography scales

### Spacing
- Margin and padding scales
- Layout spacing systems
- Component-specific spacing

### Borders & Shadows
- Border radius, width, styles
- Box shadows and elevations
- Focus and interaction states

## 🔄 CI/CD Integration

The Specify integration includes automated CI/CD workflows:

### Automatic Token Updates
```yaml
# .github/workflows/specify-ci.yml
- name: Update Design Tokens
  run: |
    if [ "$SPECIFY_MODE" = "live" ]; then
      python tools/specify/generate_tokens.py
    else
      echo "Running in mock mode for development"
    fi
```

### Mock/Live Toggle
The CI system automatically switches between mock and live modes:
- **Pull Requests**: Uses mock mode for safety
- **Main Branch**: Uses live mode for production
- **Manual Override**: Set `FORCE_LIVE_MODE=true` in workflow

## 🛠️ Development Workflow

### 1. Local Development
```bash
# Work with mock data
export SPECIFY_MODE=mock
python generate_tokens.py

# Test your changes
npm run test:tokens
```

### 2. Token Updates
```bash
# Pull latest tokens from Specify
export SPECIFY_MODE=live
python generate_tokens.py

# Commit the updated tokens
git add output/
git commit -m "chore: update design tokens from Specify"
```

### 3. Integration Testing
```bash
# Test token integration in components
npm run build:tokens
npm run test:integration
```

## 📊 Output Formats

### CSS Custom Properties
```css
/* output/tokens.css */
:root {
  --color-primary: #007bff;
  --spacing-md: 16px;
  --font-size-h1: 2.5rem;
}
```

### Sass Variables
```scss
/* output/tokens.scss */
$color-primary: #007bff;
$spacing-md: 16px;
$font-size-h1: 2.5rem;
```

### JavaScript/TypeScript
```javascript
/* output/tokens.js */
export const tokens = {
  color: {
    primary: '#007bff'
  },
  spacing: {
    md: '16px'
  }
};
```

### JSON
```json
{
  "color": {
    "primary": {
      "value": "#007bff",
      "type": "color"
    }
  }
}
```

## 🔍 Troubleshooting

### Common Issues

**Authentication Errors**
```bash
Error: Invalid API token
```
- Verify your `SPECIFY_API_TOKEN` in `.env`
- Check token permissions in Specify dashboard
- Ensure token hasn't expired

**Repository Not Found**
```bash
Error: Repository not accessible
```
- Verify `SPECIFY_REPOSITORY_ID` is correct
- Check repository permissions
- Ensure you're part of the organization

**Network Issues**
```bash
Error: Request timeout
```
- Check internet connection
- Verify `SPECIFY_API_BASE_URL` if using custom endpoint
- Try again later (may be temporary API issue)

### Debug Mode
```bash
# Enable verbose logging
export LOG_LEVEL=debug
python generate_tokens.py
```

## 🤝 Contributing

### Adding New Token Categories
1. Update `mock-tokens.json` with new token structure
2. Modify `generate_tokens.py` to handle new token types
3. Update output templates for all formats
4. Add tests for new token categories

### Improving CI Integration
1. Edit `.github/workflows/specify-ci.yml`
2. Test changes in a feature branch
3. Ensure mock/live mode switching works correctly
4. Update documentation

## 📚 Resources

- [Specify Documentation](https://docs.specify.app/)
- [Specify API Reference](https://docs.specify.app/api)
- [Design Token Community Group](https://www.w3.org/community/design-tokens/)
- [UtilityFog Design Philosophy](../../docs/DESIGN_PHILOSOPHY.md)

## 🔐 Security

- Never commit `.env` files with real credentials
- Use environment variables in CI/CD
- Rotate API tokens regularly
- Limit token permissions to minimum required

## 📄 License

This integration follows the same license as the main UtilityFog project.
