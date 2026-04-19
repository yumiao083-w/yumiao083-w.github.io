// utils/api.js — 统一 API 封装

const BASE_URL = 'https://yolanda083-voice-call-test.hf.space';

function request(url, method = 'GET', data = null, options = {}) {
  return new Promise((resolve, reject) => {
    const config = {
      url: BASE_URL + url,
      method,
      header: {
        'Content-Type': 'application/json',
        ...(options.header || {})
      },
      timeout: options.timeout || 30000,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else {
          reject({ statusCode: res.statusCode, data: res.data });
        }
      },
      fail: (err) => {
        reject(err);
      }
    };
    if (data && method !== 'GET') {
      config.data = data;
    }
    if (options.responseType) {
      config.responseType = options.responseType;
    }
    uni.request(config);
  });
}

// --- 登录相关 ---
export function redeemCode(code) {
  return request('/api/redeem', 'POST', { code });
}

export function login(nickname, password) {
  return request('/api/account/login', 'POST', { nickname, password });
}

export function register(nickname, password) {
  return request('/api/account/register', 'POST', { nickname, password });
}

export function getRegistrationStatus() {
  return request('/api/registration-status');
}

export function getAnnouncement() {
  return request('/api/announcement');
}

// --- 通话记录 ---
export function getCallHistory(token) {
  return request('/api/call-history?token=' + encodeURIComponent(token));
}

export function saveCallHistory(data) {
  return request('/api/call-history', 'POST', data);
}

export function deleteCallHistory(token, callId) {
  return request('/api/call-history', 'DELETE', { token, call_id: callId });
}

// --- 模型 ---
export function getBuiltinModels() {
  return request('/api/builtin-models');
}

export function getModels(baseUrl, apiKey) {
  let url = '/api/models?base_url=' + encodeURIComponent(baseUrl);
  if (apiKey) url += '&api_key=' + encodeURIComponent(apiKey);
  return request(url);
}

// --- 账号 ---
export function getBalance(token) {
  return request('/api/account/balance?token=' + encodeURIComponent(token));
}

export function redeemCard(token, code) {
  return request('/api/account/redeem-card?token=' + encodeURIComponent(token), 'POST', { code });
}

export function getSettings(token) {
  return request('/api/account/settings?token=' + encodeURIComponent(token));
}

export function saveEncryptedSettings(token, encrypted) {
  return request('/api/account/settings?token=' + encodeURIComponent(token), 'POST', { encrypted });
}

// 保持旧名称兼容（加密设置）
export { saveEncryptedSettings as saveCloudSettingsEncrypted };

// --- 云端个人设置（明文，user_id / user_info / topic / extra_prompt）---
export function loadCloudSettings(token) {
  return request('/api/account/load-settings?token=' + encodeURIComponent(token));
}

export function saveCloudSettings(token, settings) {
  return request('/api/account/save-settings?token=' + encodeURIComponent(token), 'POST', settings);
}

// --- 记忆 ---
export function getMemorySummaries(token) {
  return request('/api/memory/summaries?token=' + encodeURIComponent(token));
}

export function generateMemory(data) {
  return request('/api/memory/generate', 'POST', data);
}

export function deleteMemory(token, memoryId) {
  return request('/api/memory/summaries', 'DELETE', { token, id: memoryId });
}

export function updateMemory(token, memoryId, text) {
  return request('/api/memory/summaries', 'PUT', { token, id: memoryId, text });
}

export function setAutoMemory(token, enabled) {
  return request('/api/memory/auto-setting', 'POST', { token, enabled });
}

// --- 反馈 ---
export function submitFeedback(text, contact) {
  return request('/api/feedback', 'POST', { text, contact });
}

// --- 充值 ---
export function getRechargeStatus() {
  return request('/api/recharge/status');
}

// --- STT (语音识别，上传文件) ---
export function submitSTT(token, filePath, options = {}) {
  return new Promise((resolve, reject) => {
    const formData = { token };
    if (options.model) formData.stt_model = options.model;
    if (options.language) formData.language = options.language;

    uni.uploadFile({
      url: BASE_URL + '/api/recognize',
      filePath,
      name: 'audio',
      formData,
      success: (res) => {
        try {
          const data = JSON.parse(res.data);
          resolve(data);
        } catch (e) {
          reject(e);
        }
      },
      fail: reject
    });
  });
}

