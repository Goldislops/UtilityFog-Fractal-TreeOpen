#!/usr/bin/env node

/**
 * Transform Design Tokens
 * 
 * This script transforms raw design tokens from Specify into platform-specific
 * formats (CSS, SCSS, JavaScript, JSON) using the transformation configuration.
 */

const fs = require('fs').promises;
const path = require('path');
const Handlebars = require('handlebars');
const config = require('../config/specify.config.js');
const transformConfig = require('../config/transform.config.js');

class TokenTransformer {
  constructor() {
    this.config = config;
    this.transformConfig = transformConfig;
    this.setupHandlebarsHelpers();
  }

  setupHandlebarsHelpers() {
    // Register Handlebars helpers for token transformation
    Handlebars.registerHelper('kebabCase', (str) => {
      return str.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`).replace(/^-/, '');
    });

    Handlebars.registerHelper('camelCase', (str) => {
      return str.replace(/-([a-z])/g, (match, letter) => letter.toUpperCase());
    });

    Handlebars.registerHelper('rgbFromHex', (hex) => {
      if (!hex || !hex.startsWith('#')) return hex;
      const r = parseInt(hex.substr(1, 2), 16);
      const g = parseInt(hex.substr(3, 2), 16);
      const b = parseInt(hex.substr(5, 2), 16);
      return `${r}, ${g}, ${b}`;
    });
  }

  async transformTokens() {
    console.log('🔄 Starting token transformation...');

    try {
      // Load raw tokens
      const rawTokens = await this.loadRawTokens();
      
      // Transform tokens for each enabled platform
      const results = {};
      
      for (const [platform, platformConfig] of Object.entries(this.config.transform.platforms)) {
        if (platformConfig.enabled) {
          console.log(`📝 Transforming tokens for ${platform}...`);
          const transformed = await this.transformForPlatform(rawTokens, platform, platformConfig);
          results[platform] = transformed;
        }
      }

      console.log('✅ Token transformation completed successfully!');
      return results;

    } catch (error) {
      console.error('❌ Error transforming tokens:', error.message);
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

  async transformForPlatform(rawTokens, platform, platformConfig) {
    const flatTokens = this.flattenTokens(rawTokens);
    const transformedTokens = this.applyTransformations(flatTokens, platform);
    
    // Generate output using template
    const output = await this.generateOutput(transformedTokens, platform, platformConfig);
    
    // Ensure output directory exists
    const outputDir = path.dirname(platformConfig.outputPath);
    await fs.mkdir(outputDir, { recursive: true });
    
    // Write transformed tokens
    await fs.writeFile(platformConfig.outputPath, output);
    
    console.log(`  ✓ ${platform} tokens saved to ${platformConfig.outputPath}`);
    
    return {
      path: platformConfig.outputPath,
      tokenCount: Object.keys(transformedTokens).length,
      output: output
    };
  }

  flattenTokens(tokens, prefix = '', result = {}) {
    for (const [key, value] of Object.entries(tokens)) {
      const tokenPath = prefix ? `${prefix}-${key}` : key;
      
      if (value && typeof value === 'object' && value.value !== undefined) {
        // This is a token with a value
        result[tokenPath] = {
          name: tokenPath,
          value: value.value,
          type: value.type,
          path: tokenPath.split('-'),
          attributes: {
            category: prefix.split('-')[0] || key,
            type: value.type
          }
        };
      } else if (value && typeof value === 'object') {
        // This is a nested object, recurse
        this.flattenTokens(value, tokenPath, result);
      }
    }
    
    return result;
  }

  applyTransformations(tokens, platform) {
    const platformTransforms = this.transformConfig.platforms[platform]?.transforms || [];
    const transformed = {};

    for (const [tokenName, token] of Object.entries(tokens)) {
      let transformedToken = { ...token };

      // Apply each transformation
      for (const transformName of platformTransforms) {
        const transform = this.transformConfig.transforms[transformName];
        if (transform && transform.matcher(transformedToken)) {
          if (transform.type === 'value') {
            transformedToken.value = transform.transformer(transformedToken);
          } else if (transform.type === 'name') {
            transformedToken.name = transform.transformer(transformedToken);
          }
        }
      }

      transformed[transformedToken.name] = transformedToken;
    }

    return transformed;
  }

  async generateOutput(tokens, platform, platformConfig) {
    const templatePath = platformConfig.template;
    const fileHeaders = this.transformConfig.fileHeaders[platform] || [];
    
    let output = '';
    
    // Add file header
    if (fileHeaders.length > 0) {
      output += fileHeaders.join('\n') + '\n';
    }

    // Generate platform-specific output
    switch (platform) {
      case 'css':
        output += this.generateCSSOutput(tokens);
        break;
      case 'scss':
        output += this.generateSCSSOutput(tokens);
        break;
      case 'js':
        output += this.generateJSOutput(tokens);
        break;
      case 'json':
        output += this.generateJSONOutput(tokens);
        break;
      default:
        throw new Error(`Unsupported platform: ${platform}`);
    }

    return output;
  }

  generateCSSOutput(tokens) {
    let css = ':root {\n';
    
    for (const [name, token] of Object.entries(tokens)) {
      const cssName = `--${name}`;
      const comment = token.attributes?.category ? ` /* ${token.attributes.category} */` : '';
      css += `  ${cssName}: ${token.value};${comment}\n`;
    }
    
    css += '}\n';
    return css;
  }

  generateSCSSOutput(tokens) {
    let scss = '';
    
    for (const [name, token] of Object.entries(tokens)) {
      const scssName = `$${name}`;
      const comment = token.attributes?.category ? ` // ${token.attributes.category}` : '';
      scss += `${scssName}: ${token.value};${comment}\n`;
    }
    
    return scss;
  }

  generateJSOutput(tokens) {
    let js = 'export const tokens = {\n';
    
    const entries = Object.entries(tokens);
    entries.forEach(([name, token], index) => {
      const jsName = this.toCamelCase(name);
      const comment = token.attributes?.category ? ` // ${token.attributes.category}` : '';
      const comma = index < entries.length - 1 ? ',' : '';
      js += `  ${jsName}: '${token.value}'${comma}${comment}\n`;
    });
    
    js += '};\n\nexport default tokens;\n';
    
    // Add TypeScript definitions if enabled
    if (this.transformConfig.platforms.js?.generateTypes) {
      this.generateTypeDefinitions(tokens);
    }
    
    return js;
  }

  generateJSONOutput(tokens) {
    const jsonTokens = {};
    
    for (const [name, token] of Object.entries(tokens)) {
      jsonTokens[name] = {
        value: token.value,
        type: token.type,
        category: token.attributes?.category
      };
    }
    
    return JSON.stringify(jsonTokens, null, 2);
  }

  async generateTypeDefinitions(tokens) {
    const typeDefsPath = this.transformConfig.platforms.js.typeDefinitionsPath;
    
    let typeDefs = '/**\n * Design Tokens Type Definitions\n * Generated automatically - do not edit\n */\n\n';
    typeDefs += 'export interface DesignTokens {\n';
    
    for (const [name, token] of Object.entries(tokens)) {
      const jsName = this.toCamelCase(name);
      const comment = token.attributes?.category ? ` // ${token.attributes.category}` : '';
      typeDefs += `  ${jsName}: string;${comment}\n`;
    }
    
    typeDefs += '}\n\n';
    typeDefs += 'declare const tokens: DesignTokens;\n';
    typeDefs += 'export default tokens;\n';
    
    // Ensure directory exists
    const typeDefsDir = path.dirname(typeDefsPath);
    await fs.mkdir(typeDefsDir, { recursive: true });
    
    await fs.writeFile(typeDefsPath, typeDefs);
    console.log(`  ✓ TypeScript definitions saved to ${typeDefsPath}`);
  }

  toCamelCase(str) {
    return str.replace(/-([a-z])/g, (match, letter) => letter.toUpperCase());
  }
}

// CLI execution
if (require.main === module) {
  const transformer = new TokenTransformer();
  
  transformer.transformTokens()
    .then(() => {
      console.log('🎉 Token transformation completed successfully!');
      process.exit(0);
    })
    .catch((error) => {
      console.error('💥 Token transformation failed:', error.message);
      process.exit(1);
    });
}

module.exports = TokenTransformer;
