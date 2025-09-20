# Specify Design Tokens Tooling

This directory contains the complete tooling infrastructure for managing design tokens from Specify in the UtilityFog-Fractal-TreeOpen project.

## Overview

The design token pipeline follows a 4-step process:
1. **Fetch** - Pull tokens from Specify API
2. **Transform** - Convert tokens to platform-specific formats
3. **Publish** - Deploy tokens to target destinations
4. **Validate** - Ensure token quality and consistency

## Directory Structure

```
tools/specify/
├── config/
│   ├── specify.config.js      # Specify API and pipeline configuration
│   └── transform.config.js    # Token transformation rules
├── scripts/
│   ├── fetch-tokens.js        # Pull tokens from Specify API
│   ├── transform-tokens.js    # Transform tokens for different platforms
│   ├── publish-tokens.js      # Publish tokens to consumers
│   └── validate-tokens.js     # Token validation and testing
├── templates/
│   ├── css-variables.hbs      # CSS custom properties template
│   ├── js-tokens.hbs          # JavaScript tokens template
│   └── scss-variables.hbs     # SCSS variables template
├── output/
│   ├── raw-tokens.json        # Raw tokens from Specify
│   ├── tokens.css             # Generated CSS custom properties
│   ├── tokens.js              # Generated JavaScript tokens
│   ├── tokens.scss            # Generated SCSS variables
│   └── tokens.json            # Generated JSON tokens
└── backups/                   # Backup directory for safety
```

## Quick Start

### Prerequisites

1. **Node.js** (v14 or higher)
2. **Specify API Token** - Set as environment variable
3. **Repository Access** - Ensure proper permissions

### Environment Setup

#### Repository Secrets Setup

For CI/CD workflows, configure the following repository secrets in GitHub:

1. Navigate to your repository → Settings → Secrets and variables → Actions
2. Add the following secrets:
   - `SPECIFY_API_TOKEN`: Your Specify API token from account settings
   - `SPECIFY_SPACE_ID`: Your Specify workspace/space identifier

