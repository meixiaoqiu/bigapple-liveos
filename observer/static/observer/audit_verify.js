;(function () {
  'use strict';

  var EXPECTED_ABC = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad';
  var _currentRunId = 0;

  // ---- SHA-256 helpers ----

  function bytesToHex(buf) {
    return Array.from(new Uint8Array(buf))
      .map(function (b) { return b.toString(16).padStart(2, '0'); })
      .join('');
  }

  var _sha256FallbackTested = false;
  var _sha256FallbackSelfTestPassed = false;

  function _sha256SelfTest() {
    if (_sha256FallbackTested) return _sha256FallbackSelfTestPassed;
    _sha256FallbackTested = true;
    var raw = _sha256Raw(new TextEncoder().encode('abc'));
    var got = bytesToHex(raw);
    _sha256FallbackSelfTestPassed = (got === EXPECTED_ABC);
    return _sha256FallbackSelfTestPassed;
  }

  function _sha256Raw(data) {
    var K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    var msg = new Uint8Array(data), bitLen = msg.length * 8,
        padLen = (msg.length + 9 + 63) & ~63, padded = new Uint8Array(padLen);
    padded.set(msg);
    padded[msg.length] = 0x80;
    new DataView(padded.buffer).setUint32(padLen - 4, bitLen, false);
    var H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19],
        W = new Uint32Array(64);
    for (var b = 0; b < padLen; b += 64) {
      for (var t = 0; t < 16; t++)
        W[t] = (padded[b + t * 4] << 24) | (padded[b + t * 4 + 1] << 16) | (padded[b + t * 4 + 2] << 8) | padded[b + t * 4 + 3];
      for (t = 16; t < 64; t++)
        W[t] = (function (x) { return ((x >>> 17) | (x << 15)) ^ ((x >>> 19) | (x << 13)) ^ (x >>> 10); })(W[t - 2]) + W[t - 7] + (function (x) { return ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3); })(W[t - 15]) + W[t - 16] >>> 0;
      var a = H[0], b_ = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (t = 0; t < 64; t++) {
        var T1 = (h + (function (x) { return ((x >>> 6) | (x << 26)) ^ ((x >>> 11) | (x << 21)) ^ ((x >>> 25) | (x << 7)); })(e) + (e & f ^ ~e & g) + K[t] + W[t]) >>> 0,
            T2 = ((function (x) { return ((x >>> 2) | (x << 30)) ^ ((x >>> 13) | (x << 19)) ^ ((x >>> 22) | (x << 10)); })(a) + (a & b_ ^ a & c ^ b_ & c)) >>> 0;
        h = g; g = f; f = e; e = (d + T1) >>> 0; d = c; c = b_; b_ = a; a = (T1 + T2) >>> 0;
      }
      H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b_) >>> 0; H[2] = (H[2] + c) >>> 0;
      H[3] = (H[3] + d) >>> 0; H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0;
      H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
    }
    var result = new Uint8Array(32), out = new DataView(result.buffer);
    for (var i = 0; i < 8; i++) out.setUint32(i * 4, H[i], false);
    return result;
  }

  async function sha256Hex(data) {
    if (window.crypto && window.crypto.subtle && window.crypto.subtle.digest) {
      var buf = await window.crypto.subtle.digest('SHA-256', data);
      return bytesToHex(buf);
    }
    if (!_sha256SelfTest()) {
      throw new Error('SHA-256 fallback self-test failed (SHA-256("abc") mismatch)');
    }
    return bytesToHex(_sha256Raw(data));
  }

  // ---- Modal display helpers ----

  function delay(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function _renderStepBox(steps, runId, message, cls, ms) {
    return Promise.resolve().then(function () {
      if (_currentRunId !== runId) return;
      return delay(ms || 350).then(function () {
        if (_currentRunId !== runId) return;
        var pre = document.createElement('pre');
        pre.className = 'whitespace-pre-wrap break-words max-w-full text-xs text-neutral-content';
        pre.setAttribute('data-prefix', '$');
        pre.textContent = message;
        if (cls) pre.classList.add(cls);
        steps.appendChild(pre);
        steps.scrollTop = steps.scrollHeight;
      });
    });
  }

  function _renderJsonBlock(steps, runId, summaryText, jsonText, ms) {
    if (_currentRunId !== runId) return Promise.resolve();
    return delay(ms || 200).then(function () {
      if (_currentRunId !== runId) return;
      var details = document.createElement('details');
      details.className = 'mx-4 my-2 rounded-lg border border-neutral-content/20 bg-neutral text-neutral-content p-3';
      details.open = true;
      var summary = document.createElement('summary');
      summary.className = 'cursor-pointer text-xs font-semibold text-neutral-content';
      summary.textContent = summaryText;
      var pre = document.createElement('pre');
      pre.className = 'mt-2 whitespace-pre-wrap break-words text-xs font-mono max-w-full text-neutral-content/90';
      pre.textContent = jsonText;
      details.appendChild(summary);
      details.appendChild(pre);
      steps.appendChild(details);
      steps.scrollTop = steps.scrollHeight;
    });
  }

  function _renderTitle(steps, runId, text, ms) {
    if (_currentRunId !== runId) return Promise.resolve();
    return delay(ms || 100).then(function () {
      if (_currentRunId !== runId) return;
      var div = document.createElement('div');
      div.className = 'px-4 pt-4 pb-1 text-sm font-bold text-info text-left';
      div.textContent = text;
      steps.appendChild(div);
      steps.scrollTop = steps.scrollHeight;
    });
  }

  function _renderKV(steps, runId, label, value, cls, ms) {
    if (_currentRunId !== runId) return Promise.resolve();
    return delay(ms || 100).then(function () {
      if (_currentRunId !== runId) return;
      var div = document.createElement('div');
      div.className = 'px-4 py-1 text-xs';
      var spanLabel = document.createElement('span');
      spanLabel.className = 'text-neutral-content/70 font-semibold';
      spanLabel.textContent = label;
      var spanVal = document.createElement('span');
      spanVal.className = 'font-mono break-all text-neutral-content ' + (cls || '');
      spanVal.textContent = value;
      div.appendChild(spanLabel);
      div.appendChild(spanVal);
      steps.appendChild(div);
      steps.scrollTop = steps.scrollHeight;
    });
  }

  function _renderLine(steps, runId, text, cls, ms) {
    if (_currentRunId !== runId) return Promise.resolve();
    return delay(ms || 100).then(function () {
      if (_currentRunId !== runId) return;
      var p = document.createElement('p');
      p.className = 'px-4 py-1 text-xs whitespace-pre-wrap break-words max-w-full text-neutral-content ' + (cls || '');
      p.textContent = text;
      steps.appendChild(p);
      steps.scrollTop = steps.scrollHeight;
    });
  }

  function _renderMatchBadge(steps, runId, matched, ms) {
    if (_currentRunId !== runId) return Promise.resolve();
    return delay(ms || 200).then(function () {
      if (_currentRunId !== runId) return;
      var badge = document.createElement('span');
      if (matched) {
        badge.className = 'badge badge-success badge-xs';
        badge.textContent = '匹配';
      } else {
        badge.className = 'badge badge-error badge-xs';
        badge.textContent = '不匹配';
      }
      var p = document.createElement('p');
      p.className = 'px-4 py-1 text-xs';
      p.appendChild(document.createTextNode('对比结果：'));
      p.appendChild(badge);
      steps.appendChild(p);
      steps.scrollTop = steps.scrollHeight;
    });
  }

  // ---- Audit verification ----

  async function runVerification(button) {
    _currentRunId++;
    var runId = _currentRunId;

    var payloadScriptId = button.getAttribute('data-payload-script-id');
    var inputScriptId = button.getAttribute('data-event-hash-input-script-id');
    var seq = button.getAttribute('data-seq');
    var expectedPayloadHash = button.getAttribute('data-expected-payload-hash');
    var expectedEventHash = button.getAttribute('data-expected-event-hash');

    var modal = document.getElementById('audit-verify-modal');
    var steps = document.getElementById('audit-verify-steps');
    var badge = document.getElementById('audit-verify-badge-' + seq);
    if (!modal || !steps) return;

    steps.innerHTML = '';
    modal.showModal();
    var encoder = new TextEncoder();
    button.disabled = true;

    try {
      await _renderStepBox(steps, runId,
        '===== SystemEvent #' + seq + ' 哈希链复算 =====', 'text-info', 100);

      // ---- payload_hash ----
      await _renderTitle(steps, runId, '1. payload_hash 验证', 300);

      var payloadEl = document.getElementById(payloadScriptId);
      if (!payloadEl) {
        await _renderLine(steps, runId, 'ERROR: 未找到 payload JSON script: ' + payloadScriptId, 'text-error', 100);
        return;
      }
      var payloadCanonical;
      try {
        payloadCanonical = JSON.parse(payloadEl.textContent);
      } catch (e) {
        await _renderLine(steps, runId, 'ERROR: payload JSON 解析失败: ' + e.message, 'text-error', 100);
        return;
      }
      await _renderLine(steps, runId, '读取 payload_json 规范化 JSON', 'text-success', 300);
      await _renderJsonBlock(steps, runId,
        '查看实际参与 SHA-256 的 canonical_json(payload_json)',
        payloadCanonical,
        150);

      await _renderStepBox(steps, runId,
        '函数：payload_hash = SHA-256(UTF-8(canonical_json(payload_json)))', 'text-warning', 300);

      var payloadData = encoder.encode(payloadCanonical);
      await _renderKV(steps, runId, 'UTF-8 byte length = ', String(payloadData.length), '', 300);

      var computedPayloadHash = await sha256Hex(payloadData);
      await _renderKV(steps, runId, '浏览器计算值：', computedPayloadHash, 'text-warning', 400);
      await _renderKV(steps, runId, '服务端记录值：', expectedPayloadHash, 'text-info', 200);

      var payloadOk = (computedPayloadHash === expectedPayloadHash);
      await _renderMatchBadge(steps, runId, payloadOk, 300);

      // ---- event_hash ----
      await _renderTitle(steps, runId, '2. event_hash 验证', 400);

      var inputEl = document.getElementById(inputScriptId);
      if (!inputEl) {
        await _renderLine(steps, runId, 'ERROR: 未找到 event_hash_input JSON script: ' + inputScriptId, 'text-error', 100);
        return;
      }
      var eventHashInputCanonical;
      try {
        eventHashInputCanonical = JSON.parse(inputEl.textContent);
      } catch (e) {
        await _renderLine(steps, runId, 'ERROR: event_hash_input JSON 解析失败: ' + e.message, 'text-error', 100);
        return;
      }
      await _renderLine(steps, runId, '读取 event_hash_input 规范化 JSON', 'text-success', 300);
      await _renderJsonBlock(steps, runId,
        '查看实际参与 SHA-256 的 canonical_json(event_hash_input)',
        eventHashInputCanonical,
        150);

      await _renderStepBox(steps, runId,
        '函数：event_hash = SHA-256(UTF-8(canonical_json(event_hash_input)))', 'text-warning', 300);

      var inputData = encoder.encode(eventHashInputCanonical);
      await _renderKV(steps, runId, 'UTF-8 byte length = ', String(inputData.length), '', 300);

      var computedEventHash = await sha256Hex(inputData);
      await _renderKV(steps, runId, '浏览器计算值：', computedEventHash, 'text-warning', 400);
      await _renderKV(steps, runId, '服务端记录值：', expectedEventHash, 'text-info', 200);

      var eventOk = (computedEventHash === expectedEventHash);
      await _renderMatchBadge(steps, runId, eventOk, 300);

      // ---- prev_hash ----
      await _renderTitle(steps, runId, '3. prev_hash 链校验', 400);

      var prevHash = '';
      try {
        var inputObj = JSON.parse(inputEl.textContent);
        prevHash = inputObj.prev_hash || '';
      } catch(e) {}
      await _renderLine(steps, runId,
        'prev_hash 已由服务端校验（需查找上一条 SystemEvent）。', 'text-info', 300);
      if (prevHash) {
        await _renderKV(steps, runId, '本事件记录的 prev_hash：', prevHash, '', 200);
      }

      // ---- summary ----
      await _renderTitle(steps, runId, '结论', 500);
      if (payloadOk && eventOk) {
        await _renderLine(steps, runId,
          '===== 哈希链复算通过：浏览器计算结果与服务端记录一致 =====', 'text-success', 300);
        if (badge) badge.innerHTML = '<span class="badge badge-success badge-xs">复算通过</span>';
      } else {
        await _renderLine(steps, runId,
          '===== 哈希链复算失败：浏览器计算结果与服务端记录不一致 =====', 'text-error', 300);
        if (badge) badge.innerHTML = '<span class="badge badge-error badge-xs">复算失败</span>';
      }
    } catch (e) {
      await _renderLine(steps, runId, 'ERROR: ' + e.message, 'text-error', 100);
      if (badge) badge.innerHTML = '<span class="badge badge-warning badge-xs">计算异常</span>';
    } finally {
      button.disabled = false;
    }
  }

  // ---- Event binding ----

  function bindAuditVerifyButtons() {
    var buttons = document.querySelectorAll('[data-audit-verify-button]');
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      if (btn.getAttribute('data-audit-verify-bound') === '1') continue;
      btn.setAttribute('data-audit-verify-bound', '1');
      btn.addEventListener('click', function () { runVerification(this); });
    }
  }

  // Bind on load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindAuditVerifyButtons);
  } else {
    bindAuditVerifyButtons();
  }

  // Re-bind after HTMX swaps
  document.addEventListener('htmx:afterSwap', bindAuditVerifyButtons);

  // Expose for tests/debugging
  window.BigAppleAuditVerify = {
    bindAuditVerifyButtons: bindAuditVerifyButtons,
    sha256Hex: sha256Hex
  };
})();
