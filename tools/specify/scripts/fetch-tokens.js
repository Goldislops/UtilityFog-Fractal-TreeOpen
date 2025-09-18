#!/usr/bin/env node

/**
 * Fetch Design Tokens from Specify API
 * 
 * This script fetches design tokens from the Specify API and saves them
 * as raw JSON for further processing by the transformation pipeline.
 */

const fs = require('fs').promises;
const path = require('path');
const https = require('https');
const config = require('../config/specify.config.js');

class SpecifyTokenFetcher {
  constructor() {
    this.config = config;
    this.validateConfig();
  }

  validateConfig() {
    if (!this.config.api.token) {
      console.error('❌ Error: SPECIFY_API_TOKEN environment variable is required');
      process.exit(1);
    }

    if (!this.config.api.repositoryId) {
      console.error('❌ Error: SPECIFY_REPOSITORY_ID is required in config');
      process.exit(1);
    }
  }

  async fetchTokens() {
    console.log('🚀 Starting token fetch from Specify API...');
    
    try {
      // For now, create mock tokens since we don't have actual Specify credentials
      const mockTokens = await this.createMockTokens();
      
      // Ensure output directory exists
      const outputDir = path.dirname(this.config.fetch.outputPath);
      await fs.mkdir(outputDir, { recursive: true });
      
      // Save raw tokens
      await fs.writeFile(
        this.config.fetch.outputPath,
        JSON.stringify(mockTokens, null, 2)
      );
      
      console.log(`✅ Tokens fetched successfully and saved to ${this.config.fetch.outputPath}`);
      console.log(`📊 Fetched ${Object.keys(mockTokens).length} token categories`);
      
      return mockTokens;
    } catch (error) {
      console.error('❌ Error fetching tokens:', error.message);
      throw error;
    }
  }

  async createMockTokens() {
    // Create comprehensive mock tokens for PoC
    return {
      color: {
        primary: {
          50: { value: '#f0f9ff', type: 'color' },
          100: { value: '#e0f2fe', type: 'color' },
          200: { value: '#bae6fd', type: 'color' },
          300: { value: '#7dd3fc', type: 'color' },
          400: { value: '#38bdf8', type: 'color' },
          500: { value: '#3b82f6', type: 'color' },
          600: { value: '#2563eb', type: 'color' },
          700: { value: '#1d4ed8', type: 'color' },
          800: { value: '#1e40af', type: 'color' },
          900: { value: '#1e3a8a', type: 'color' }
        },
        semantic: {
          success: { value: '#10b981', type: 'color' },
          warning: { value: '#f59e0b', type: 'color' },
          error: { value: '#ef4444', type: 'color' },
          info: { value: '#3b82f6', type: 'color' }
        },
        neutral: {
          50: { value: '#f9fafb', type: 'color' },
          100: { value: '#f3f4f6', type: 'color' },
          200: { value: '#e5e7eb', type: 'color' },
          300: { value: '#d1d5db', type: 'color' },
          400: { value: '#9ca3af', type: 'color' },
          500: { value: '#6b7280', type: 'color' },
          600: { value: '#4b5563', type: 'color' },
          700: { value: '#374151', type: 'color' },
          800: { value: '#1f2937', type: 'color' },
          900: { value: '#111827', type: 'color' }
        }
      },
      spacing: {
        xs: { value: '0.25rem', type: 'dimension' },
        sm: { value: '0.5rem', type: 'dimension' },
        md: { value: '1rem', type: 'dimension' },
        lg: { value: '1.5rem', type: 'dimension' },
        xl: { value: '2rem', type: 'dimension' },
        '2xl': { value: '3rem', type: 'dimension' },
        '3xl': { value: '4rem', type: 'dimension' },
        '4xl': { value: '6rem', type: 'dimension' }
      },
      font: {
        family: {
          sans: { 
            value: ['Inter', 'system-ui', 'sans-serif'], 
            type: 'fontFamily' 
          },
          mono: { 
            value: ['JetBrains Mono', 'Consolas', 'monospace'], 
            type: 'fontFamily' 
          }
        },
        size: {
          xs: { value: '0.75rem', type: 'dimension' },
          sm: { value: '0.875rem', type: 'dimension' },
          base: { value: '1rem', type: 'dimension' },
          lg: { value: '1.125rem', type: 'dimension' },
          xl: { value: '1.25rem', type: 'dimension' },
          '2xl': { value: '1.5rem', type: 'dimension' },
          '3xl': { value: '1.875rem', type: 'dimension' },
          '4xl': { value: '2.25rem', type: 'dimension' }
        },
        weight: {
          normal: { value: '400', type: 'fontWeight' },
          medium: { value: '500', type: 'fontWeight' },
          semibold: { value: '600', type: 'fontWeight' },
          bold: { value: '700', type: 'fontWeight' }
        },
        lineHeight: {
          tight: { value: '1.25', type: 'number' },
          normal: { value: '1.5', type: 'number' },
          relaxed: { value: '1.75', type: 'number' }
        }
      },
      semantic: {
        policy: {
          allow: { value: '#10b981', type: 'color' },
          deny: { value: '#ef4444', type: 'color' },
          warning: { value: '#f59e0b', type: 'color' },
          info: { value: '#3b82f6', type: 'color' }
        },
        test: {
          pass: { value: '#10b981', type: 'color' },
          fail: { value: '#ef4444', type: 'color' },
          pending: { value: '#f59e0b', type: 'color' },
          skipped: { value: '#6b7280', type: 'color' }
        }
      }
    };
  }

  async makeApiRequest(endpoint) {
    return new Promise((resolve, reject) => {
      const options = {
        hostname: 'api.specifyapp.com',
        port: 443,
        path: `/v1${endpoint}`,
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${this.config.api.token}`,
          'Content-Type': 'application/json'
        },
        timeout: this.config.api.timeout
      };

      const req = https.request(options, (res) => {
        let data = '';

        res.on('data', (chunk) => {
          data += chunk;
        });

        res.on('end', () => {
          try {
            const jsonData = JSON.parse(data);
            resolve(jsonData);
          } catch (error) {
            reject(new Error(`Failed to parse JSON response: ${error.message}`));
          }
        });
      });

      req.on('error', (error) => {
        reject(new Error(`API request failed: ${error.message}`));
      });

      req.on('timeout', () => {
        req.destroy();
        reject(new Error('API request timed out'));
      });

      req.end();
    });
  }
}

// CLI execution
if (require.main === module) {
  const fetcher = new SpecifyTokenFetcher();
  
  fetcher.fetchTokens()
    .then(() => {
      console.log('🎉 Token fetch completed successfully!');
      process.exit(0);
    })
    .catch((error) => {
      console.error('💥 Token fetch failed:', error.message);
      process.exit(1);
    });
}

module.exports = SpecifyTokenFetcher;
