<template>
  <view class="container">
    <view class="app-container">
      <view class="content">
        <!-- 系统公告 -->
        <view class="announce-banner" v-if="announcement" @tap="announcement=''">
          <text class="announce-text">{{ announcement }}</text>
          <text class="announce-close">×</text>
        </view>

        <text class="large-title">给{{ characterName }}打\n一通电话吧</text>
        <text class="subtitle">输入口令体验，或登录账号</text>

        <!-- 口令体验 -->
        <text class="section-title">口令体验</text>
        <view class="input-group">
          <input class="input-field" v-model="redeemInput" placeholder="输入口令" @confirm="doRedeem" />
        </view>
        <button class="btn-primary btn-green" :disabled="redeemLoading" @tap="doRedeem">
          {{ redeemLoading ? '验证中...' : '开始体验' }}
        </button>
        <text class="error-msg">{{ redeemError }}</text>
        <text class="hint">从小红书获取口令，免费体验</text>

        <!-- 分割线 -->
        <view class="divider">
          <view class="divider-line"></view>
          <text class="divider-text">或</text>
          <view class="divider-line"></view>
        </view>

        <!-- 账号登录 -->
        <text class="section-title">账号登录</text>
        <view class="input-group">
          <input class="input-field" v-model="nickname" placeholder="昵称" @confirm="focusPassword" />
        </view>
        <view class="input-group">
          <input class="input-field" v-model="password" placeholder="密码" password @confirm="doAuth" ref="pwInput" />
        </view>
        <button class="btn-primary" :disabled="authLoading" @tap="doAuth">
          {{ authLoading ? '登录中...' : '登录' }}
        </button>
        <text class="error-msg">{{ authError }}</text>
        <view class="auth-toggle">
          <text class="auth-link" @tap="toggleAuthMode">{{ registrationEnabled ? '没有账号？点击注册' : '注册已关闭' }}</text>
        </view>

        <!-- 底部 -->
        <view class="footer">
          <text class="footer-text">登录后不会过期 · 口令体验30分钟有效</text>
        </view>
      </view>
    </view>

    <!-- 反馈浮动按钮 -->
    <view class="fab" @tap="showFeedback=true">
      <text class="fab-icon">💬</text>
    </view>

    <!-- 反馈弹窗 -->
    <view class="modal-overlay" v-if="showFeedback" @tap.self="showFeedback=false">
      <view class="modal-content">
        <text class="modal-title">意见反馈</text>
        <textarea class="fb-textarea" v-model="fbText" placeholder="说说你的建议或遇到的问题..." />
        <input class="fb-input" v-model="fbContact" placeholder="联系方式（选填）" />
        <button class="fb-submit" @tap="doFeedback">提交</button>
        <text class="fb-msg">{{ fbMsg }}</text>
      </view>
    </view>
  </view>
</template>

<script>
import { redeemCode, login, register, getRegistrationStatus, getAnnouncement, submitFeedback } from '../../utils/api.js';
import { get, set, remove, KEYS } from '../../utils/storage.js';

export default {
  data() {
    return {
      characterName: '袁朗',
      redeemInput: '',
      redeemError: '',
      redeemLoading: false,
      nickname: '',
      password: '',
      authError: '',
      authLoading: false,
      registrationEnabled: true,
      announcement: '',
      showFeedback: false,
      fbText: '',
      fbContact: '',
      fbMsg: ''
    };
  },
  onLoad() {
    this.checkAutoLogin();
    this.loadAnnouncement();
    this.checkRegistration();
  },
  methods: {
    async checkAutoLogin() {
      const token = get(KEYS.TOKEN);
      if (token) {
        // 有 token，直接跳转
        uni.redirectTo({ url: '/pages/index/index?token=' + token });
      }
    },
    async loadAnnouncement() {
      try {
        const data = await getAnnouncement();
        if (data && data.text) this.announcement = data.text;
      } catch (e) {}
    },
    async checkRegistration() {
      try {
        const data = await getRegistrationStatus();
        this.registrationEnabled = data.enabled !== false;
      } catch (e) {}
    },
    focusPassword() {
      // uni-app 没有直接 focus ref 的方式，用户手动点击
    },
    async doRedeem() {
      const code = this.redeemInput.trim();
      this.redeemError = '';
      if (!code) {
        this.redeemError = '请输入口令';
        return;
      }
      this.redeemLoading = true;
      try {
        const result = await redeemCode(code);
        if (result.token) {
          set(KEYS.TOKEN, result.token);
          uni.redirectTo({ url: '/pages/index/index?token=' + result.token });
        } else {
          this.redeemError = result.error || '验证失败，请重试';
        }
      } catch (e) {
        this.redeemError = e?.data?.error || '网络错误，请重试';
      } finally {
        this.redeemLoading = false;
      }
    },
    async doAuth() {
      const nickname = this.nickname.trim();
      const password = this.password;
      this.authError = '';
      if (!nickname) { this.authError = '请输入昵称'; return; }
      if (!password) { this.authError = '请输入密码'; return; }

      this.authLoading = true;
      try {
        const result = await login(nickname, password);
        if (result.token) {
          set(KEYS.TOKEN, result.token);
          set(KEYS.NICKNAME, result.nickname);
          set(KEYS.API_KEY, result.api_key);
          set(KEYS.PW_SEED, password);
          uni.redirectTo({ url: '/pages/index/index?token=' + result.token });
        } else {
          this.authError = result.error || '登录失败';
        }
      } catch (e) {
        this.authError = e?.data?.error || '网络错误，请重试';
      } finally {
        this.authLoading = false;
      }
    },
    toggleAuthMode() {
      if (!this.registrationEnabled) {
        this.authError = '注册已关闭，请联系管理员';
        return;
      }
      uni.showToast({ title: '请前往网页版注册', icon: 'none' });
    },
    async doFeedback() {
      const text = this.fbText.trim();
      if (!text) { this.fbMsg = '请输入内容'; return; }
      try {
        await submitFeedback(text, this.fbContact.trim());
        this.fbMsg = '感谢反馈！';
        this.fbText = '';
        setTimeout(() => { this.showFeedback = false; this.fbMsg = ''; }, 1500);
      } catch (e) {
        this.fbMsg = '提交失败';
      }
    }
  }
};
</script>

