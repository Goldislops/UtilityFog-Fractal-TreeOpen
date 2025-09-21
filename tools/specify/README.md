# Specify Design Tokens Integration

[![Specify Design Tokens](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/specify-ci.yml/badge.svg)](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/specify-ci.yml)

Automated design token management using [Specify](https://specify.io) for consistent design system implementation across the UtilityFog project.

## 🚀 Quick Start Guide

### 1. Repository Secrets Setup (GitHub Actions)

For automated CI/CD token generation, configure these secrets in your repository:

**Go to:** `Settings` → `Secrets and variables` → `Actions` → `New repository secret`

| Secret Name | Required | Description | How to Get |
|-------------|----------|-------------|------------|
| `SPECIFY_API_TOKEN` | ✅ Yes | Your Specify API token | [Specify Settings → API Tokens](https://app.specify.io/settings/api-tokens) |
| `SPECIFY_REPOSITORY_ID` | ✅ Yes | Your Specify repository ID | Found in repository URL or API |
| `SPECIFY_ORGANIZATION_ID` | ✅ Yes | Your Specify organization ID | Found in organization settings |

### 2. Local Development Setup

For local token generation and testing:

```bash
# 1. Navigate to the specify tools directory
cd tools/specify

# 2. Copy the environment template
cp .env.example .env

# 3. Edit .env with your credentials
nano .env  # or your preferred editor

# 4. Install dependencies (if needed)
pip install -r requirements-dev.txt
npm install -g @specify/cli  # Optional: for direct CLI usage
```

### 3. Configuration (.env file)

Edit your `.env` file with your Specify credentials:

```bash
# Required for live mode
SPECIFY_API_TOKEN=your_api_token_here
SPECIFY_REPOSITORY_ID=your_repository_id_here
SPECIFY_ORGANIZATION_ID=your_organization_id_here

# Optional: Override default behavior
SPECIFY_MODE=auto          # auto, live, or mock
LOG_LEVEL=info            # debug, info, warning, error
TOKEN_CATEGORIES=all      # all, or comma-separated: colors,spacing,typography
```

## 🔄 Mock vs Live Mode

### Mock Mode (Default for Development)
- **When:** Pull requests, development branches, missing credentials
- **Behavior:** Uses local `mock-tokens.json` for safe testing
- **Output:** Generated tokens uploaded as PR artifacts
- **Safety:** No API calls, no commits to main branch

### Live Mode (Production)
- **When:** Main branch pushes, manual workflow dispatch with force flag
- **Behavior:** Fetches real tokens from Specify API
- **Output:** Generated tokens committed to `tools/specify/output/`
- **Requirements:** All three secrets must be configured

## 📁 Generated Output Files

The workflow generates tokens in multiple formats:

```
tools/specify/output/
├── tokens.json          # Raw token data from Specify
├── tokens.css           # CSS custom properties (:root variables)
├── tokens.scss          # Sass/SCSS variables ($variable-name)
└── tokens.js            # JavaScript/TypeScript exports
```

### Usage Examples

**CSS:**
```css
/* Auto-generated custom properties */
:root {
  --colors-primary: #007bff;
  --spacing-md: 16px;
  --typography-font-size-lg: 18px;
}

/* Use in your styles */
.button {
  background-color: var(--colors-primary);
  padding: var(--spacing-md);
  font-size: var(--typography-font-size-lg);
}
```

**SCSS:**
```scss
// Auto-generated variables
$colors-primary: #007bff;
$spacing-md: 16px;

// Use in your Sass
.button {
  background-color: $colors-primary;
  padding: $spacing-md;
}
```

**JavaScript/TypeScript:**
```javascript
// Auto-generated exports
import { tokens } from './tools/specify/output/tokens.js';

// Use in your components
const Button = styled.button`
  background-color: ${tokens.colors.primary};
  padding: ${tokens.spacing.md};
`;
```

## 🔧 Workflow Triggers

### Automatic Triggers
- **Push to main/develop:** Runs in live mode (if secrets configured)
- **Pull Request:** Runs in mock mode for safety
- **File changes:** Only triggers when `tools/specify/**` or workflow files change

### Manual Trigger
Use GitHub Actions "Run workflow" button with options:
- **Force Live Mode:** Override automatic mode detection
- **Token Categories:** Specify which categories to update (colors, spacing, etc.)

## 🛠️ Troubleshooting

### ❌ "SPECIFY_API_TOKEN secret not configured"
**Problem:** Missing or invalid API token
**Solution:**
1. Go to [Specify API Tokens](https://app.specify.io/settings/api-tokens)
2. Create a new token with appropriate permissions
3. Add it as `SPECIFY_API_TOKEN` repository secret

### ❌ "SPECIFY_REPOSITORY_ID secret not configured"
**Problem:** Missing repository ID
**Solution:**
1. Open your Specify repository
2. Copy the ID from the URL: `https://app.specify.io/repository/{ID}`
3. Add it as `SPECIFY_REPOSITORY_ID` repository secret

### ❌ "SPECIFY_ORGANIZATION_ID secret not configured"
**Problem:** Missing organization ID
**Solution:**
1. Go to your Specify organization settings
2. Copy the organization ID
3. Add it as `SPECIFY_ORGANIZATION_ID` repository secret

### ❌ API Rate Limits
**Problem:** Too many API requests
**Solution:**
- Wait for rate limit reset (usually 1 hour)
- Use mock mode for development
- Reduce frequency of token updates

### ❌ Invalid Token Structure
**Problem:** Generated tokens fail validation
**Solution:**
1. Check your Specify repository structure
2. Ensure tokens follow expected naming conventions
3. Review token categories in your Specify setup

### ❌ Local Development Issues
**Problem:** Tokens not generating locally
**Solution:**
```bash
# Check your .env file
cat .env

# Verify Python dependencies
pip install -r requirements-dev.txt

# Test with mock mode first
SPECIFY_MODE=mock python generate_tokens.py

# Enable debug logging
LOG_LEVEL=debug python generate_tokens.py
```

## 📊 Monitoring & Status

### GitHub Actions Status
- View workflow runs: [Actions → Specify Design Tokens](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/specify-ci.yml)
- Check badge status in main README
- Review PR comments for detailed status

### Artifacts & Downloads
- **PR Artifacts:** Download generated tokens from workflow runs
- **Main Branch:** Tokens automatically committed to `tools/specify/output/`
- **Retention:** Artifacts kept for 30 days

## 🔒 Security & Best Practices

### API Token Security
- ✅ Store tokens as repository secrets (never in code)
- ✅ Use tokens with minimal required permissions
- ✅ Rotate tokens regularly
- ❌ Never commit tokens to version control

### Workflow Safety
- ✅ Mock mode prevents accidental API usage in development
- ✅ Separate branches for token updates
- ✅ Automatic validation of generated tokens
- ✅ PR comments provide transparency

### Development Workflow
1. **Development:** Work in mock mode with local `.env`
2. **Testing:** Create PR to validate token changes
3. **Production:** Merge to main for live token generation
4. **Monitoring:** Check workflow status and generated outputs

## 📚 Additional Resources

- [Specify Documentation](https://docs.specify.io/)
- [Specify API Reference](https://docs.specify.io/api)
- [Design Tokens Community Group](https://design-tokens.github.io/community-group/)
- [CSS Custom Properties Guide](https://developer.mozilla.org/en-US/docs/Web/CSS/Using_CSS_custom_properties)

## 🤝 Contributing

When contributing to design token configuration:

1. **Test locally** with mock mode first
2. **Create focused PRs** for token changes
3. **Document changes** in PR descriptions
4. **Review generated outputs** before merging
5. **Monitor CI status** after deployment

---

**Need help?** Check the [troubleshooting section](#-troubleshooting) above or create an issue with the `tooling` label.
