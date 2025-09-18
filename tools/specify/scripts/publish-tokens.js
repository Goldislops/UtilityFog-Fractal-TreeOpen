#!/usr/bin/env node

/**
 * Publish Design Tokens
 * 
 * This script publishes transformed design tokens to their target destinations
 * (docs, tests, etc.) and creates backups of existing files.
 */

const fs = require('fs').promises;
const path = require('path');
const config = require('../config/specify.config.js');

class TokenPublisher {
  constructor() {
    this.config = config;
  }

  async publishTokens() {
    console.log('📦 Starting token publishing...');

    try {
      const results = {};

      // Create backup if enabled
      if (this.config.publish.createBackup) {
        await this.createBackups();
      }

      // Publish to each target
      for (const target of this.config.publish.targets) {
        console.log(`🚀 Publishing tokens to ${target.name}...`);
        const result = await this.publishToTarget(target);
        results[target.name] = result;
      }

      console.log('✅ Token publishing completed successfully!');
      return results;

    } catch (error) {
      console.error('❌ Error publishing tokens:', error.message);
      throw error;
    }
  }

  async createBackups() {
    console.log('💾 Creating backups...');
    
    const backupDir = this.config.publish.backupPath;
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const backupPath = path.join(backupDir, `backup-${timestamp}`);
    
    await fs.mkdir(backupPath, { recursive: true });

    for (const target of this.config.publish.targets) {
      try {
        const targetPath = target.path;
        const targetExists = await this.pathExists(targetPath);
        
        if (targetExists) {
          const backupTargetPath = path.join(backupPath, target.name);
          await this.copyDirectory(targetPath, backupTargetPath);
          console.log(`  ✓ Backed up ${target.name} to ${backupTargetPath}`);
        }
      } catch (error) {
        console.warn(`  ⚠️  Could not backup ${target.name}: ${error.message}`);
      }
    }
  }

  async publishToTarget(target) {
    const results = [];
    
    // Ensure target directory exists
    await fs.mkdir(target.path, { recursive: true });

    // Copy each requested format
    for (const format of target.formats) {
      const result = await this.copyTokenFormat(format, target);
      results.push(result);
    }

    return {
      target: target.name,
      path: target.path,
      formats: results,
      publishedAt: new Date().toISOString()
    };
  }

  async copyTokenFormat(format, target) {
    const platformConfig = this.config.transform.platforms[format];
    
    if (!platformConfig || !platformConfig.enabled) {
      throw new Error(`Format ${format} is not enabled or configured`);
    }

    const sourcePath = platformConfig.outputPath;
    const fileName = path.basename(sourcePath);
    const targetPath = path.join(target.path, fileName);

    try {
      // Check if source file exists
      const sourceExists = await this.pathExists(sourcePath);
      if (!sourceExists) {
        throw new Error(`Source file does not exist: ${sourcePath}`);
      }

      // Copy the file
      await fs.copyFile(sourcePath, targetPath);
      
      // Get file stats for reporting
      const stats = await fs.stat(targetPath);
      
      console.log(`  ✓ Published ${format} tokens to ${targetPath}`);
      
      return {
        format: format,
        sourcePath: sourcePath,
        targetPath: targetPath,
        size: stats.size,
        publishedAt: new Date().toISOString()
      };

    } catch (error) {
      console.error(`  ❌ Failed to publish ${format} tokens: ${error.message}`);
      throw error;
    }
  }

  async pathExists(filePath) {
    try {
      await fs.access(filePath);
      return true;
    } catch {
      return false;
    }
  }

  async copyDirectory(source, destination) {
    await fs.mkdir(destination, { recursive: true });
    
    const entries = await fs.readdir(source, { withFileTypes: true });
    
    for (const entry of entries) {
      const sourcePath = path.join(source, entry.name);
      const destPath = path.join(destination, entry.name);
      
      if (entry.isDirectory()) {
        await this.copyDirectory(sourcePath, destPath);
      } else {
        await fs.copyFile(sourcePath, destPath);
      }
    }
  }

  async generatePublishReport(results) {
    const report = {
      publishedAt: new Date().toISOString(),
      targets: results,
      summary: {
        totalTargets: Object.keys(results).length,
        totalFiles: Object.values(results).reduce((sum, target) => sum + target.formats.length, 0),
        totalSize: Object.values(results).reduce((sum, target) => 
          sum + target.formats.reduce((formatSum, format) => formatSum + format.size, 0), 0
        )
      }
    };

    const reportPath = path.join(this.config.publish.backupPath, 'publish-report.json');
    await fs.mkdir(path.dirname(reportPath), { recursive: true });
    await fs.writeFile(reportPath, JSON.stringify(report, null, 2));
    
    console.log(`📊 Publish report saved to ${reportPath}`);
    return report;
  }

  async validatePublishedTokens() {
    console.log('🔍 Validating published tokens...');
    
    const validationResults = [];

    for (const target of this.config.publish.targets) {
      for (const format of target.formats) {
        const platformConfig = this.config.transform.platforms[format];
        const fileName = path.basename(platformConfig.outputPath);
        const publishedPath = path.join(target.path, fileName);
        
        try {
          const exists = await this.pathExists(publishedPath);
          const stats = exists ? await fs.stat(publishedPath) : null;
          
          validationResults.push({
            target: target.name,
            format: format,
            path: publishedPath,
            exists: exists,
            size: stats ? stats.size : 0,
            valid: exists && stats.size > 0
          });

          if (exists && stats.size > 0) {
            console.log(`  ✓ ${target.name}/${format} - Valid (${stats.size} bytes)`);
          } else {
            console.log(`  ❌ ${target.name}/${format} - Invalid or missing`);
          }

        } catch (error) {
          console.error(`  ❌ ${target.name}/${format} - Validation error: ${error.message}`);
          validationResults.push({
            target: target.name,
            format: format,
            path: publishedPath,
            exists: false,
            valid: false,
            error: error.message
          });
        }
      }
    }

    const allValid = validationResults.every(result => result.valid);
    
    if (allValid) {
      console.log('✅ All published tokens are valid!');
    } else {
      console.warn('⚠️  Some published tokens failed validation');
    }

    return {
      allValid: allValid,
      results: validationResults
    };
  }
}

// CLI execution
if (require.main === module) {
  const publisher = new TokenPublisher();
  
  publisher.publishTokens()
    .then(async (results) => {
      // Generate report
      await publisher.generatePublishReport(results);
      
      // Validate published tokens
      await publisher.validatePublishedTokens();
      
      console.log('🎉 Token publishing completed successfully!');
      process.exit(0);
    })
    .catch((error) => {
      console.error('💥 Token publishing failed:', error.message);
      process.exit(1);
    });
}

module.exports = TokenPublisher;
