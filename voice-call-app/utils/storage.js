// utils/storage.js — 本地存储封装

export const KEYS = {
  TOKEN: 'account_token',
  NICKNAME: 'account_nickname',
  API_KEY: 'account_api_key',
  PW_SEED: 'account_pw_seed',
  USER_ID: 'vc_userId',
  USER_INFO: 'vc_userInfo',
  TOPIC: 'vc_topic',
  EXTRA_PROMPT: 'vc_extraPrompt',
  SHOW_SUBTITLE: 'show_subtitle',
  VIDEO_ENABLED: 'video_enabled',
  API_RETRY_COUNT: 'api_retry_count',
  CUSTOM_LLM: 'vc_customLlm',
  CUSTOM_TTS: 'vc_customTts',
  CUSTOM_VISION: 'vc_customVision',
  MAX_HISTORY: 'vc_maxHistory',
  HISTORY_COUNT: 'vc_historyCount',
  BUILTIN_LLM: 'vc_builtinLlm',
  BUILTIN_TTS: 'vc_builtinTts',
  BUILTIN_MODEL: 'vc_builtinModel',
  AUTO_MEMORY: 'vc_autoMemory',
  FILTER_RULES: 'vc_filterRules',
};

export function get(key) {
  try {
    return uni.getStorageSync(key);
  } catch (e) {
    return '';
  }
}

export function set(key, value) {
  try {
    uni.setStorageSync(key, value);
  } catch (e) {}
}

export function remove(key) {
  try {
    uni.removeStorageSync(key);
  } catch (e) {}
}

export function getJSON(key) {
  try {
    const val = uni.getStorageSync(key);
    if (val && typeof val === 'string') return JSON.parse(val);
    return val || null;
  } catch (e) {
    return null;
  }
}

export function setJSON(key, value) {
  try {
    uni.setStorageSync(key, typeof value === 'string' ? value : JSON.stringify(value));
  } catch (e) {}
}