// --- TTS (语音合成，返回音频 URL) ---
export function submitTTS(token, text, options = {}) {
  return new Promise((resolve, reject) => {
    const data = {
      token,
      text,
      ...options
    };
    uni.request({
      url: BASE_URL + '/api/tts',
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data,
      responseType: 'arraybuffer',
      success: (res) => {
        if (res.statusCode === 200) {
          // 将 arraybuffer 保存为临时文件
          const fs = uni.getFileSystemManager();
          const tmpPath = `${wx.env.USER_DATA_PATH || '_doc'}/tts_${Date.now()}.mp3`;
          // #ifdef APP-PLUS
          const base64 = plus.nativeObj.ArrayBuffer2Base64 ?
            plus.nativeObj.ArrayBuffer2Base64(res.data) :
            uni.arrayBufferToBase64(res.data);
          const filePath = `_doc/tts_${Date.now()}.mp3`;
          plus.io.resolveLocalFileSystemURL('_doc/', (entry) => {
            entry.getFile(`tts_${Date.now()}.mp3`, { create: true }, (fileEntry) => {
              fileEntry.createWriter((writer) => {
                writer.write(res.data);
                writer.onwriteend = () => resolve(fileEntry.toURL());
                writer.onerror = reject;
              });
            }, reject);
          }, reject);
          // #endif
          // #ifdef H5
          const blob = new Blob([res.data], { type: 'audio/mpeg' });
          const url = URL.createObjectURL(blob);
          resolve(url);
          // #endif
        } else {
          reject({ statusCode: res.statusCode });
        }
      },
      fail: reject
    });
  });
}

// --- 结束通话 ---
export function endCall(data) {
  return request('/api/end-call', 'POST', data);
}

// --- 通话详情 ---
export function getCallDetail(token, callId) {
  return request('/api/call-detail/' + callId + '?token=' + encodeURIComponent(token));
}

export function updateCallMessages(token, callId, messages) {
  return request('/api/call-detail/' + callId + '?token=' + encodeURIComponent(token), 'PUT', { messages });
}

// --- 单条通话记忆生成 ---
export function generateCallMemory(token, callId) {
  return request('/api/generate-memory/' + callId + '?token=' + encodeURIComponent(token), 'POST', {}, { timeout: 60000 });
}

