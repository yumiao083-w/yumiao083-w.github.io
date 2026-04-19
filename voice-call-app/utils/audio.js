// utils/audio.js — 录音和音频播放封装

// VAD 常量
const SILENCE_THRESHOLD = 15;   // 音量阈值（0-128 范围）
const SILENCE_DURATION = 1500;  // 连续静音多久后自动截断（ms）
const MIN_RECORD_TIME = 500;    // 最短录音时间（ms）
const VOICE_FRAMES_REQUIRED = 3; // 至少多少帧有声音才算有效录音
const MAX_RECORD_DURATION = 60000; // 最大录音时长（ms）

/**
 * 分析音频帧数据的音量
 * onFrameRecorded 返回的是编码后的 mp3 数据，不是 raw PCM
 * 我们通过分析字节分布来估算能量：
 * - 静音的 mp3 帧字节值集中在中间（0x00 附近或固定模式）
 * - 有声音的 mp3 帧字节值分布更广、变化更大
 */
function estimateFrameVolume(buffer) {
  if (!buffer || buffer.byteLength === 0) return 0;
  const bytes = new Uint8Array(buffer);
  const len = bytes.length;
  // 跳过前 4 字节（mp3 帧头），分析数据部分
  const start = Math.min(4, len);
  if (len - start < 10) return 0;
  
  // 计算字节值的标准差作为能量指标
  let sum = 0;
  let sumSq = 0;
  const count = len - start;
  for (let i = start; i < len; i++) {
    const v = bytes[i];
    sum += v;
    sumSq += v * v;
  }
  const mean = sum / count;
  const variance = (sumSq / count) - (mean * mean);
  // 将标准差映射到 0-128 范围，与 SILENCE_THRESHOLD 对比
  return Math.sqrt(Math.max(0, variance)) * 0.5;
}

/**
 * 录音管理器
 * 封装 uni.getRecorderManager，支持 VAD 静音检测
 */
export class Recorder {
  constructor(options = {}) {
    this.manager = uni.getRecorderManager();
    this.isRecording = false;
    this.onStop = options.onStop || (() => {});
    this.onError = options.onError || (() => {});
    this.onVolumeChange = options.onVolumeChange || (() => {});

    // VAD 状态
    this.hasVoiceActivity = false;
    this.voiceFrameCount = 0;
    this.silenceStart = null;
    this.recordStartTime = 0;
    this._maxDurationTimer = null;

    this.manager.onStop((res) => {
      this.isRecording = false;
      this._clearMaxDurationTimer();
      if (res.tempFilePath) {
        this.onStop(res);
      }
    });

    this.manager.onError((err) => {
      this.isRecording = false;
      this._clearMaxDurationTimer();
      this.onError(err);
    });

    // VAD: 分析每个音频帧的音量
    this.manager.onFrameRecorded((res) => {
      if (!this.isRecording) return;
      const { frameBuffer } = res;
      if (!frameBuffer) return;

      const volume = estimateFrameVolume(frameBuffer);
      this.onVolumeChange(volume);

      if (volume > SILENCE_THRESHOLD) {
        // 检测到声音
        this.silenceStart = null;
        this.voiceFrameCount++;
        if (this.voiceFrameCount >= VOICE_FRAMES_REQUIRED) {
          this.hasVoiceActivity = true;
        }
      } else {
        // 静音帧
        const now = Date.now();
        if (!this.silenceStart) {
          this.silenceStart = now;
        } else if (
          now - this.silenceStart > SILENCE_DURATION &&
          now - this.recordStartTime > MIN_RECORD_TIME
        ) {
          // 连续静音超过阈值，自动停止录音
          this.stop();
        }
      }
    });
  }

  start() {
    if (this.isRecording) return;
    this.isRecording = true;
    // 重置 VAD 状态
    this.hasVoiceActivity = false;
    this.voiceFrameCount = 0;
    this.silenceStart = null;
    this.recordStartTime = Date.now();

    this.manager.start({
      duration: MAX_RECORD_DURATION,
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 48000,
      format: 'mp3',
      frameSize: 5 // 每 5KB 回调一次
    });

    // 最大录音时长保护
    this._clearMaxDurationTimer();
    this._maxDurationTimer = setTimeout(() => {
      if (this.isRecording) {
        this.stop();
      }
    }, MAX_RECORD_DURATION);
  }

  stop() {
    if (!this.isRecording) return;
    this._clearMaxDurationTimer();
    this.manager.stop();
  }

  _clearMaxDurationTimer() {
    if (this._maxDurationTimer) {
      clearTimeout(this._maxDurationTimer);
      this._maxDurationTimer = null;
    }
  }
}

/**
 * 音频播放队列
 * 依次播放多段音频
 */
export class AudioPlayer {
  constructor(options = {}) {
    this.queue = [];
    this.isPlaying = false;
    this.onPlayEnd = options.onPlayEnd || (() => {});
    this.onAllEnd = options.onAllEnd || (() => {});
    this.onError = options.onError || (() => {});
    this.onLog = options.onLog || ((level, msg) => console.log(`[AudioPlayer] [${level}] ${msg}`));

    this._createAudio();
  }

  _createAudio() {
    if (this.audio) {
      try { this.audio.destroy(); } catch(e) {}
    }
    this.audio = uni.createInnerAudioContext();
    // #ifdef APP-PLUS
    // Android/iOS: 设置不遵循静音开关
    try { this.audio.obeyMuteSwitch = false; } catch(e) {}
    // #endif

    this.audio.onPlay(() => {
      this.onLog('info', '▶ 音频开始播放: ' + (this.audio.src || '').slice(0, 60));
    });

    this.audio.onEnded(() => {
      this.onLog('info', '⏹ 音频播放结束');
      this.isPlaying = false;
      this.onPlayEnd();
      this._playNext();
    });

    this.audio.onError((err) => {
      const errCode = err && err.errCode ? err.errCode : (err && err.errMsg ? err.errMsg : JSON.stringify(err));
      this.onLog('error', '❌ 音频播放错误: ' + errCode + ' | src: ' + (this.audio.src || '').slice(0, 60));
      this.isPlaying = false;
      this.onError(err);
      // 出错后重建播放器（避免错误状态污染）
      this._createAudio();
      this._playNext();
    });
  }

  enqueue(src) {
    this.queue.push(src);
    this.onLog('info', '📥 入队: ' + (src || '').slice(0, 60) + ' | 队列长度: ' + this.queue.length + ' | isPlaying: ' + this.isPlaying);
    if (!this.isPlaying) {
      this._playNext();
    }
  }

  _playNext() {
    if (this.queue.length === 0) {
      this.onLog('info', '📭 队列播放完毕');
      this.onAllEnd();
      return;
    }
    const src = this.queue.shift();
    this.isPlaying = true;
    this.onLog('info', '🎵 播放: ' + (src || '').slice(0, 60) + ' | 剩余: ' + this.queue.length);
    this.audio.src = src;
    this.audio.play();
  }

  stop() {
    this.onLog('info', '⏸ 停止播放 (队列 ' + this.queue.length + ' 项清空)');
    this.queue = [];
    this.isPlaying = false;
    try {
      this.audio.stop();
    } catch (e) {}
  }

  destroy() {
    this.stop();
    try { this.audio.destroy(); } catch(e) {}
  }
}
