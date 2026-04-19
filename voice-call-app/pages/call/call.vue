<template>
  <view class="call-page">
    <!-- 背景光效 -->
    <view class="bg-blur"></view>

    <!-- 顶部栏 -->
    <view class="top-bar" :style="{ paddingTop: (statusBarHeight + 10) + 'px' }">
      <view class="back-btn" @tap="goBack">
        <image class="back-icon" :src="icons.chevronLeft" mode="aspectFit" />
        <text class="back-text">返回</text>
      </view>
      <view class="spacer"></view>
      <view class="settings-btn" @tap="showSettings = true">
        <image class="settings-icon" :src="icons.settings" mode="aspectFit" />
      </view>
    </view>

    <!-- 角色信息 -->
    <view class="caller-info">
      <text class="caller-name">{{ characterName }}</text>
      <text class="call-status">{{ statusText }}</text>
      <text class="call-timer" v-if="isInCall">{{ timerStr }}</text>
    </view>

    <!-- 视频预览 -->
    <!-- #ifdef H5 -->
    <view class="video-container" v-if="videoEnabled" :class="{ fullscreen: videoFullscreen }" :style="{ top: videoFullscreen ? 0 : (statusBarHeight + 90) + 'px' }" @tap="videoFullscreen = !videoFullscreen">
      <video ref="videoPreview" class="video-preview" autoplay playsinline muted :style="{ transform: facingMode === 'user' ? 'scaleX(-1)' : '' }"></video>
      <view class="video-switch-btn" @tap.stop="switchCamera">
        <text class="video-switch-icon">🔄</text>
      </view>
    </view>
    <canvas ref="videoCanvas" style="display:none;"></canvas>
    <!-- #endif -->

    <!-- #ifdef APP-PLUS -->
    <view class="video-container" v-if="videoEnabled" :class="{ fullscreen: videoFullscreen }" :style="{ top: videoFullscreen ? 0 : (statusBarHeight + 90) + 'px' }" @tap="videoFullscreen = !videoFullscreen">
      <camera :device-position="facingMode === 'user' ? 'front' : 'back'" flash="off" class="video-preview"></camera>
      <view class="video-switch-btn" @tap.stop="switchCamera">
        <text class="video-switch-icon">🔄</text>
      </view>
    </view>
    <!-- #endif -->

    <!-- 字幕区 -->
    <scroll-view class="subtitle-area" scroll-y :scroll-top="subtitleScrollTop" v-if="showSubtitle">
      <view class="subtitle-bubble-row right" v-if="userText">
        <view class="subtitle-bubble user-bubble">
          <text class="subtitle-bubble-text">{{ userText }}</text>
        </view>
      </view>
      <view class="subtitle-bubble-row left" v-if="aiText">
        <view class="subtitle-bubble ai-bubble">
          <text class="subtitle-bubble-text ai-bubble-text">{{ aiText }}</text>
        </view>
      </view>
    </scroll-view>

    <!-- 文字输入 -->
    <view class="text-input-area" v-if="isInCall">
      <input class="text-input" v-model="textInput" placeholder="输入文字..." @confirm="sendTextInput" />
      <text class="send-btn" @tap="sendTextInput">发送</text>
    </view>

    <!-- 拨号按钮 -->
    <view class="controls" v-if="!isInCall">
      <view class="dial-btn" @tap="startCall">
        <image class="dial-icon-img" :src="icons.phoneCall" mode="aspectFit" />
      </view>
      <text class="dial-hint">点击拨号</text>
    </view>

    <!-- 通话中控制栏 -->
    <view class="control-bar" v-if="isInCall">
      <view class="ctrl-wrap">
        <view class="ctrl-btn" :class="{ active: isMuted }" @tap="toggleMute">
          <view class="ctrl-inner">
            <image class="ctrl-icon" :src="isMuted ? icons.micOff : icons.mic" mode="aspectFit" />
          </view>
        </view>
        <text class="ctrl-label">{{ isMuted ? '取消静音' : '静音' }}</text>
      </view>
      <view class="ctrl-wrap">
        <view class="ctrl-btn" :class="{ active: videoEnabled }" @tap="toggleVideo">
          <view class="ctrl-inner">
            <image class="ctrl-icon" :src="icons.video" mode="aspectFit" />
          </view>
        </view>
        <text class="ctrl-label">{{ videoEnabled ? '关闭视频' : '视频' }}</text>
      </view>
      <view class="ctrl-wrap">
        <view class="hangup-btn" @tap="endCall">
          <image class="hangup-icon" :src="icons.phoneHangup" mode="aspectFit" />
        </view>
      </view>
      <view class="ctrl-wrap">
        <view class="ctrl-btn" :class="{ active: isSpeaker }" @tap="toggleSpeaker">
          <view class="ctrl-inner">
            <image class="ctrl-icon" :src="icons.speaker" mode="aspectFit" />
          </view>
        </view>
        <text class="ctrl-label">免提</text>
      </view>
    </view>

    <!-- 设置弹窗 -->
    <view class="settings-overlay" v-if="showSettings" @tap.self="showSettings = false">
      <view class="settings-panel">
        <view class="settings-header">
          <text class="settings-title">通话设置</text>
          <text class="settings-close" @tap="showSettings = false">✕</text>
        </view>
        <scroll-view class="settings-body" scroll-y>
          <!-- 对话模型 -->
          <view class="settings-section">
            <text class="settings-section-title">对话模型</text>
            <view class="setting-item">
              <text class="setting-label">使用内置模型</text>
              <switch :checked="sUseBuiltinLlm" @change="sUseBuiltinLlm = $event.detail.value" color="#34C759" />
            </view>
            <view v-if="sUseBuiltinLlm" class="setting-item column">
              <text class="setting-label">内置模型</text>
              <picker :range="builtinModels" :value="builtinModelIdx" @change="onBuiltinModelChange">
                <view class="setting-input picker-display">{{ sBuiltinModel || '点击选择模型' }}</view>
              </picker>
            </view>
            <view v-else>
              <view class="setting-item column">
                <text class="setting-label">API 地址</text>
                <input class="setting-input" v-model="sLlmUrl" placeholder="https://api.example.com/v1" />
              </view>
              <view class="setting-item column">
                <text class="setting-label">API Key</text>
                <input class="setting-input" v-model="sLlmKey" placeholder="sk-..." password />
              </view>
              <view class="setting-item column">
                <text class="setting-label">模型名称</text>
                <input class="setting-input" v-model="sLlmModel" placeholder="gpt-4o" />
              </view>
              <view class="setting-item">
                <text class="settings-fetch-btn" @tap="fetchLlmModels">{{ sLlmFetching ? '获取中...' : '获取模型列表' }}</text>
              </view>
              <scroll-view v-if="sLlmModelList.length" class="settings-model-list" scroll-y>
                <view v-for="(m, i) in sLlmModelList" :key="i" class="settings-model-item" :class="{ selected: sLlmModel === m }" @tap="sLlmModel = m">
                  <text class="settings-model-name">{{ m }}</text>
                </view>
              </scroll-view>
            </view>
          </view>

          <!-- 对话偏好 -->
          <view class="settings-section">
            <text class="settings-section-title">对话偏好</text>
            <view class="setting-item column">
              <text class="setting-label">用户称呼</text>
              <input class="setting-input" v-model="userId" placeholder="你的名字" />
            </view>
            <view class="setting-item column">
              <text class="setting-label">话题</text>
              <input class="setting-input" v-model="topic" placeholder="聊什么话题" />
            </view>
            <view class="setting-item column">
              <text class="setting-label">关于用户</text>
              <textarea class="setting-textarea" v-model="sUserInfo" placeholder="描述一下自己，帮助AI更了解你" />
            </view>
            <view class="setting-item column">
              <text class="setting-label">额外提示词</text>
              <textarea class="setting-textarea" v-model="sExtraPrompt" placeholder="额外的角色设定..." />
            </view>
          </view>

          <!-- 对话记忆 -->
          <view class="settings-section">
            <text class="settings-section-title">对话记忆</text>
            <view class="setting-item column">
              <text class="setting-label">保留最近对话轮数 (1-100)</text>
              <input class="setting-input" v-model="maxHistory" type="number" placeholder="20" />
            </view>
            <view class="setting-item column">
              <text class="setting-label">加载历史通话总结 (0=不加载)</text>
              <input class="setting-input" v-model="sHistoryCount" type="number" placeholder="0" />
            </view>
          </view>

          <!-- 通话显示 -->
          <view class="settings-section">
            <text class="settings-section-title">通话显示</text>
            <view class="setting-item">
              <text class="setting-label">显示通话字幕</text>
              <switch :checked="showSubtitle" @change="showSubtitle = $event.detail.value" color="#34C759" />
            </view>
          </view>

          <!-- 网络 -->
          <view class="settings-section">
            <text class="settings-section-title">网络</text>
            <view class="setting-item column">
              <text class="setting-label">API 报错重试次数 (0-10)</text>
              <input class="setting-input" v-model="sRetryCount" type="number" placeholder="3" />
            </view>
          </view>

          <!-- 过滤规则 -->
          <view class="settings-section">
            <text class="settings-section-title">输出过滤规则</text>
            <view class="profile-section-desc" style="margin-bottom:16rpx;">
              <text style="color:#8E8E93;font-size:24rpx;">用正则表达式过滤AI输出中的特定内容</text>
            </view>
            <view v-for="(rule, ri) in sFilterRules" :key="ri" class="filter-rule-item">
              <view class="filter-rule-inputs">
                <input class="setting-input filter-input" v-model="sFilterRules[ri].pattern" placeholder="正则表达式" />
                <input class="setting-input filter-input" v-model="sFilterRules[ri].replace" placeholder="替换为（留空则删除）" />
              </view>
              <text class="filter-rule-del" @tap="sFilterRules.splice(ri, 1)">✕</text>
            </view>
            <view class="filter-rule-add" @tap="sFilterRules.push({pattern:'', replace:''})">
              <text style="color:#0A84FF;font-size:28rpx;">+ 添加规则</text>
            </view>
          </view>

          <!-- 识图模型 -->
          <view class="settings-section">
            <text class="settings-section-title">识图模型（视频通话）</text>
            <view class="setting-item">
              <text class="setting-label">使用独立识图模型</text>
              <switch :checked="sUseCustomVision" @change="sUseCustomVision = $event.detail.value" color="#34C759" />
            </view>
            <view class="profile-section-desc" style="margin-top:4rpx;margin-bottom:16rpx;">
              <text style="color:#8E8E93;font-size:24rpx;">开启后，视频截图将用独立模型识图；关闭则用当前对话模型</text>
            </view>
            <view v-if="sUseCustomVision">
              <view class="setting-item column">
                <text class="setting-label">API 地址</text>
                <input class="setting-input" v-model="sVisionUrl" placeholder="https://api.example.com/v1" />
              </view>
              <view class="setting-item column">
                <text class="setting-label">API Key</text>
                <input class="setting-input" v-model="sVisionKey" placeholder="sk-..." password />
              </view>
              <view class="setting-item column">
                <text class="setting-label">模型名称</text>
                <input class="setting-input" v-model="sVisionModel" placeholder="gpt-4o-mini" />
              </view>
            </view>
          </view>

          <!-- 语音合成 -->
          <view class="settings-section">
            <text class="settings-section-title">语音合成</text>
            <view class="setting-item">
              <text class="setting-label">使用内置语音</text>
              <switch :checked="sUseBuiltinTts" @change="sUseBuiltinTts = $event.detail.value" color="#34C759" />
            </view>
            <view v-if="!sUseBuiltinTts">
              <view class="setting-item column">
                <text class="setting-label">TTS API Key</text>
                <input class="setting-input" v-model="sTtsKey" placeholder="MiniMax API Key" password />
              </view>
              <view class="setting-item column">
                <text class="setting-label">Group ID</text>
                <input class="setting-input" v-model="sTtsGroupId" placeholder="Group ID" />
              </view>
              <view class="setting-item column">
                <text class="setting-label">Voice ID</text>
                <input class="setting-input" v-model="sTtsVoiceId" placeholder="male-qn-qingse" />
              </view>
              <view class="setting-item column">
                <text class="setting-label">TTS 模型</text>
                <picker :range="['speech-2.8-hd', 'speech-2.8-turbo']" :value="sTtsModelIdx" @change="sTtsModelIdx = $event.detail.value">
                  <view class="setting-input picker-display">{{ ['speech-2.8-hd', 'speech-2.8-turbo'][sTtsModelIdx] }}</view>
                </picker>
              </view>
            </view>
          </view>

          <!-- 保存按钮 -->
          <view class="settings-save-btn" @tap="saveAllSettings">
            <text class="settings-save-text">保存并应用</text>
          </view>

          <!-- 调试日志 -->
          <view class="settings-section" style="margin-top: 32rpx;">
            <text class="settings-section-title">调试日志</text>
            <scroll-view class="log-content" scroll-y>
              <view v-for="(line, i) in logLines" :key="i" class="log-line">
                <text :class="'log-' + line.level">{{ line.time }} [{{ line.level }}] {{ line.msg }}</text>
              </view>
              <view v-if="!logLines.length" style="padding: 24rpx;">
                <text style="color: #636366; font-size: 24rpx;">暂无日志</text>
              </view>
            </scroll-view>
            <view class="log-actions">
              <view class="log-action-btn" @tap="copyLog"><text style="color: #fff; font-size: 26rpx;">复制日志</text></view>
              <view class="log-action-btn" @tap="logLines = []"><text style="color: #fff; font-size: 26rpx;">清空</text></view>
            </view>
          </view>
        </scroll-view>
      </view>
    </view>
  </view>