**Getting Your Specify Credentials:**
1. Log into your Specify account at [specify.app](https://specify.app)
2. Go to Account Settings → API Tokens
3. Generate a new token with appropriate permissions
4. Copy your Space ID from the workspace URL: `https://specify.app/workspace/{SPACE_ID}`

#### Local Development Environment Setup

**Step 1: Clone and Navigate**
```bash
git clone https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen.git
cd UtilityFog-Fractal-TreeOpen/tools/specify
```

**Step 2: Environment Configuration**
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your actual credentials
# SPECIFY_API_TOKEN=your_actual_token_here
# SPECIFY_SPACE_ID=your_actual_space_id_here
```

**Step 3: Install Dependencies**
```bash
# Install Node.js dependencies (if using npm packages)
npm install handlebars

# Verify environment setup
node -e "console.log('Environment check:', process.env.SPECIFY_API_TOKEN ? 'Token set' : 'Token missing')"
```

**Step 4: Test Connection**
```bash
# Test API connection (mock mode by default)
node scripts/fetch-tokens.js --dry-run
```

### Basic Usage

**Development Mode (Mock API - Default):**
```bash
# Navigate to the tools directory
cd tools/specify

# Run the complete pipeline (uses mock data by default)
npm run tokens:build

# Or run individual steps in mock mode
node scripts/fetch-tokens.js      # Step 1: Fetch (mock data)
node scripts/transform-tokens.js  # Step 2: Transform
node scripts/validate-tokens.js   # Step 3: Validate
node scripts/publish-tokens.js    # Step 4: Publish
```

**Production Mode (Live API - Requires Credentials):**
```bash
# Only use when connecting to live Specify API
# Requires SPECIFY_API_TOKEN and SPECIFY_SPACE_ID to be set

# Run with live API connection
LIVE_API=true npm run tokens:build

# Or run individual steps with live API
LIVE_API=true node scripts/fetch-tokens.js  # Fetches real tokens from Specify
node scripts/transform-tokens.js            # Transform real data
node scripts/validate-tokens.js             # Validate real tokens
node scripts/publish-tokens.js              # Publish to production
```

**⚠️ Important:** Always develop and test with mock data first. Only connect to the live API when you need to pull the latest production tokens or when deploying changes.

## Configuration

### Specify Configuration (`config/specify.config.js`)

Configure your Specify workspace connection:

```javascript
module.exports = {
  api: {
    token: process.env.SPECIFY_API_TOKEN,
    repositoryId: process.env.SPECIFY_REPOSITORY_ID,
    baseUrl: 'https://api.specifyapp.com/v1'
  },
  // ... additional configuration
};
```

### Transform Configuration (`config/transform.config.js`)

Customize how tokens are transformed for different platforms:

```javascript
module.exports = {
  platforms: {
    css: {
      transforms: ['name/cti/kebab', 'color/hex-to-rgb'],
      outputPath: './output/tokens.css'
    },
    // ... additional platforms
  }
};
```

## Token Categories

The system supports the following token categories:

### Colors
- **Primary Colors**: Brand colors with variants (50-900)
- **Neutral Colors**: Grayscale palette
- **Semantic Colors**: Success, error, warning, info

### Spacing
- **Scale**: xs, sm, md, lg, xl, 2xl, 3xl, 4xl
- **Units**: rem-based for consistency

### Typography
- **Font Families**: Sans-serif and monospace stacks
- **Font Sizes**: Responsive scale from xs to 4xl
- **Font Weights**: Normal, medium, semibold, bold
- **Line Heights**: Tight, normal, relaxed

### Semantic Tokens
- **Policy States**: Allow, deny, warning, info
- **Test Results**: Pass, fail, pending, skipped

## Output Formats

### CSS Custom Properties (`tokens.css`)
```css
:root {
  --color-primary-500: 59, 130, 246; /* RGB values for flexibility */
  --spacing-md: 1rem;
  --font-size-base: 1rem;
}
```

### SCSS Variables (`tokens.scss`)
```scss
$color-primary-500: #3b82f6;
$spacing-md: 1rem;
$font-size-base: 1rem;

// Utility functions and mixins included
@function color($name, $variant: 500) { ... }
```

### JavaScript/TypeScript (`tokens.js`)
```javascript
export const tokens = {
  colorPrimary500: '#3b82f6',
  spacingMd: '1rem',
  fontSizeBase: '1rem'
};

// Organized collections and utilities
export const colors = { ... };
export const getColor = (name, variant) => { ... };
```

### JSON (`tokens.json`)
```json
{
  "color-primary-500": {
    "value": "#3b82f6",
    "type": "color",
    "category": "color"
  }
}
```

## Integration Points

### Documentation (`docs/`)
Tokens are published to `docs/assets/tokens/` for use in documentation styling and living style guides.

### Tests (`tests/`)
Tokens are available in `tests/assets/tokens/` for consistent test interface styling.

### Policy UI Components
Apply tokens to policy-related interfaces for consistent theming and better user experience.

## Validation Rules

The validation system checks for:

- **Structure**: Proper token object format
- **Naming**: Consistent naming conventions
- **Values**: Valid color formats, dimension units
- **Categories**: Required token categories present
- **Accessibility**: Color contrast and font size guidelines

## Safety Features

- **Backups**: Automatic backups before publishing
- **Validation**: Comprehensive token validation
- **Branch Protection**: No direct commits to main branches
- **CI Integration**: Automated testing and validation

## Troubleshooting

### Common Issues

1. **Missing API Token**
   ```bash
   Error: SPECIFY_API_TOKEN environment variable is required
   ```
   Solution: Set your Specify API token as an environment variable.

2. **Invalid Token Format**
   ```bash
   Error: Color token "primary-500" has invalid format
   ```
   Solution: Check token values in Specify match expected formats.

3. **Permission Errors**
   ```bash
   Error: Failed to write to output directory
   ```
   Solution: Ensure proper file system permissions.

### Debug Mode

Run scripts with debug output:
```bash
DEBUG=true node scripts/fetch-tokens.js
```

## Development

### Adding New Platforms

1. Add platform configuration to `config/transform.config.js`
2. Create template in `templates/`
3. Update transformation logic in `scripts/transform-tokens.js`
4. Add validation rules if needed

### Custom Transformations

Add custom transformation functions in `config/transform.config.js`:

```javascript
transforms: {
  'custom/transform': {
    type: 'value',
    matcher: (token) => token.type === 'custom',
    transformer: (token) => `custom-${token.value}`
  }
}
```

## Onboarding Checklist

### For New Team Members

**Prerequisites Setup:**
- [ ] Node.js v14+ installed locally
- [ ] Git configured with repository access
- [ ] Specify account access (request from team lead)

**Environment Configuration:**
- [ ] Repository cloned locally
- [ ] `.env` file created from `.env.example`
- [ ] `SPECIFY_API_TOKEN` obtained and configured
- [ ] `SPECIFY_SPACE_ID` identified and configured
- [ ] Dependencies installed (`npm install handlebars`)
- [ ] Connection test successful (`node scripts/fetch-tokens.js --dry-run`)

**Understanding the System:**
- [ ] Read through this README completely
- [ ] Review existing token structure in `output/` directory
- [ ] Understand the 4-step pipeline (Fetch → Transform → Publish → Validate)
- [ ] Familiarize with token categories (colors, spacing, typography, semantic)

**Development Workflow:**
- [ ] Know how to run individual pipeline steps
- [ ] Understand mock vs live API modes
- [ ] Can identify and fix common validation errors
- [ ] Familiar with backup and safety features

**CI/CD Integration:**
- [ ] Repository secrets configured (if admin access)
- [ ] Understand how tokens integrate with documentation
- [ ] Know the branch protection and PR workflow

### For Repository Administrators

**Initial Setup:**
- [ ] Repository secrets configured (`SPECIFY_API_TOKEN`, `SPECIFY_SPACE_ID`)
- [ ] Branch protection rules enabled
- [ ] CI workflows tested and passing
- [ ] Team members granted appropriate Specify workspace access

**Ongoing Maintenance:**
- [ ] Regular token validation and updates
- [ ] Monitor CI workflow health
- [ ] Review and approve token-related PRs
- [ ] Maintain backup procedures

## Contributing

1. Follow existing code patterns and naming conventions
2. Add tests for new functionality
3. Update documentation for any changes
4. Ensure all validation passes before committing
5. Use mock mode for development and testing
6. Only connect to live API when explicitly required

## Resources

- [Specify Documentation](https://docs.specifyapp.com/)
- [Design Tokens Community Group](https://design-tokens.github.io/community-group/)
- [W3C Design Tokens Format](https://tr.designtokens.org/format/)

---

For questions or issues, please refer to the main project documentation or create an issue in the repository.