// --- SSE 流式对话 ---
// callbacks: { onUserConfirmed, onStatus, onTextDelta, onAudio, onDone, onError, onTtsError }
export function streamChat(token, text, options = {}, callbacks = {}) {
  const data = { text, token, timestamp: new Date().toLocaleString('zh-CN', { hour12: false }) };
  if (options.session_id) data.session_id = options.session_id;
  if (options.custom_prompt) data.custom_prompt = options.custom_prompt;
  if (options.model) data.model = options.model;
  if (options.max_history) data.max_history = options.max_history;
  if (options.custom_api) data.custom_api = options.custom_api;
  if (options.custom_tts) data.custom_tts = options.custom_tts;
  if (options.filter_rules) data.filter_rules = options.filter_rules;
  if (options.history_count !== undefined) data.history_count = options.history_count;
  if (options.image) data.image = options.image;
  if (options.vision_api) data.vision_api = options.vision_api;

  const retryCount = (options.retryCount !== undefined) ? options.retryCount : 3;

  function handleSSELine(content) {
    if (content === '[DONE]') {
      return;
    }
    if (!content || !content.trim()) return;
    try {
      const parsed = JSON.parse(content);
      switch (parsed.type) {
        case 'user_confirmed':
          if (callbacks.onUserConfirmed) callbacks.onUserConfirmed(parsed.text);
          break;
        case 'status':
          if (callbacks.onStatus) callbacks.onStatus(parsed.message);
          break;
        case 'text_delta':
          if (callbacks.onTextDelta) callbacks.onTextDelta(parsed.text);
          break;
        case 'audio':
          console.log('[streamChat] 收到 audio 事件 #' + parsed.index + ', 数据长度: ' + (parsed.audio || '').length);
          if (callbacks.onAudio) callbacks.onAudio(parsed.audio, parsed.text, parsed.index);
          break;
        case 'done':
          if (callbacks.onDone) callbacks.onDone(parsed.stats);
          break;
        case 'error':
          if (callbacks.onError) callbacks.onError(parsed.message);
          break;
        case 'tts_error':
          if (callbacks.onTtsError) callbacks.onTtsError(parsed.text);
          break;
        case 'vision_log':
          if (callbacks.onVisionLog) callbacks.onVisionLog(parsed.text || parsed.message);
          break;
      }
    } catch (e) {
      // JSON 解析失败 — 记录日志方便排查
      console.error('[streamChat] SSE JSON 解析失败:', e.message, '| 数据前100字符:', (content || '').slice(0, 100));
    }
  }

  // 用于跨重试共享的 abort 状态
  let aborted = false;

  // #ifdef H5
  // H5 环境使用 fetch + ReadableStream
  let controller = new AbortController();
  let retryLeft = retryCount;

  function doFetchH5() {
    if (aborted) return;
    controller = new AbortController();

    fetch(BASE_URL + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      signal: controller.signal
    }).then(async (response) => {
      // HTTP 401: 会话过期，不重试
      if (response.status === 401) {
        if (callbacks.onError) callbacks.onError('会话已过期');
        return;
      }
      // HTTP 500/429: 可重试
      if (response.status >= 500 || response.status === 429) {
        retryLeft--;
        if (retryLeft > 0 && !aborted) {
          const attempt = retryCount - retryLeft;
          if (callbacks.onStatus) callbacks.onStatus('API错误，重试中... (' + attempt + '/' + retryCount + ')');
          setTimeout(doFetchH5, 2000);
          return;
        }
        if (callbacks.onError) callbacks.onError('重试失败');
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const content = line.slice(6);
            handleSSELine(content);
          }
        }
      }
    }).catch((err) => {
      if (aborted || err.name === 'AbortError') return;
      // 网络错误：可重试
      retryLeft--;
      if (retryLeft > 0 && !aborted) {
        const attempt = retryCount - retryLeft;
        if (callbacks.onStatus) callbacks.onStatus('网络错误，重试中... (' + attempt + '/' + retryCount + ')');
        setTimeout(doFetchH5, 1500);
      } else {
        if (callbacks.onError) callbacks.onError('重试失败');
      }
    });
  }

  doFetchH5();

  return {
    abort: () => {
      aborted = true;
      try { controller.abort(); } catch (e) {}
    }
  };
  // #endif

  // #ifdef APP-PLUS
  // App 环境使用 XMLHttpRequest
  let currentXhr = null;
  let retryLeftApp = retryCount;
  let _appSseBuffer = ''; // SSE 行缓冲区，防止不完整行被截断

  function doFetchApp() {
    if (aborted) return;
    _appSseBuffer = '';
    const xhr = new plus.net.XMLHttpRequest();
    currentXhr = xhr;
    xhr.open('POST', BASE_URL + '/api/chat');
    xhr.setRequestHeader('Content-Type', 'application/json');
    let lastIndex = 0;

    console.log('[streamChat APP] 发起请求到', BASE_URL + '/api/chat');

    xhr.onreadystatechange = function() {
      if (xhr.readyState >= 3) {
        const responseText = xhr.responseText || '';
        const newData = responseText.substring(lastIndex);
        lastIndex = responseText.length;

        if (newData) {
          // 关键修复：用 buffer 拼接，防止 SSE 行被截断（音频 base64 数据很大）
          _appSseBuffer += newData;
          const lines = _appSseBuffer.split('\n');
          // 最后一个元素可能是不完整行，留在 buffer 里
          _appSseBuffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const content = line.slice(6);
              handleSSELine(content);
            }
          }
        }
      }
      if (xhr.readyState === 4) {
        // 刷出 buffer 中残留的最后一行
        if (_appSseBuffer && _appSseBuffer.trim()) {
          if (_appSseBuffer.startsWith('data: ')) {
            handleSSELine(_appSseBuffer.slice(6));
          }
          _appSseBuffer = '';
        }
        console.log('[streamChat APP] 请求完成 status=' + xhr.status);
        // HTTP 401: 会话过期，不重试
        if (xhr.status === 401) {
          if (callbacks.onError) callbacks.onError('会话已过期');
          return;
        }
        // HTTP 500/429: 可重试
        if (xhr.status >= 500 || xhr.status === 429) {
          retryLeftApp--;
          if (retryLeftApp > 0 && !aborted) {
            const attempt = retryCount - retryLeftApp;
            if (callbacks.onStatus) callbacks.onStatus('API错误，重试中... (' + attempt + '/' + retryCount + ')');
            setTimeout(doFetchApp, 2000);
            return;
          }
          if (callbacks.onError) callbacks.onError('重试失败');
          return;
        }
        // 非 200 且非上述状态（如 0 表示网络错误）
        if (xhr.status !== 200) {
          if (xhr.status === 0) {
            // 网络错误
            retryLeftApp--;
            if (retryLeftApp > 0 && !aborted) {
              const attempt = retryCount - retryLeftApp;
              if (callbacks.onStatus) callbacks.onStatus('网络错误，重试中... (' + attempt + '/' + retryCount + ')');
              setTimeout(doFetchApp, 1500);
              return;
            }
            if (callbacks.onError) callbacks.onError('重试失败');
          } else {
            if (callbacks.onError) callbacks.onError('HTTP ' + xhr.status);
          }
        }
      }
    };

    xhr.onerror = function() {
      if (aborted) return;
      retryLeftApp--;
      if (retryLeftApp > 0 && !aborted) {
        const attempt = retryCount - retryLeftApp;
        if (callbacks.onStatus) callbacks.onStatus('网络错误，重试中... (' + attempt + '/' + retryCount + ')');
        setTimeout(doFetchApp, 1500);
      } else {
        if (callbacks.onError) callbacks.onError('重试失败');
      }
    };

    xhr.send(JSON.stringify(data));
  }

  doFetchApp();

  return {
    abort: () => {
      aborted = true;
      try { if (currentXhr) currentXhr.abort(); } catch (e) {}
    }
  };
  // #endif
}

export { BASE_URL };