</template>

<script>
import { submitSTT, streamChat, endCall as apiEndCall, getBuiltinModels, getModels } from '../../utils/api.js';
import { Recorder, AudioPlayer } from '../../utils/audio.js';
import { get, set, getJSON, setJSON, KEYS } from '../../utils/storage.js';

export default {
  data() {
    const svgUri = (path, size=24, color='%23fff') => `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 ${size} ${size}' fill='${color}'%3E${path}%3C/svg%3E`;
    return {
      icons: {
        mic: svgUri("%3Cpath d='M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z'/%3E%3Cpath d='M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z'/%3E"),
        micOff: svgUri("%3Cpath d='M19 11c0 .73-.13 1.43-.37 2.09l1.53 1.53C20.69 13.51 21 12.29 21 11h-2zM4.27 3L3 4.27l6 6V11c0 1.66 1.34 3 3 3 .23 0 .44-.03.65-.08l1.66 1.66c-.71.33-1.5.52-2.31.52-2.76 0-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c1.37-.2 2.63-.82 3.65-1.68l2.08 2.08 1.27-1.27L4.27 3zM12 4c-1.66 0-3 1.34-3 3v.18l7 7V7c0-1.66-1.34-3-3-3z'/%3E"),
        video: svgUri("%3Cpath d='M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z'/%3E"),
        phoneHangup: svgUri("%3Cpath d='M20.01 15.38c-1.23 0-2.42-.2-3.53-.56-.35-.12-.74-.03-1.01.24l-1.57 1.97c-2.83-1.35-5.48-3.9-6.89-6.83l1.95-1.66c.27-.28.35-.67.24-1.02-.37-1.11-.56-2.3-.56-3.53 0-.54-.45-.99-.99-.99H4.19C3.65 3 3 3.24 3 3.99 3 13.28 10.73 21 20.01 21c.71 0 .99-.63.99-1.18v-3.45c0-.54-.45-.99-.99-.99z'/%3E"),
        phoneCall: svgUri("%3Cpath d='M20.01 15.38c-1.23 0-2.42-.2-3.53-.56-.35-.12-.74-.03-1.01.24l-1.57 1.97c-2.83-1.35-5.48-3.9-6.89-6.83l1.95-1.66c.27-.28.35-.67.24-1.02-.37-1.11-.56-2.3-.56-3.53 0-.54-.45-.99-.99-.99H4.19C3.65 3 3 3.24 3 3.99 3 13.28 10.73 21 20.01 21c.71 0 .99-.63.99-1.18v-3.45c0-.54-.45-.99-.99-.99z'/%3E"),
        speaker: svgUri("%3Cpath d='M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z'/%3E"),
        settings: svgUri("%3Cpath d='M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.49.49 0 00-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.09-.49 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z'/%3E"),
        chevronLeft: svgUri("%3Cpath d='M15.41 16.59L10.83 12l4.58-4.59L14 6l-6 6 6 6 1.41-1.41z'/%3E"),
      },
      token: '',
      characterName: '袁朗',
      isInCall: false,
      isMuted: false,
      isSpeaker: false,
      isAiSpeaking: false,
      showSubtitle: true,
      showSettings: false,
      statusText: '准备拨号',
      timerStr: '00:00',
      userText: '',
      aiText: '',
      currentAiFullText: '',
      textInput: '',
      subtitleScrollTop: 0,
      userId: '',
      topic: '',
      maxHistory: 20,
      // 设置弹窗新增
      sUseBuiltinLlm: true,
      sBuiltinModel: '',
      builtinModels: [],
      builtinModelIdx: 0,
      sLlmUrl: '',
      sLlmKey: '',
      sLlmModel: '',
      sLlmModelList: [],
      sLlmFetching: false,
      sExtraPrompt: '',
      sUserInfo: '',
      sHistoryCount: 0,
      sRetryCount: 3,
      sUseBuiltinTts: true,
      sTtsKey: '',
      sTtsGroupId: '',
      sTtsVoiceId: '',
      sTtsModelIdx: 0,
      logLines: [],

      // 识图模型设置
      sUseCustomVision: false,
      sVisionUrl: '',
      sVisionKey: '',
      sVisionModel: '',

      // 过滤规则
      sFilterRules: [],  // [{pattern: '正则', replace: '替换文本'}]

      // 内部状态
      sessionId: 'vc_' + Date.now(),
      statusBarHeight: 44,
      callStartTime: null,
      timerInterval: null,
      recorder: null,
      audioPlayer: null,
      chatAbort: null,
      messages: [],
      // 音频片段收集
      audioSegments: [],
      assistantMsgCount: 0,

      // === 视频通话 ===
      videoEnabled: false,        // 摄像头是否开启
      videoStream: null,          // H5: MediaStream 对象
      latestVideoFrame: '',       // 最新截帧 base64 JPEG（不含 data: 前缀）
      videoCaptureTimer: null,    // 截帧定时器
      videoFullscreen: false,     // 预览窗口是否全屏
      facingMode: 'user',         // 'user'=前置, 'environment'=后置
      cameraContext: null,        // APP: camera 组件上下文
      customVision: null,         // 独立识图模型 {base_url, api_key, model}
    };
  },

  onLoad(query) {
    // 获取状态栏高度
    try {
      const sysInfo = uni.getSystemInfoSync();
      this.statusBarHeight = sysInfo.statusBarHeight || 44;
    } catch (e) {}
    this.token = query.token || get(KEYS.TOKEN) || '';
    if (!this.token) {
      uni.redirectTo({ url: '/pages/login/login' });
      return;
    }
    // 读本地设置
    this.showSubtitle = get(KEYS.SHOW_SUBTITLE) !== 'false';
    this.userId = get(KEYS.USER_ID) || '';
    this.topic = get(KEYS.TOPIC) || '';
    this.maxHistory = parseInt(get(KEYS.MAX_HISTORY)) || 20;
    this.sExtraPrompt = get(KEYS.EXTRA_PROMPT) || '';
    this.sUserInfo = get(KEYS.USER_INFO) || '';
    this.sHistoryCount = parseInt(get(KEYS.HISTORY_COUNT)) || 0;
    this.sRetryCount = parseInt(get(KEYS.API_RETRY_COUNT)) || 3;
    // LLM 配置
    const savedLlm = getJSON(KEYS.CUSTOM_LLM);
    if (savedLlm && savedLlm.base_url) {
      this.sUseBuiltinLlm = false;
      this.sLlmUrl = savedLlm.base_url || '';
      this.sLlmKey = savedLlm.api_key || '';
      this.sLlmModel = savedLlm.model || '';
    }
    this.sBuiltinModel = get(KEYS.BUILTIN_MODEL) || '';
    // TTS 配置
    const savedTts = getJSON(KEYS.CUSTOM_TTS);
    if (savedTts && savedTts.api_key) {
      this.sUseBuiltinTts = false;
      this.sTtsKey = savedTts.api_key || '';
      this.sTtsGroupId = savedTts.group_id || '';
      this.sTtsVoiceId = savedTts.voice_id || '';
    }
    // 加载内置模型
    this.loadBuiltinModels();
    // 读取识图模型配置
    const savedVision = getJSON(KEYS.CUSTOM_VISION);
    if (savedVision && savedVision.base_url && savedVision.api_key) {
      this.sUseCustomVision = true;
      this.sVisionUrl = savedVision.base_url || '';
      this.sVisionKey = savedVision.api_key || '';
      this.sVisionModel = savedVision.model || '';
      this.customVision = savedVision;
    }
    // 读取视频开关（不自动开摄像头，仅恢复状态记忆）
    // 如需自动开启，取消下面注释：
    // if (get(KEYS.VIDEO_ENABLED) === 'true') this.startVideo();
    // 读取过滤规则
    const savedRules = getJSON(KEYS.FILTER_RULES);
    if (Array.isArray(savedRules)) {
      this.sFilterRules = savedRules;
    }
  },

  onUnload() {
    this.cleanup();
  },

  methods: {
    // === 通话控制 ===
    startCall() {
      this.isInCall = true;

      // 环境检测日志
      try {
        const sysInfo = uni.getSystemInfoSync();
        this.addLog('info', '=== 通话开始 ===');
        this.addLog('info', '设备: ' + (sysInfo.brand || '') + ' ' + (sysInfo.model || ''));
        this.addLog('info', '系统: ' + (sysInfo.platform || '') + ' ' + (sysInfo.system || ''));
        this.addLog('info', '屏幕: ' + sysInfo.screenWidth + 'x' + sysInfo.screenHeight + ' DPR=' + (sysInfo.pixelRatio || ''));
        this.addLog('info', '运行环境: ' + (sysInfo.uniPlatform || sysInfo.host?.appId || 'unknown'));
        // #ifdef APP-PLUS
        this.addLog('info', '平台: APP-PLUS');
        this.addLog('info', 'plus.io: ' + (typeof plus !== 'undefined' && plus.io ? '✅' : '❌'));
        this.addLog('info', 'uni.base64ToArrayBuffer: ' + (typeof uni.base64ToArrayBuffer === 'function' ? '✅' : '❌'));
        // #endif
        // #ifdef H5
        this.addLog('info', '平台: H5');
        this.addLog('info', 'UA: ' + navigator.userAgent.slice(0, 80));
        // #endif
      } catch (e) {
        this.addLog('warn', '环境检测失败: ' + (e.message || e));
      }

      // #ifdef H5
      // 解锁音频自动播放限制
      try {
        const unlockCtx = new (window.AudioContext || window.webkitAudioContext)();
        const buf = unlockCtx.createBuffer(1, 1, 22050);
        const src = unlockCtx.createBufferSource();
        src.buffer = buf;
        src.connect(unlockCtx.destination);
        src.start(0);
        setTimeout(() => { try { unlockCtx.close(); } catch(e) {} }, 100);
        this.addLog('info', '✅ H5 音频已解锁');
      } catch(e) {
        this.addLog('warn', 'H5 音频解锁失败: ' + (e.message || e));
      }
      // #endif
      this.messages = [];
      this.audioSegments = [];
      this.assistantMsgCount = 0;
      this.statusText = '已连接';
      this.userText = '';
      this.aiText = '';
      this.currentAiFullText = '';
      this.callStartTime = Date.now();

      // 计时器
      this.timerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - this.callStartTime) / 1000);
        const m = Math.floor(elapsed / 60).toString().padStart(2, '0');
        const s = (elapsed % 60).toString().padStart(2, '0');
        this.timerStr = m + ':' + s;
      }, 1000);

      // 初始化录音
      this.initRecorder();

      // 初始化播放器
      this.audioPlayer = new AudioPlayer({
        onLog: (level, msg) => {
          this.addLog(level, '[播放器] ' + msg);
        },
        onPlayEnd: () => {},
        onAllEnd: () => {
          this.addLog('info', '所有音频播放完毕，恢复录音');
          this.isAiSpeaking = false;
          this.statusText = '已连接';
          this.startRecording();
        },
        onError: (err) => {
          const errMsg = err && err.errMsg ? err.errMsg : JSON.stringify(err);
          this.addLog('error', '播放器回调错误: ' + errMsg);
          this.isAiSpeaking = false;
          this.startRecording();
        }
      });
    },

    endCall() {
      this.isInCall = false;
      this.addLog('info', '=== 通话结束 ===');
      this.addLog('info', '通话时长: ' + this.timerStr + ' | 消息数: ' + this.messages.length + ' | 音频段: ' + this.audioSegments.length);
      this.statusText = '正在保存...';
      clearInterval(this.timerInterval);

      // 停止录音
      if (this.recorder) {
        this.recorder.stop();
      }
      // 停止播放
      if (this.audioPlayer) {
        this.audioPlayer.stop();
      }
      // 中断流式请求
      if (this.chatAbort) {
        this.chatAbort.abort();
        this.chatAbort = null;
      }

      // 调用 end-call API（包含音频片段）
      const chunksToSend = this.audioSegments.slice();
      this.audioSegments = [];
      apiEndCall({
        token: this.token,
        session_id: this.sessionId,
        audio_chunks: chunksToSend,
        auto_memory: get(KEYS.AUTO_MEMORY) === 'true'
      }).then(data => {
        if (data.summary) {
          this.aiText = '💌 ' + data.summary;
        }
        this.statusText = '✅ 通话记录已保存';
      }).catch(() => {
        this.statusText = '通话已结束';
      });

      setTimeout(() => {
        uni.navigateBack();
      }, 2000);
    },

    cleanup() {
      clearInterval(this.timerInterval);
      if (this.recorder) this.recorder.stop();
      if (this.audioPlayer) {
        this.audioPlayer.destroy();
      }
      if (this.chatAbort) {
        this.chatAbort.abort();
      }
      // 清理视频资源
      this.stopVideoCapture();
      if (this.videoEnabled) {
        this.stopVideo();
      }
    },

    goBack() {
      if (this.isInCall) {
        uni.showModal({
          title: '确认挂断',
          content: '通话进行中，确认要挂断吗？',
          success: (res) => {
            if (res.confirm) this.endCall();
          }
        });
      } else {
        uni.navigateBack();
      }
    },

    // === 录音 ===
    initRecorder() {
      this.recorder = new Recorder({
        onStop: (res) => {
          if (!this.isInCall || this.isMuted || this.isAiSpeaking) return;
          // VAD: 检查是否有有效声音
          if (!this.recorder.hasVoiceActivity) {
            this.addLog('info', '录音无声音，跳过 STT');
            this.statusText = '聆听中...';
            // 无声音，直接重新开始录音
            setTimeout(() => this.startRecording(), 200);
            return;
          }
          // 收集用户录音到 audioSegments
          this.collectUserAudio(res.tempFilePath);
          this.handleRecordingResult(res.tempFilePath);
        },
        onError: (err) => {
          console.error('录音错误:', err);
          if (this.isInCall && !this.isMuted) {
            setTimeout(() => this.startRecording(), 1000);
          }
        },
        onVolumeChange: (volume) => {
          // 可选：根据音量更新状态文字
          if (this.isInCall && !this.isMuted && !this.isAiSpeaking) {
            if (this.recorder && this.recorder.hasVoiceActivity) {
              this.statusText = '聆听中... 🎤';
            }
          }
        }
      });
      this.startRecording();
    },

    startRecording() {
      if (!this.isInCall || this.isMuted || this.isAiSpeaking) return;
      if (!this.recorder) return;
      this.statusText = '聆听中...';
      this.addLog('info', '开始录音（VAD 自动截断）');
      this.recorder.start();
    },

    // === STT ===
    // 收集用户录音为 base64（异步，不阻塞 STT 流程）
    collectUserAudio(filePath) {
      try {
        // #ifdef APP-PLUS
        plus.io.resolveLocalFileSystemURL(filePath, (entry) => {
          entry.file((file) => {
            const reader = new plus.io.FileReader();
            reader.onloadend = (e) => {
              // result 格式: data:audio/xxx;base64,XXXX
              const dataUrl = e.target.result;
              const b64 = dataUrl.split(',')[1] || dataUrl;
              this.audioSegments.push({
                type: 'user',
                audio_b64: b64,
                format: 'mp4',
                timestamp: Date.now()
              });
            };
            reader.readAsDataURL(file);
          });
        }, (err) => {
          console.error('collectUserAudio plus.io error:', err);
        });
        // #endif
        // #ifdef H5
        // H5 环境下 uni.getFileSystemManager 不可用，尝试 fetch
        fetch(filePath).then(r => r.blob()).then(blob => {
          const reader = new FileReader();
          reader.onloadend = () => {
            const b64 = reader.result.split(',')[1] || reader.result;
            this.audioSegments.push({
              type: 'user',
              audio_b64: b64,
              format: 'webm',
              timestamp: Date.now()
            });
          };
          reader.readAsDataURL(blob);
        }).catch(err => {
          console.error('collectUserAudio H5 error:', err);
        });
        // #endif
      } catch (e) {
        console.error('collectUserAudio error:', e);
      }
    },

    async handleRecordingResult(filePath) {
      this.statusText = '语音识别中...';
      this.userText = '识别中...';
      this.addLog('info', '发送录音到 STT: ' + filePath);
      try {
        const sttOptions = {};
        const result = await submitSTT(this.token, filePath, sttOptions);
        const text = (result.text || '').trim();
        if (!text) {
          this.addLog('info', 'STT 返回空（静音段）');
          this.userText = '';
          this.statusText = '已连接';
          this.startRecording();
          return;
        }
        const engineInfo = result.engine ? (' [' + result.engine + ']') : '';
        const timeInfo = result.time ? (' ' + result.time + 's') : '';
        this.addLog('info', 'STT 识别: 「' + text.slice(0, 40) + '」' + engineInfo + timeInfo);
        this.userText = text;
        this.sendToChat(text);
      } catch (err) {
        const errMsg = err.message || (err.data && err.data.error) || JSON.stringify(err).slice(0, 100);
        this.addLog('error', 'STT 失败: ' + errMsg);
        console.error('STT 失败:', err);
        this.statusText = '识别失败，继续聆听...';
        this.startRecording();
      }
    },

    // === 流式对话 ===
    sendToChat(text) {
      if (!this.token) {
        this.addLog('error', 'sendToChat: 无 token，无法发送');
        this.statusText = '⚠️ 未登录';
        return;
      }
      this.addLog('info', '>>> 发送消息: ' + text.slice(0, 50) + (text.length > 50 ? '...' : ''));
      this.addLog('info', '会话: ' + this.sessionId + ' | 历史: ' + this.messages.length + '条 | 重试: ' + (this.sRetryCount || 3));
      this.messages.push({ role: 'user', content: text });
      this.isAiSpeaking = true;
      this.currentAiFullText = '';
      this.aiText = '';
      this.statusText = '思考中...';

      // 构建 options
      let customPrompt = '';
      if (this.userId) customPrompt += '# 用户称呼\n' + this.userId + '\n\n';
      if (this.topic) customPrompt += '# 本次话题\n' + this.topic + '\n\n';
      const userInfo = get(KEYS.USER_INFO) || '';
      const extraPrompt = get(KEYS.EXTRA_PROMPT) || '';
      if (userInfo) customPrompt += '# 关于用户\n' + userInfo + '\n\n';
      if (extraPrompt) customPrompt += '# 补充设定\n' + extraPrompt + '\n\n';

      const options = { session_id: this.sessionId };
      options.retryCount = this.sRetryCount || 3;
      if (customPrompt) options.custom_prompt = customPrompt;
      if (this.maxHistory) options.max_history = parseInt(this.maxHistory);
      if (this.sHistoryCount > 0) options.history_count = parseInt(this.sHistoryCount);
      if (this.sFilterRules && this.sFilterRules.length > 0) options.filter_rules = this.sFilterRules;

      // 自定义 LLM
      const customLlm = get(KEYS.CUSTOM_LLM);
      if (customLlm) {
        try {
          const llm = typeof customLlm === 'string' ? JSON.parse(customLlm) : customLlm;
          if (llm && llm.base_url && llm.api_key) options.custom_api = llm;
        } catch (e) {}
      }

      // 自定义 TTS
      const customTts = get(KEYS.CUSTOM_TTS);
      if (customTts) {
        try {
          const tts = typeof customTts === 'string' ? JSON.parse(customTts) : customTts;
          if (tts && tts.api_key) options.custom_tts = tts;
        } catch (e) {}
      }

      const builtinModel = get(KEYS.BUILTIN_MODEL);
      if (builtinModel && !options.custom_api) options.model = builtinModel;

      // 附加视频截帧
      if (this.latestVideoFrame) {
        options.image = this.latestVideoFrame;
        this.addLog('debug', '附加视频截图 (' + Math.round(this.latestVideoFrame.length / 1024) + 'KB)');
        // 独立识图模型
        if (this.customVision && this.customVision.base_url && this.customVision.api_key) {
          options.vision_api = this.customVision;
        }
      }

      const self = this;

      this.chatAbort = streamChat(this.token, text, options, {
        onUserConfirmed(confirmedText) {
          self.addLog('info', '✅ 服务端已确认收到文本');
          self.statusText = '已收到，正在处理...';
        },
        onStatus(message) {
          self.addLog('info', '状态: ' + message);
          self.statusText = message;
        },
        onTextDelta(delta) {
          self.currentAiFullText += delta;
          self.aiText = self.cleanVoiceTags(self.currentAiFullText);
          self.statusText = '回复中...';
          self.subtitleScrollTop += 100;
        },
        onAudio(audioBase64, audioText, index) {
          const audioLen = (audioBase64 || '').length;
          const audioKB = Math.round(audioLen / 1024);
          self.addLog('info', '🔊 收到音频 #' + index + ' (' + audioKB + 'KB, ' + audioLen + '字符)');
          if (audioLen < 100) {
            self.addLog('warn', '音频数据异常短，可能为空');
          }
          // 收集 AI 音频片段
          self.audioSegments.push({
            type: 'ai',
            audio_b64: audioBase64,
            format: 'mp3',
            timestamp: Date.now(),
            msg_index: self.assistantMsgCount
          });
          // 后端已经做了 TTS，直接播放 base64 音频
          if (self.audioPlayer && self.isInCall) {
            self.addLog('info', '调用 playBase64Audio，播放器队列: ' + (self.audioPlayer.queue ? self.audioPlayer.queue.length : 0) + ' | isPlaying: ' + self.audioPlayer.isPlaying);
            self.playBase64Audio(audioBase64);
          } else {
            self.addLog('error', '❌ 无法播放: audioPlayer=' + !!self.audioPlayer + ' isInCall=' + self.isInCall);
          }
        },
        onDone(stats) {
          const statsStr = stats ? (' | 总耗时 ' + (stats.total_time || '?') + 's, ' + (stats.sentences || '?') + '句TTS') : '';
          self.addLog('info', '✅ AI 回复完成 (' + self.currentAiFullText.length + '字)' + statsStr);
          self.messages.push({ role: 'assistant', content: self.currentAiFullText });
          self.assistantMsgCount++;
          self.statusText = '';
          // 如果没有音频在播放，恢复录音
          if (!self.audioPlayer || !self.audioPlayer.isPlaying) {
            self.addLog('info', '无音频在播放，恢复录音');
            self.isAiSpeaking = false;
            self.statusText = '已连接';
            self.startRecording();
          } else {
            self.addLog('info', '音频播放中，等待播完后恢复录音');
          }
        },
        onError(message) {
          self.addLog('error', '❌ Chat 错误: ' + message);
          self.statusText = '⚠️ ' + message;
          self.isAiSpeaking = false;
          self.startRecording();
        },
        onTtsError(errorText) {
          self.addLog('error', '❌ TTS 错误: ' + errorText);
          self.statusText = '⚠️ TTS: ' + errorText;
        },
        onVisionLog(text) {
          self.addLog('info', '🎥 识图: ' + text);
          self.statusText = text;
        }
      });
    },

    // === 播放 base64 音频 ===
    playBase64Audio(base64) {
      if (!base64 || base64.length < 100) {
        this.addLog('warn', 'playBase64Audio: 音频数据为空或过短 (' + (base64 || '').length + ')');
        return;
      }
      this.addLog('info', 'playBase64Audio: 收到 ' + Math.round(base64.length / 1024) + 'KB 音频数据');

      // #ifdef APP-PLUS
      try {
        const self = this;
        const fileName = `tts_${Date.now()}_${Math.random().toString(36).slice(2,6)}.mp3`;
        const filePath = '_doc/' + fileName;

        // 使用 plus.io.FileWriter 的 writeAsBinary 替代 atob（APP 环境更可靠）
        plus.io.resolveLocalFileSystemURL('_doc/', (entry) => {
          entry.getFile(fileName, { create: true }, (fileEntry) => {
            fileEntry.createWriter((writer) => {
              writer.onwriteend = () => {
                const fileUrl = fileEntry.toURL();
                self.addLog('info', 'TTS 文件写入成功: ' + fileUrl);
                if (self.audioPlayer && self.isInCall) {
                  self.audioPlayer.enqueue(fileUrl);
                } else {
                  self.addLog('warn', '播放器不可用或不在通话中');
                }
              };
              writer.onerror = (e) => {
                self.addLog('error', 'TTS 文件写入失败: ' + JSON.stringify(e));
              };
              // 关键修复: 用 base64 直接写入，避免 atob 兼容性问题
              writer.seek(0);
              const arrayBuffer = self._base64ToArrayBuffer(base64);
              if (arrayBuffer) {
                writer.write(arrayBuffer);
              } else {
                self.addLog('error', 'base64 解码失败');
              }
            }, (e) => {
              self.addLog('error', 'createWriter 失败: ' + JSON.stringify(e));
            });
          }, (e) => {
            self.addLog('error', 'getFile 失败: ' + JSON.stringify(e));
          });
        }, (e) => {
          self.addLog('error', 'resolveLocalFileSystemURL 失败: ' + JSON.stringify(e));
        });
      } catch (e) {
        this.addLog('error', 'playBase64Audio APP 异常: ' + (e.message || e));
      }
      // #endif
      // #ifdef H5
      try {
        const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: 'audio/mpeg' });
        const url = URL.createObjectURL(blob);
        if (this.audioPlayer && this.isInCall) {
          this.audioPlayer.enqueue(url);
          this.addLog('info', 'H5 音频入队: ' + url.slice(0, 40));
        }
      } catch (e) {
        this.addLog('error', 'playBase64Audio H5 异常: ' + (e.message || e));
      }
      // #endif
    },

    // base64 → ArrayBuffer（兼容 APP 环境）
    _base64ToArrayBuffer(base64) {
      try {
        // 优先用 uni 内置方法
        if (typeof uni.base64ToArrayBuffer === 'function') {
          return uni.base64ToArrayBuffer(base64);
        }
        // 降级用 atob
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
      } catch (e) {
        this.addLog('error', 'base64ToArrayBuffer 失败: ' + (e.message || e));
        return null;
      }
    },

    // === 工具方法 ===
    cleanVoiceTags(text) {
      if (!text) return '';
      let c = text.replace(/\((laughs|chuckle|coughs|clear-throat|groans|breath|pant|inhale|exhale|gasps|sniffs|sighs|snorts|burps|lip-smacking|humming|hissing|emm|whistles|sneezes|crying|applause)\)/gi, '');
      c = c.replace(/<#[\d.]+#?>/g, '');
      c = c.replace(/<#[\d.#]*$/, '');
      return c.replace(/\s{2,}/g, ' ').trim();
    },

    // === 控制 ===
    toggleMute() {
      this.isMuted = !this.isMuted;
      if (this.isMuted) {
        if (this.recorder) this.recorder.stop();
        this.statusText = '已静音';
      } else if (this.isInCall && !this.isAiSpeaking) {
        this.startRecording();
      }
    },

    toggleVideo() {
      if (this.videoEnabled) {
        this.stopVideo();
      } else {
        this.startVideo();
      }
    },

    startVideo() {
      if (this.videoEnabled) return;
      this.addLog('info', '请求摄像头权限...');

      // #ifdef H5
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        this.addLog('error', '浏览器不支持摄像头');
        uni.showToast({ title: '浏览器不支持摄像头', icon: 'none' });
        return;
      }
      navigator.mediaDevices.getUserMedia({
        video: { facingMode: this.facingMode, width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false
      }).then(stream => {
        this.videoStream = stream;
        this.videoEnabled = true;
        set(KEYS.VIDEO_ENABLED, 'true');
        this.addLog('info', '✅ 摄像头已开启');
        // 连接到 video 元素
        this.$nextTick(() => {
          const videoEl = this.$refs.videoPreview;
          if (videoEl) {
            videoEl.srcObject = stream;
            videoEl.play().catch(() => {});
          }
        });
        this.startVideoCapture();
      }).catch(e => {
        this.addLog('error', '摄像头权限被拒绝: ' + (e.message || e));
        uni.showToast({ title: '摄像头权限被拒绝', icon: 'none' });
      });
      // #endif

      // #ifdef APP-PLUS
      // APP 环境：先申请相机权限，再显示 camera 组件
      const self = this;
      // 检查并申请相机权限
      function requestCameraPermission() {
        // Android 权限申请
        if (plus.os.name === 'Android') {
          plus.android.requestPermissions(
            ['android.permission.CAMERA'],
            function(e) {
              if (e.granted && e.granted.length > 0) {
                self.addLog('info', '✅ Android 相机权限已授予');
                self._initCameraComponent();
              } else {
                self.addLog('error', '❌ 相机权限被拒绝');
                uni.showToast({ title: '需要相机权限才能使用视频通话', icon: 'none' });
                self.videoEnabled = false;
              }
            },
            function(e) {
              self.addLog('error', '相机权限申请失败: ' + JSON.stringify(e));
              self.videoEnabled = false;
            }
          );
        } else {
          // iOS: camera 组件会自动弹权限，直接初始化
          self._initCameraComponent();
        }
      }
      this.videoEnabled = true;
      set(KEYS.VIDEO_ENABLED, 'true');
      requestCameraPermission();
      // #endif
    },

    stopVideo() {
      this.videoEnabled = false;
      set(KEYS.VIDEO_ENABLED, 'false');
      this.stopVideoCapture();

      // #ifdef H5
      if (this.videoStream) {
        this.videoStream.getTracks().forEach(t => t.stop());
        this.videoStream = null;
      }
      const videoEl = this.$refs.videoPreview;
      if (videoEl) {
        videoEl.srcObject = null;
      }
      // #endif

      // #ifdef APP-PLUS
      this.cameraContext = null;
      // #endif

      this.videoFullscreen = false;
      this.addLog('info', '📹 摄像头已关闭');
    },

    startVideoCapture() {
      this.stopVideoCapture();
      this.videoCaptureTimer = setInterval(() => {
        this.captureVideoFrame();
      }, 1500);
    },

    stopVideoCapture() {
      if (this.videoCaptureTimer) {
        clearInterval(this.videoCaptureTimer);
        this.videoCaptureTimer = null;
      }
    },

    captureVideoFrame() {
      // #ifdef H5
      const videoEl = this.$refs.videoPreview;
      if (!videoEl || !videoEl.srcObject || videoEl.videoWidth === 0) return;
      let canvas = this.$refs.videoCanvas;
      if (!canvas) return;
      const targetWidth = 512;
      const scale = targetWidth / videoEl.videoWidth;
      const targetHeight = Math.round(videoEl.videoHeight * scale);
      canvas.width = targetWidth;
      canvas.height = targetHeight;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(videoEl, 0, 0, targetWidth, targetHeight);
      const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
      this.latestVideoFrame = dataUrl.split(',')[1] || '';
      // #endif

      // #ifdef APP-PLUS
      if (!this.cameraContext) return;
      this.cameraContext.takePhoto({
        quality: 'low',
        success: (res) => {
          // 读取图片文件转 base64，压缩到 512px
          plus.io.resolveLocalFileSystemURL(res.tempImagePath, (entry) => {
            entry.file((file) => {
              const reader = new plus.io.FileReader();
              reader.onloadend = (e) => {
                const dataUrl = e.target.result;
                this.latestVideoFrame = dataUrl.split(',')[1] || '';
              };
              reader.readAsDataURL(file);
            });
          }, () => {});
        },
        fail: () => {}
      });
      // #endif
    },

    // APP-PLUS: 初始化 camera 组件（权限通过后调用）
    _initCameraComponent() {
      this.$nextTick(() => {
        this.cameraContext = uni.createCameraContext();
        this.addLog('info', '✅ 摄像头已开启 (APP)');
        this.startVideoCapture();
      });
    },

    switchCamera() {
      if (!this.videoEnabled) return;
      this.facingMode = (this.facingMode === 'user') ? 'environment' : 'user';
      this.addLog('info', '切换摄像头: ' + (this.facingMode === 'user' ? '前置' : '后置'));

      // #ifdef H5
      // 停掉当前流，重新获取
      if (this.videoStream) {
        this.videoStream.getTracks().forEach(t => t.stop());
        this.videoStream = null;
      }
      this.stopVideoCapture();
      navigator.mediaDevices.getUserMedia({
        video: { facingMode: this.facingMode, width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false
      }).then(stream => {
        this.videoStream = stream;
        this.$nextTick(() => {
          const videoEl = this.$refs.videoPreview;
          if (videoEl) {
            videoEl.srcObject = stream;
            videoEl.play().catch(() => {});
          }
        });
        this.startVideoCapture();
      }).catch(e => {
        this.addLog('error', '切换摄像头失败: ' + (e.message || e));
      });
      // #endif

      // #ifdef APP-PLUS
      // APP 的 <camera> 组件通过 :device-position 绑定自动切换，无需额外操作
      // #endif
    },

    toggleSpeaker() {
      this.isSpeaker = !this.isSpeaker;
    },

    // === 设置相关 ===
    async loadBuiltinModels() {
      try {
        const data = await getBuiltinModels();
        this.builtinModels = data.models || data || [];
        if (!this.sBuiltinModel && this.builtinModels.length) {
          this.sBuiltinModel = this.builtinModels[0];
        }
        const idx = this.builtinModels.indexOf(this.sBuiltinModel);
        this.builtinModelIdx = idx >= 0 ? idx : 0;
      } catch (e) {
        this.addLog('error', '加载内置模型失败: ' + (e.message || e));
      }
    },
    onBuiltinModelChange(e) {
      this.builtinModelIdx = e.detail.value;
      this.sBuiltinModel = this.builtinModels[e.detail.value];
    },
    async fetchLlmModels() {
      if (!this.sLlmUrl || !this.sLlmKey) {
        uni.showToast({ title: '请先填写 API 地址和 Key', icon: 'none' });
        return;
      }
      this.sLlmFetching = true;
      try {
        const data = await getModels(this.sLlmUrl, this.sLlmKey);
        this.sLlmModelList = data.models || data || [];
        if (this.sLlmModelList.length && !this.sLlmModel) {
          this.sLlmModel = this.sLlmModelList[0];
        }
      } catch (e) {
        uni.showToast({ title: '获取失败', icon: 'none' });
      } finally {
        this.sLlmFetching = false;
      }
    },
    saveAllSettings() {
      // 保存对话偏好
      set(KEYS.USER_ID, this.userId);
      set(KEYS.TOPIC, this.topic);
      set(KEYS.EXTRA_PROMPT, this.sExtraPrompt);
      set(KEYS.USER_INFO, this.sUserInfo);
      set(KEYS.MAX_HISTORY, String(this.maxHistory));
      set(KEYS.SHOW_SUBTITLE, String(this.showSubtitle));
      set(KEYS.API_RETRY_COUNT, String(this.sRetryCount));
      // 保存 LLM
      if (this.sUseBuiltinLlm) {
        setJSON(KEYS.CUSTOM_LLM, null);
        set(KEYS.BUILTIN_MODEL, this.sBuiltinModel);
      } else {
        setJSON(KEYS.CUSTOM_LLM, {
          base_url: this.sLlmUrl,
          api_key: this.sLlmKey,
          model: this.sLlmModel,
        });
      }
      // 保存 TTS
      if (this.sUseBuiltinTts) {
        setJSON(KEYS.CUSTOM_TTS, null);
      } else {
        setJSON(KEYS.CUSTOM_TTS, {
          api_key: this.sTtsKey,
          group_id: this.sTtsGroupId,
          voice_id: this.sTtsVoiceId,
          model: ['speech-2.8-hd', 'speech-2.8-turbo'][this.sTtsModelIdx] || 'speech-2.8-hd',
        });
      }
      // 保存识图模型
      if (this.sUseCustomVision && this.sVisionUrl && this.sVisionKey) {
        const visionCfg = {
          base_url: this.sVisionUrl,
          api_key: this.sVisionKey,
          model: this.sVisionModel || 'gpt-4o-mini',
        };
        setJSON(KEYS.CUSTOM_VISION, visionCfg);
        this.customVision = visionCfg;
      } else {
        setJSON(KEYS.CUSTOM_VISION, null);
        this.customVision = null;
      }
      // 保存过滤规则（去掉空规则）
      const validRules = this.sFilterRules.filter(r => r.pattern && r.pattern.trim());
      setJSON(KEYS.FILTER_RULES, validRules.length > 0 ? validRules : null);
      this.sFilterRules = validRules;
      this.addLog('info', '设置已保存');
      uni.showToast({ title: '已保存', icon: 'success' });
      this.showSettings = false;
    },
    // === 日志 ===
    addLog(level, msg) {
      const now = new Date();
      const time = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
      this.logLines.push({ level, msg, time });
      if (this.logLines.length > 200) this.logLines.splice(0, 50);
    },
    copyLog() {
      const text = this.logLines.map(l => `${l.time} [${l.level}] ${l.msg}`).join('\n');
      uni.setClipboardData({ data: text || '(空)' });
    },

    sendTextInput() {
      const text = this.textInput.trim();
      if (!text) return;
      if (!this.isInCall) {
        uni.showToast({ title: '请先拨号', icon: 'none' });
        return;
      }
      if (this.isAiSpeaking) {
        // 如果 AI 正在说话，先中断当前回复
        if (this.chatAbort) {
          this.chatAbort.abort();
          this.chatAbort = null;
        }
        if (this.audioPlayer) {
          this.audioPlayer.stop();
        }
        this.isAiSpeaking = false;
      }
      this.textInput = '';
      // 停止录音
      if (this.recorder) this.recorder.stop();
      this.userText = text;
      console.log('[call] sendTextInput:', text);
      this.sendToChat(text);
    },
  }
};
</script>

<style scoped>
.call-page {
  min-height: 100vh;
  width: 100%;
  max-width: 100vw;
  background: #000;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow-x: hidden;
  overflow-y: auto;
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

/* 顶部栏 */
.top-bar {
  display: flex;
  align-items: center;
  padding: 24rpx 32rpx;
  position: relative;
  z-index: 20;
}
.back-btn {
  display: flex;
  align-items: center;
  padding: 8rpx 0;
}
.back-icon {
  width: 40rpx;
  height: 40rpx;
}
.back-text {
  font-size: 32rpx;
  color: #0A84FF;
}
.spacer { flex: 1; }
.settings-btn {
  padding: 20rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 80rpx;
  min-height: 80rpx;
}
.settings-icon {
  width: 44rpx;
  height: 44rpx;
  opacity: 0.9;
}

/* 角色信息 */
.caller-info {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20rpx 0 20rpx;
  position: relative;
  z-index: 10;
}
.caller-name {
  font-size: 68rpx;
  font-weight: 300;
  color: #fff;
  letter-spacing: 2rpx;
}
.call-status {
  font-size: 26rpx;
  color: #8E8E93;
  margin-top: 8rpx;
}
.call-timer {
  font-size: 32rpx;
  font-weight: 400;
  color: #8E8E93;
  margin-top: 8rpx;
  letter-spacing: 2rpx;
  font-variant-numeric: tabular-nums;
}

/* 字幕区 */
.subtitle-area {
  flex: 1;
  padding: 24rpx 32rpx;
  max-height: 400rpx;
  position: relative;
  z-index: 10;
}
.subtitle-bubble-row {
  display: flex;
  margin-bottom: 16rpx;
}
.subtitle-bubble-row.right {
  justify-content: flex-end;
}
.subtitle-bubble-row.left {
  justify-content: flex-start;
}
.subtitle-bubble {
  max-width: 80%;
  padding: 16rpx 24rpx;
  border-radius: 20rpx;
}
.user-bubble {
  background: rgba(10, 132, 255, 0.25);
  border-bottom-right-radius: 6rpx;
}
.ai-bubble {
  background: rgba(255, 255, 255, 0.1);
  border-bottom-left-radius: 6rpx;
}
.subtitle-bubble-text {
  font-size: 28rpx;
  color: #8E8E93;
  line-height: 1.4;
}
.ai-bubble-text {
  font-size: 36rpx;
  color: #fff;
  font-weight: 500;
}

/* 文字输入 */
.text-input-area {
  display: flex;
  align-items: center;
  padding: 16rpx 32rpx;
  margin-top: auto;
  position: relative;
  z-index: 10;
  background: rgba(0,0,0,0.5);
  border-top: 1rpx solid rgba(255,255,255,0.1);
}
.text-input {
  flex: 1;
  height: 72rpx;
  background: rgba(255,255,255,0.1);
  border: 1rpx solid rgba(255,255,255,0.15);
  border-radius: 36rpx;
  padding: 0 32rpx;
  color: #fff;
  font-size: 28rpx;
}
.send-btn {
  width: 64rpx;
  height: 64rpx;
  border-radius: 50%;
  background: #0A84FF;
  color: #fff;
  font-size: 24rpx;
  font-weight: 600;
  margin-left: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.send-btn:active {
  transform: scale(0.9);
}

/* 背景光效 */
.bg-blur {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: radial-gradient(circle at 50% 15%, #2a2a30 0%, #000000 65%);
  z-index: 0;
  pointer-events: none;
}

/* 拨号按钮 */
.controls {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: auto;
  padding-bottom: calc(120rpx + env(safe-area-inset-bottom));
  position: relative;
  z-index: 10;
}
.dial-btn {
  width: 152rpx;
  height: 152rpx;
  border-radius: 50%;
  background: #34C759;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8rpx 32rpx rgba(52, 199, 89, 0.35);
}
.dial-btn:active {
  transform: scale(0.9);
  opacity: 0.85;
}
.dial-icon-img {
  width: 56rpx;
  height: 56rpx;
}
.dial-hint {
  font-size: 26rpx;
  color: #8E8E93;
  margin-top: 20rpx;
}

/* 控制栏 */
.control-bar {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 48rpx;
  padding: 40rpx 0;
  padding-bottom: calc(60rpx + env(safe-area-inset-bottom));
  background: linear-gradient(to top, rgba(0,0,0,0.8) 0%, transparent 100%);
  position: relative;
  z-index: 10;
}
.ctrl-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 120rpx;
}
.ctrl-btn {
  width: 108rpx;
  height: 108rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ctrl-btn:active {
  transform: scale(0.9);
}
.ctrl-inner {
  width: 108rpx;
  height: 108rpx;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
}
.ctrl-btn.active .ctrl-inner {
  background: #fff;
}
.ctrl-icon {
  width: 48rpx;
  height: 48rpx;
}
.ctrl-btn.active .ctrl-icon {
  /* 反色效果：active 时背景白色，图标需要黑色 — 通过 filter 实现 */
  filter: invert(1);
}
.ctrl-label {
  font-size: 22rpx;
  color: rgba(255, 255, 255, 0.85);
  margin-top: 12rpx;
  text-align: center;
}
.hangup-btn {
  width: 108rpx;
  height: 108rpx;
  border-radius: 50%;
  background: #FF3B30;
  display: flex;
  align-items: center;
  justify-content: center;
}
.hangup-btn:active {
  background: #D32F2F;
  transform: scale(0.9);
}
.hangup-icon {
  width: 52rpx;
  height: 52rpx;
  transform: rotate(135deg);
}

/* 设置弹窗 */
.settings-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.6);
  display: flex;
  align-items: flex-end;
  z-index: 999;
}
.settings-panel {
  background: #1C1C1E;
  border-radius: 28rpx 28rpx 0 0;
  width: 100%;
  max-height: 70vh;
  padding-bottom: env(safe-area-inset-bottom);
}
.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 32rpx 32rpx 16rpx;
  border-bottom: 1rpx solid #2C2C2E;
}
.settings-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #fff;
}
.settings-close {
  font-size: 36rpx;
  color: #8E8E93;
  padding: 16rpx;
}
.settings-body {
  padding: 16rpx 32rpx 32rpx;
  max-height: 55vh;
}
.setting-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx 0;
  border-bottom: 1rpx solid #2C2C2E;
}
.setting-item.column {
  flex-direction: column;
  align-items: flex-start;
}
.setting-label {
  font-size: 28rpx;
  color: #fff;
  margin-bottom: 8rpx;
}
.setting-input {
  width: 100%;
  height: 72rpx;
  background: #2C2C2E;
  border-radius: 16rpx;
  padding: 0 24rpx;
  color: #fff;
  font-size: 28rpx;
  margin-top: 8rpx;
}

