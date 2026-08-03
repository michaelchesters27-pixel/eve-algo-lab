import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const css = fs.readFileSync(new URL('../styles.css', import.meta.url), 'utf8');

test('desktop sidebar is constrained to viewport and navigation can scroll', () => {
  assert.match(css, /@media \(min-width: 761px\)[\s\S]*?\.sidebar\s*\{[\s\S]*?height:\s*100dvh;[\s\S]*?overflow:\s*hidden;/);
  assert.match(css, /\.sidebar \.nav\s*\{[\s\S]*?flex:\s*1 1 auto;[\s\S]*?min-height:\s*0;[\s\S]*?overflow-y:\s*auto;/);
  assert.match(css, /\.sidebar \.side-status\s*\{[\s\S]*?flex:\s*0 0 auto;/);
});

test('mobile navigation does not inherit desktop vertical scrolling', () => {
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.sidebar \.nav\s*\{[\s\S]*?overflow-y:\s*hidden;/);
});
