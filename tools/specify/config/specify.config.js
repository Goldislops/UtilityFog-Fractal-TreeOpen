/**
 * Specify API Configuration
 * 
 * This configuration file defines how to connect to and fetch design tokens
 * from the Specify API. Update the settings below to match your Specify
 * workspace configuration.
 */

module.exports = {
  // Specify API Configuration
  api: {
    // Your Specify API token (set via environment variable)
    token: process.env.SPECIFY_API_TOKEN,
    
    // Your Specify workspace/repository ID
    repositoryId: process.env.SPECIFY_REPOSITORY_ID || 'your-repo-id',
    
    // API base URL (usually doesn't need to change)
    baseUrl: 'https://api.specifyapp.com/v1',
    
    // Request timeout in milliseconds
    timeout: 30000
  },

  // Token fetching configuration
  fetch: {
    // Which token collections to fetch
    collections: [
      'color',
      'spacing', 
      'font',
      'semantic'
    ],
    
    // Token filtering options
    filters: {
      // Only fetch tokens matching these patterns
      include: ['*'],
      
      // Exclude tokens matching these patterns
      exclude: ['*.deprecated.*', '*.internal.*']
    },
    
    // Output format for raw tokens
    outputFormat: 'json',
    
    // Where to save raw tokens
    outputPath: './tools/specify/output/raw-tokens.json'
  },

  // Transformation configuration
  transform: {
    // Platform-specific transformations
    platforms: {
      css: {
        enabled: true,
        outputPath: './tools/specify/output/tokens.css',
        template: './tools/specify/templates/css-variables.hbs',
        prefix: '--token',
        format: 'css-custom-properties'
      },
      
      scss: {
        enabled: true,
        outputPath: './tools/specify/output/tokens.scss',
        template: './tools/specify/templates/scss-variables.hbs',
        prefix: '$token',
        format: 'scss-variables'
      },
      
      js: {
        enabled: true,
        outputPath: './tools/specify/output/tokens.js',
        template: './tools/specify/templates/js-tokens.hbs',
        format: 'es6-module'
      },
      
      json: {
        enabled: true,
        outputPath: './tools/specify/output/tokens.json',
        format: 'flat-json'
      }
    },
    
    // Token naming conventions
    naming: {
      // How to format token names
      convention: 'kebab-case', // 'kebab-case', 'camelCase', 'snake_case'
      
      // Separator for nested tokens
      separator: '-',
      
      // Whether to include category in token names
      includeCategory: true
    }
  },

  // Publishing configuration
  publish: {
    // Where to publish generated tokens
    targets: [
      {
        name: 'docs',
        path: './docs/assets/tokens',
        formats: ['css', 'json']
      },
      {
        name: 'tests',
        path: './tests/assets/tokens',
        formats: ['css', 'js']
      }
    ],
    
    // Whether to create backup before publishing
    createBackup: true,
    
    // Backup directory
    backupPath: './tools/specify/backups'
  },

  // Validation configuration
  validation: {
    // Required token categories
    requiredCategories: ['color', 'spacing', 'font'],
    
    // Token naming validation rules
    naming: {
      // Allowed characters in token names
      allowedChars: /^[a-zA-Z0-9-_]+$/,
      
      // Maximum token name length
      maxLength: 50,
      
      // Required prefixes for certain token types
      prefixes: {
        color: ['color'],
        spacing: ['spacing'],
        font: ['font']
      }
    },
    
    // Value validation rules
    values: {
      // Color value validation
      color: {
        formats: ['hex', 'rgb', 'rgba', 'hsl', 'hsla'],
        requireAlpha: false
      },
      
      // Spacing value validation
      spacing: {
        units: ['px', 'rem', 'em', '%'],
        minValue: 0
      }
    }
  }
};