/* 过滤规则 */
.filter-rule-item {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 16rpx;
}
.filter-rule-inputs {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}
.filter-input {
  height: 64rpx !important;
  font-size: 26rpx !important;
}
.filter-rule-del {
  font-size: 32rpx;
  color: #FF3B30;
  padding: 8rpx 16rpx;
  flex-shrink: 0;
}
.filter-rule-add {
  padding: 16rpx 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 视频预览 */
.video-container {
  position: absolute;
  right: 24rpx;
  width: 220rpx;
  height: 300rpx;
  border-radius: 24rpx;
  overflow: hidden;
  z-index: 50;
  background: #000;
  border: 2rpx solid rgba(255,255,255,0.2);
  box-shadow: 0 8rpx 32rpx rgba(0,0,0,0.5);
  transition: all 0.3s ease;
}
.video-container.fullscreen {
  top: 0;
  right: 0;
  width: 100%;
  height: 100%;
  border-radius: 0;
  border: none;
}
.video-preview {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.video-switch-btn {
  position: absolute;
  bottom: 12rpx;
  right: 12rpx;
  width: 56rpx;
  height: 56rpx;
  border-radius: 50%;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
}
.video-container.fullscreen .video-switch-btn {
  bottom: 32rpx;
  right: 32rpx;
  width: 72rpx;
  height: 72rpx;
}
.video-switch-icon {
  font-size: 28rpx;
}
.video-container.fullscreen .video-switch-icon {
  font-size: 36rpx;
}
</style>
