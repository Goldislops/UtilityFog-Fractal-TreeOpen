#!/usr/bin/env node

/**
 * Validate Design Tokens
 * 
 * This script validates design tokens against defined rules and standards
 * to ensure consistency, accessibility, and proper formatting.
 */

const fs = require('fs').promises;
const path = require('path');
const config = require('../config/specify.config.js');

class TokenValidator {
  constructor() {
    this.config = config;
    this.validationRules = this.config.validation;
    this.errors = [];
    this.warnings = [];
  }

  async validateTokens() {
    console.log('🔍 Starting token validation...');

    try {
      // Load raw tokens
      const rawTokens = await this.loadRawTokens();
      
      // Run validation checks
      await this.validateTokenStructure(rawTokens);
      await this.validateTokenNaming(rawTokens);
      await this.validateTokenValues(rawTokens);
      await this.validateRequiredCategories(rawTokens);
      await this.validateAccessibility(rawTokens);
      
      // Generate validation report
      const report = this.generateValidationReport();
      
      if (this.errors.length === 0) {
        console.log('✅ All tokens passed validation!');
      } else {
        console.error(`❌ Validation failed with ${this.errors.length} errors and ${this.warnings.length} warnings`);
      }
      
      return report;

    } catch (error) {
      console.error('❌ Error during token validation:', error.message);
      throw error;
    }
  }

  async loadRawTokens() {
    try {
      const rawData = await fs.readFile(this.config.fetch.outputPath, 'utf8');
      return JSON.parse(rawData);
    } catch (error) {
      throw new Error(`Failed to load raw tokens: ${error.message}`);
    }
  }

  async validateTokenStructure(tokens) {
    console.log('📋 Validating token structure...');
    
    this.validateObjectStructure(tokens, '');
  }

  validateObjectStructure(obj, path) {
    if (!obj || typeof obj !== 'object') {
      this.addError(`Invalid token structure at ${path || 'root'}: expected object`);
      return;
    }

    for (const [key, value] of Object.entries(obj)) {
      const currentPath = path ? `${path}.${key}` : key;
      
      if (value && typeof value === 'object') {
        if (value.value !== undefined) {
          // This is a token leaf node
          this.validateTokenLeaf(value, currentPath);
        } else {
          // This is a nested object, recurse
          this.validateObjectStructure(value, currentPath);
        }
      } else {
        this.addError(`Invalid token structure at ${currentPath}: expected object or token`);
      }
    }
  }

  validateTokenLeaf(token, path) {
    // Check required properties
    if (token.value === undefined) {
      this.addError(`Missing value property at ${path}`);
    }
    
    if (!token.type) {
      this.addWarning(`Missing type property at ${path}`);
    }

    // Validate token type
    const validTypes = ['color', 'dimension', 'fontFamily', 'fontWeight', 'number', 'string'];
    if (token.type && !validTypes.includes(token.type)) {
      this.addWarning(`Unknown token type "${token.type}" at ${path}`);
    }
  }

  async validateTokenNaming(tokens) {
    console.log('🏷️  Validating token naming...');
    
    const flatTokens = this.flattenTokens(tokens);
    
    for (const [name, token] of Object.entries(flatTokens)) {
      this.validateTokenName(name, token);
    }
  }

  validateTokenName(name, token) {
    const namingRules = this.validationRules.naming;
    
    // Check allowed characters
    if (!namingRules.allowedChars.test(name)) {
      this.addError(`Invalid characters in token name "${name}"`);
    }
    
    // Check maximum length
    if (name.length > namingRules.maxLength) {
      this.addError(`Token name "${name}" exceeds maximum length of ${namingRules.maxLength}`);
    }
    
    // Check required prefixes
    const category = this.getTokenCategory(token);
    if (category && namingRules.prefixes[category]) {
      const requiredPrefixes = namingRules.prefixes[category];
      const hasValidPrefix = requiredPrefixes.some(prefix => name.startsWith(prefix));
      
      if (!hasValidPrefix) {
        this.addWarning(`Token "${name}" should start with one of: ${requiredPrefixes.join(', ')}`);
      }
    }
  }

  async validateTokenValues(tokens) {
    console.log('💎 Validating token values...');
    
    const flatTokens = this.flattenTokens(tokens);
    
    for (const [name, token] of Object.entries(flatTokens)) {
      this.validateTokenValue(name, token);
    }
  }

  validateTokenValue(name, token) {
    const valueRules = this.validationRules.values;
    const tokenType = token.type;
    
    if (tokenType === 'color') {
      this.validateColorValue(name, token.value, valueRules.color);
    } else if (tokenType === 'dimension') {
      this.validateDimensionValue(name, token.value, valueRules.spacing);
    }
  }