<style scoped>
.container {
  min-height: 100vh;
  width: 100%;
  max-width: 100vw;
  overflow-x: hidden;
  background: #E5E5EA;
  margin: 0;
  padding: 0;
}
.app-container {
  background: #F2F2F7;
  width: 100%;
  min-height: 100vh;
  margin: 0;
  display: flex;
  flex-direction: column;
}
.content {
  flex: 1;
  padding: 0 40rpx;
  display: flex;
  flex-direction: column;
  margin-top: 160rpx;
}
.announce-banner {
  background: #E8F4FD;
  border-radius: 20rpx;
  padding: 24rpx 32rpx;
  margin-bottom: 32rpx;
  position: relative;
}
.announce-text { font-size: 28rpx; color: #1a1a1a; }
.announce-close { position: absolute; right: 20rpx; top: 16rpx; font-size: 36rpx; color: #8E8E93; }
.large-title {
  font-size: 68rpx;
  font-weight: 700;
  color: #000;
  line-height: 1.2;
  margin-bottom: 16rpx;
}
.subtitle {
  font-size: 30rpx;
  color: #8E8E93;
  margin-bottom: 64rpx;
}
.section-title {
  font-size: 26rpx;
  font-weight: 600;
  color: #8E8E93;
  text-transform: uppercase;
  letter-spacing: 1rpx;
  margin-bottom: 16rpx;
}
.input-group {
  background: #FFFFFF;
  border-radius: 20rpx;
  padding: 8rpx 32rpx;
  margin-bottom: 24rpx;
}
.input-field {
  width: 100%;
  height: 88rpx;
  border: none;
  background: transparent;
  font-size: 34rpx;
  color: #000;
}
.btn-primary {
  width: 100%;
  height: 100rpx;
  background: #000;
  color: #fff;
  border: none;
  border-radius: 28rpx;
  font-size: 34rpx;
  font-weight: 600;
  line-height: 100rpx;
}
.btn-green { background: #34C759; }
.btn-primary[disabled] { opacity: 0.5; }
.error-msg {
  color: #FF3B30;
  font-size: 26rpx;
  margin-top: 16rpx;
  text-align: center;
  min-height: 36rpx;
}
.hint {
  font-size: 26rpx;
  color: #8E8E93;
  margin-top: 16rpx;
  text-align: center;
}
.divider {
  display: flex;
  align-items: center;
  margin: 56rpx 0;
}
.divider-line { flex: 1; height: 1rpx; background: #C6C6C8; }
.divider-text { font-size: 26rpx; color: #8E8E93; margin: 0 24rpx; }
.auth-toggle { text-align: center; margin-top: 24rpx; }
.auth-link { color: #007AFF; font-size: 30rpx; }
.footer {
  text-align: center;
  margin-top: auto;
  margin-bottom: 80rpx;
  padding-top: 48rpx;
}
.footer-text { font-size: 26rpx; color: #8E8E93; }

/* 浮动按钮 */
.fab {
  position: fixed;
  bottom: 40rpx;
  right: 40rpx;
  background: #007AFF;
  border-radius: 50%;
  width: 96rpx;
  height: 96rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4rpx 24rpx rgba(0,0,0,0.2);
}
.fab-icon { font-size: 40rpx; }

/* 弹窗 */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
}
.modal-content {
  background: #fff;
  border-radius: 28rpx;
  padding: 40rpx;
  width: 85%;
  max-width: 720rpx;
}
.modal-title { font-size: 32rpx; font-weight: 600; margin-bottom: 24rpx; display: block; }
.fb-textarea {
  width: 100%;
  min-height: 160rpx;
  padding: 20rpx;
  border: 1rpx solid #E5E5EA;
  border-radius: 16rpx;
  font-size: 28rpx;
  box-sizing: border-box;
}
.fb-input {
  width: 100%;
  padding: 20rpx;
  border: 1rpx solid #E5E5EA;
  border-radius: 16rpx;
  font-size: 28rpx;
  margin-top: 16rpx;
  box-sizing: border-box;
}
.fb-submit {
  width: 100%;
  padding: 24rpx;
  background: #007AFF;
  color: #fff;
  border: none;
  border-radius: 20rpx;
  font-size: 32rpx;
  margin-top: 24rpx;
}
.fb-msg { font-size: 26rpx; color: #8E8E93; text-align: center; margin-top: 16rpx; display: block; }
</style>
