#!/usr/bin/env node
// Node.js wrapper to start the Python application
// This allows the app to run on Node.js-based panels (like Pterodactyl with Node.js yolks)

const { spawn } = require('child_process');
const path = require('path');

console.log('[Orbit] Starting Python application...');

// Check if Python is available
const pythonCmd = process.platform === 'win32' ? 'python.exe' : 'python3';

// Start uvicorn
const uvicorn = spawn(pythonCmd, ['-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000'], {
  cwd: __dirname,
  stdio: 'inherit',
  env: { ...process.env, PYTHONUNBUFFERED: '1' }
});

uvicorn.on('error', (err) => {
  console.error('[Orbit] Failed to start uvicorn:', err);
  process.exit(1);
});

uvicorn.on('exit', (code) => {
  console.log(`[Orbit] Uvicorn exited with code ${code}`);
  process.exit(code || 0);
});

// Handle signals
process.on('SIGTERM', () => {
  console.log('[Orbit] Received SIGTERM, shutting down...');
  uvicorn.kill('SIGTERM');
});

process.on('SIGINT', () => {
  console.log('[Orbit] Received SIGINT, shutting down...');
  uvicorn.kill('SIGINT');
});

console.log('[Orbit] Application started on port 8000');