  validateColorValue(name, value, rules) {
    if (typeof value !== 'string') {
      this.addError(`Color token "${name}" must have string value`);
      return;
    }

    // Check color format
    const validFormats = rules.formats;
    let isValidFormat = false;
    
    if (validFormats.includes('hex') && /^#[0-9A-Fa-f]{3,8}$/.test(value)) {
      isValidFormat = true;
    } else if (validFormats.includes('rgb') && /^rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)$/.test(value)) {
      isValidFormat = true;
    } else if (validFormats.includes('rgba') && /^rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*[\d.]+\s*\)$/.test(value)) {
      isValidFormat = true;
    }
    
    if (!isValidFormat) {
      this.addError(`Color token "${name}" has invalid format. Expected: ${validFormats.join(', ')}`);
    }
  }

  validateDimensionValue(name, value, rules) {
    if (typeof value !== 'string') {
      this.addError(`Dimension token "${name}" must have string value`);
      return;
    }

    // Extract numeric value and unit
    const match = value.match(/^([\d.]+)(.*)$/);
    if (!match) {
      this.addError(`Dimension token "${name}" has invalid format`);
      return;
    }

    const [, numericPart, unit] = match;
    const numericValue = parseFloat(numericPart);
    
    // Check minimum value
    if (numericValue < rules.minValue) {
      this.addError(`Dimension token "${name}" value ${numericValue} is below minimum ${rules.minValue}`);
    }
    
    // Check valid units
    if (unit && !rules.units.includes(unit)) {
      this.addError(`Dimension token "${name}" has invalid unit "${unit}". Expected: ${rules.units.join(', ')}`);
    }
  }

  async validateRequiredCategories(tokens) {
    console.log('📂 Validating required categories...');
    
    const requiredCategories = this.validationRules.requiredCategories;
    const availableCategories = Object.keys(tokens);
    
    for (const required of requiredCategories) {
      if (!availableCategories.includes(required)) {
        this.addError(`Missing required token category: ${required}`);
      }
    }
  }

  async validateAccessibility(tokens) {
    console.log('♿ Validating accessibility...');
    
    // Check color contrast ratios for semantic colors
    if (tokens.color && tokens.semantic) {
      this.validateColorContrast(tokens);
    }
    
    // Check font size accessibility
    if (tokens.font && tokens.font.size) {
      this.validateFontSizes(tokens.font.size);
    }
  }

  validateColorContrast(tokens) {
    // This is a simplified contrast check
    // In a real implementation, you'd use a proper contrast ratio calculation
    const semanticColors = tokens.semantic || {};
    
    for (const [name, colorToken] of Object.entries(semanticColors)) {
      if (colorToken.value) {
        // Check if color is too light or too dark for accessibility
        const hex = colorToken.value.replace('#', '');
        if (hex.length === 6) {
          const r = parseInt(hex.substr(0, 2), 16);
          const g = parseInt(hex.substr(2, 2), 16);
          const b = parseInt(hex.substr(4, 2), 16);
          const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
          
          if (luminance < 0.1 || luminance > 0.9) {
            this.addWarning(`Semantic color "${name}" may have accessibility issues due to extreme luminance`);
          }
        }
      }
    }
  }

  validateFontSizes(fontSizes) {
    for (const [name, sizeToken] of Object.entries(fontSizes)) {
      if (sizeToken.value) {
        const match = sizeToken.value.match(/^([\d.]+)(.*)$/);
        if (match) {
          const [, numericPart, unit] = match;
          const size = parseFloat(numericPart);
          
          // Check minimum font size for accessibility (assuming rem units)
          if (unit === 'rem' && size < 0.75) {
            this.addWarning(`Font size "${name}" (${sizeToken.value}) may be too small for accessibility`);
          }
        }
      }
    }
  }

  flattenTokens(tokens, prefix = '', result = {}) {
    for (const [key, value] of Object.entries(tokens)) {
      const tokenPath = prefix ? `${prefix}-${key}` : key;
      
      if (value && typeof value === 'object' && value.value !== undefined) {
        result[tokenPath] = value;
      } else if (value && typeof value === 'object') {
        this.flattenTokens(value, tokenPath, result);
      }
    }
    
    return result;
  }

  getTokenCategory(token) {
    // Simple category detection based on token type
    const typeToCategory = {
      'color': 'color',
      'dimension': 'spacing',
      'fontFamily': 'font',
      'fontWeight': 'font',
      'fontSize': 'font'
    };
    
    return typeToCategory[token.type] || 'unknown';
  }

  addError(message) {
    this.errors.push({
      type: 'error',
      message: message,
      timestamp: new Date().toISOString()
    });
    console.error(`  ❌ ${message}`);
  }

  addWarning(message) {
    this.warnings.push({
      type: 'warning',
      message: message,
      timestamp: new Date().toISOString()
    });
    console.warn(`  ⚠️  ${message}`);
  }

  generateValidationReport() {
    const report = {
      timestamp: new Date().toISOString(),
      summary: {
        totalErrors: this.errors.length,
        totalWarnings: this.warnings.length,
        passed: this.errors.length === 0
      },
      errors: this.errors,
      warnings: this.warnings
    };

    console.log('\n📊 Validation Summary:');
    console.log(`  Errors: ${this.errors.length}`);
    console.log(`  Warnings: ${this.warnings.length}`);
    console.log(`  Status: ${report.summary.passed ? '✅ PASSED' : '❌ FAILED'}`);

    return report;
  }

  async saveValidationReport(report) {
    const reportPath = path.join(this.config.publish.backupPath, 'validation-report.json');
    await fs.mkdir(path.dirname(reportPath), { recursive: true });
    await fs.writeFile(reportPath, JSON.stringify(report, null, 2));
    console.log(`📄 Validation report saved to ${reportPath}`);
  }
}

// CLI execution
if (require.main === module) {
  const validator = new TokenValidator();
  
  validator.validateTokens()
    .then(async (report) => {
      await validator.saveValidationReport(report);
      
      if (report.summary.passed) {
        console.log('🎉 Token validation completed successfully!');
        process.exit(0);
      } else {
        console.error('💥 Token validation failed!');
        process.exit(1);
      }
    })
    .catch((error) => {
      console.error('💥 Token validation error:', error.message);
      process.exit(1);
    });
}

module.exports = TokenValidator;
