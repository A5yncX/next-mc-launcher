import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {translate} from './i18n.mjs';

const en = (text, ...args) => translate('en', text, ...args);

test('launcher labels have English translations', () => {
  const source = readFileSync(new URL('./src.jsx', import.meta.url), 'utf8');
  for (const [raw] of source.matchAll(/'[^'\n]*[\u3400-\u9fff][^'\n]*'/gu)) {
    const label = raw.slice(1, -1).replaceAll('\\\\', '\\');
    assert.notEqual(en(label), label, `Missing translation: ${label}`);
  }
});

test('progress details translate while paths and names are preserved', () => {
  assert.equal(en('已取消。下次会复用所有已校验文件。'), 'Cancelled. Verified files will be reused next time.');
  assert.equal(en('下载 assets/foo 失败：timeout'), 'Unable to download assets/foo: timeout');
  assert.equal(en('组件 ZIP 校验失败：文件大小或 SHA-256 不匹配'), 'Component ZIP verification failed: File size or SHA-256 mismatch');
  assert.equal(en('资源准备失败：exit 1。日志：D:\\测试\\prepare.log'), 'Resource preparation failed: exit 1. Log: D:\\测试\\prepare.log');
  assert.equal(en('选用 {1}', '春日世界'), 'Use 春日世界');
  assert.equal(en('external diagnostic'), 'external diagnostic');
  assert.equal(translate('zh-CN', '下载并校验：assets/foo'), '下载并校验：assets/foo');
});
