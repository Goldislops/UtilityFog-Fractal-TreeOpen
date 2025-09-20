// Test setup configuration
process.env.NODE_ENV = 'test';

// Set mock mode by default unless explicitly set to live
if (!process.env.SPECIFY_MODE) {
  process.env.SPECIFY_MODE = 'mock';
}

// Clear SPECIFY_API_TOKEN in mock mode to ensure mock behavior
if (process.env.SPECIFY_MODE === 'mock') {
  delete process.env.SPECIFY_API_TOKEN;
}

console.log(`Test setup: Running in ${process.env.SPECIFY_MODE?.toUpperCase()} mode`);
