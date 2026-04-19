<template>
  <view class="page">
    <!-- 状态栏占位 -->
    <view class="status-bar" :style="{ height: statusBarHeight + 'px' }"></view>

    <!-- ========== Tab 1: 最近通话 ========== -->
    <scroll-view class="tab-view" scroll-y v-if="currentTab === 0">
      <view class="tab-header">
        <text class="tab-title">最近通话</text>
      </view>

      <!-- 加载中 -->
      <view class="placeholder-box" v-if="historyLoading">
        <text class="placeholder-text">加载中...</text>
      </view>

      <!-- 空状态 -->
      <view class="empty-state" v-else-if="!callHistory.length">
        <view class="empty-icon-circle"><text class="empty-icon-char">✆</text></view>
        <text class="empty-text">还没有通话记录</text>
        <text class="empty-hint">拨打一通电话开始吧</text>
      </view>

      <!-- 通话记录列表 -->
      <view class="call-list" v-else>
        <view
          class="call-item"
          v-for="(call, idx) in callHistory"
          :key="call.id || idx"
          @tap="onCallTap(call)"
        >
          <!-- 圆形头像（首字） -->
          <view class="call-avatar">
            <text class="avatar-text">{{ characterName.charAt(0) }}</text>
          </view>

          <!-- 信息区 -->
          <view class="call-info">
            <view class="call-row-top">
              <text class="call-name">{{ characterName }}</text>
              <text class="call-time">{{ formatTime(call.created_at) }}</text>
            </view>
            <view class="call-row-bottom">
              <text class="call-last-msg" :lines="1">{{ getLastMsg(call) }}</text>
              <text class="call-duration">{{ formatDuration(call.duration) }}</text>
            </view>
          </view>
        </view>
      </view>
    </scroll-view>

    <!-- ========== Tab 2: 拨号 ========== -->
    <view class="tab-view" v-if="currentTab === 1">
      <view class="dial-container">
        <text class="dial-role">{{ characterName }}</text>
        <text class="dial-hint">点击拨号开始通话</text>
        <view class="dial-btn" @tap="startCall">
          <image class="dial-icon-img" :src="icons.phoneCall" mode="aspectFit" />
        </view>
      </view>
    </view>

    <!-- ========== Tab 3: 我的 ========== -->
    <scroll-view class="tab-view" scroll-y v-if="currentTab === 2 && !mySubPage">
      <view class="tab-header">
        <text class="tab-title">我的</text>
      </view>

      <!-- 用户卡片 -->
      <view class="my-card user-card" @tap="openSubPage('profile')">
        <view class="user-card-left">
          <view class="user-avatar">
            <text class="avatar-text">{{ (nickname || '用').charAt(0) }}</text>
          </view>
          <view class="user-card-info">
            <text class="user-card-name">{{ nickname || '未登录' }}</text>
            <text class="user-card-type">{{ accountType }}</text>
          </view>
        </view>
        <text class="card-arrow">›</text>
      </view>

      <!-- 功能列表 -->
      <view class="my-card">
        <view class="my-item" @tap="openSubPage('memory')">
          <view class="my-item-icon-wrap"><view class="item-icon-circle bg-orange"><image class="item-icon-img" :src="icons.memory" mode="aspectFit" /></view></view>
          <text class="my-item-title">通话记忆</text>
          <text class="card-arrow">›</text>
        </view>
        <view class="my-item" @tap="openSubPage('api')">
          <view class="my-item-icon-wrap"><view class="item-icon-circle bg-green"><image class="item-icon-img" :src="icons.gear" mode="aspectFit" /></view></view>
          <text class="my-item-title">API 配置</text>
          <text class="card-arrow">›</text>
        </view>
        <view class="my-item" @tap="openSubPage('context')">
          <view class="my-item-icon-wrap"><view class="item-icon-circle bg-purple"><image class="item-icon-img" :src="icons.chat" mode="aspectFit" /></view></view>
          <text class="my-item-title">上下文设置</text>
          <text class="card-arrow">›</text>
        </view>
        <view class="my-item" @tap="openSubPage('callSettings')">
          <view class="my-item-icon-wrap"><view class="item-icon-circle bg-red"><image class="item-icon-img" :src="icons.screen" mode="aspectFit" /></view></view>
          <text class="my-item-title">通话页面设置</text>
          <text class="card-arrow">›</text>
        </view>
      </view>

      <!-- 余额 & 充值 -->
      <view class="my-card">
        <view class="my-item" @tap="openSubPage('balance')">
          <view class="my-item-icon-wrap"><view class="item-icon-circle bg-orange"><image class="item-icon-img" :src="icons.dollar" mode="aspectFit" /></view></view>
          <text class="my-item-title">余额与充值</text>
          <text class="my-item-value">{{ balanceText }}</text>
          <text class="card-arrow">›</text>
        </view>
      </view>

      <!-- 统计 & 版本 -->
      <view class="my-card">
        <view class="my-item">
          <view class="my-item-icon-wrap"><view class="item-icon-circle bg-red"><image class="item-icon-img" :src="icons.phone" mode="aspectFit" /></view></view>
          <text class="my-item-title">通话次数</text>
          <text class="my-item-value">{{ callHistory.length }} 次</text>
        </view>
        <view class="my-item">
          <view class="my-item-icon-wrap"><view class="item-icon-circle bg-orange"><image class="item-icon-img" :src="icons.clock" mode="aspectFit" /></view></view>
          <text class="my-item-title">总通话时长</text>
          <text class="my-item-value">{{ totalDurationText }}</text>
        </view>
        <view class="my-item last-item">
          <view class="my-item-icon-wrap"><view class="item-icon-circle bg-gray"><image class="item-icon-img" :src="icons.gear" mode="aspectFit" /></view></view>
          <text class="my-item-title">版本</text>
          <text class="my-item-value">v1.0.0</text>
        </view>
      </view>

      <!-- 退出登录 -->
      <view class="logout-area">
        <text class="logout-btn" @tap="confirmLogout">退出登录</text>
      </view>

      <!-- 底部间距 -->
      <view style="height: 40rpx;"></view>
    </scroll-view>

    <!-- ========== Tab 3 子页面覆盖层 ========== -->
    <view class="sub-page" v-if="currentTab === 2 && mySubPage">
      <!-- 子页面导航栏 -->
      <view class="sub-nav" :style="{ paddingTop: statusBarHeight + 'px' }">
        <text class="sub-back" @tap="mySubPage = null">‹ 返回</text>
        <text class="sub-nav-title">{{ subPageTitle }}</text>
        <view class="sub-nav-right"></view>
      </view>

      <!-- 子页面内容 -->
      <scroll-view class="sub-content" scroll-y>

        <!-- ---- 余额与充值 ---- -->
        <view v-if="mySubPage === 'balance'">
          <view class="my-card balance-card">
            <text class="balance-label">当前余额</text>
            <text class="balance-amount">{{ balanceText }}</text>
          </view>

          <view class="my-card" style="padding: 32rpx;">
            <text class="sub-section-title">充值码</text>
            <view class="sub-input-group">
              <input class="sub-input" v-model="redeemCode" placeholder="输入充值码" />
            </view>
            <view class="sub-btn" :class="{ disabled: redeemLoading }" @tap="doRedeemCard">
              <text class="sub-btn-text">{{ redeemLoading ? '充值中...' : '充值' }}</text>
            </view>
            <text class="sub-hint" v-if="redeemMsg">{{ redeemMsg }}</text>
          </view>
        </view>

        <!-- ---- 个人信息 ---- -->
        <view v-else-if="mySubPage === 'profile'">
          <view class="my-card" style="padding: 0;">
            <view class="my-item">
              <text class="my-item-title">昵称</text>
              <text class="my-item-value">{{ nickname || '未设置' }}</text>
            </view>
            <view class="my-item">
              <text class="my-item-title">账号类型</text>
              <text class="my-item-value">{{ accountType }}</text>
            </view>
            <view class="my-item last-item">
              <text class="my-item-title">Token</text>
              <text class="my-item-value token-text">{{ tokenMasked }}</text>
            </view>
          </view>

          <view class="my-card" style="padding: 32rpx;">
            <text class="sub-section-title">称呼</text>
            <text class="sub-desc">AI 怎么称呼你</text>
            <view class="sub-input-group">
              <input class="sub-input" v-model="ctxUserId" placeholder="例如：小明" />
            </view>
            <text class="sub-section-title">关于你</text>
            <text class="sub-desc">让 AI 更了解你（兴趣、性格等）</text>
            <view class="sub-textarea-group">
              <textarea class="sub-textarea" v-model="ctxUserInfo" placeholder="例如：我喜欢看电影，性格比较内向" />
            </view>
            <text class="sub-section-title">话题</text>
            <text class="sub-desc">设定本次通话的话题方向</text>
            <view class="sub-input-group">
              <input class="sub-input" v-model="ctxTopic" placeholder="例如：聊聊最近的电影" />
            </view>
          </view>

          <view class="sub-btn" @tap="saveProfileSettings">
            <text class="sub-btn-text">保存</text>
          </view>
        </view>

        <!-- ---- 通话记忆 ---- -->
        <view v-else-if="mySubPage === 'memory'">
          <!-- 自动记忆开关 -->
          <view class="my-card" style="padding: 0;">
            <view class="my-item last-item">
              <text class="my-item-title">通话后自动生成记忆</text>
              <switch :checked="memAutoEnabled" @change="toggleAutoMemory($event.detail.value)" color="#0A84FF" />
            </view>
          </view>

          <!-- 加载中 -->
          <view class="placeholder-box" v-if="memLoading" style="margin-top: 24rpx;">
            <text class="placeholder-text">加载中...</text>
          </view>

          <!-- 空状态 -->
          <view class="empty-state" v-else-if="!memorySummaries.length" style="padding-top: 120rpx;">
            <view class="empty-icon-circle"><text class="empty-icon-char">M</text></view>
            <text class="empty-text">还没有记忆</text>
            <text class="empty-hint">通话结束后会自动生成记忆总结</text>
            <text class="empty-hint" v-if="memErrorMsg" style="color: #FF6B6B; margin-top: 16rpx;">{{ memErrorMsg }}</text>
          </view>

          <!-- 记忆列表 -->
          <view v-else class="mem-list">
            <view
              class="my-card mem-card"
              v-for="(mem, idx) in memorySummaries"
              :key="mem.id || idx"
            >
              <!-- 查看/编辑模式 -->
              <view v-if="editingMemId !== mem.id" style="padding: 28rpx 32rpx;">
                <text class="mem-text">{{ mem.text }}</text>
                <view class="mem-footer">
                  <text class="mem-time">{{ formatTime(mem.created_at) }}</text>
                  <view class="mem-actions">
                    <text class="mem-action-btn" @tap="startEditMem(mem)">编辑</text>
                    <text class="mem-action-btn mem-delete" @tap="confirmDeleteMem(mem)">删除</text>
                  </view>
                </view>
              </view>

              <!-- 编辑模式 -->
              <view v-else style="padding: 28rpx 32rpx;">
                <view class="sub-textarea-group" style="margin-top: 0;">
                  <textarea class="sub-textarea" v-model="editingMemText" />
                </view>
                <view class="mem-edit-actions">
                  <view class="mem-edit-btn cancel" @tap="editingMemId = null">
                    <text class="mem-edit-btn-text cancel-text">取消</text>
                  </view>
                  <view class="mem-edit-btn save" @tap="saveEditMem(mem)">
                    <text class="mem-edit-btn-text">保存</text>
                  </view>
                </view>
              </view>
            </view>
          </view>
        </view>

        <!-- ---- API 配置 ---- -->
        <view v-else-if="mySubPage === 'api'">
          <!-- LLM 配置 -->
          <view class="my-card" style="padding: 32rpx;">
            <text class="sub-section-title">LLM（对话模型）</text>

            <!-- 内置/自定义切换 -->
            <view class="toggle-row">
              <view class="toggle-btn" :class="{ active: !apiLlmCustom }" @tap="apiLlmCustom = false">
                <text class="toggle-text">内置</text>
              </view>
              <view class="toggle-btn" :class="{ active: apiLlmCustom }" @tap="apiLlmCustom = true">
                <text class="toggle-text">自定义</text>
              </view>
            </view>

            <!-- 内置模式 -->
            <view v-if="!apiLlmCustom">
              <text class="sub-desc" style="margin-top: 16rpx;">选择内置模型</text>
              <scroll-view class="model-list" scroll-y v-if="builtinModels.length">
                <view
                  class="model-item"
                  v-for="(m, idx) in builtinModels"
                  :key="idx"
                  :class="{ selected: apiBuiltinModel === m }"
                  @tap="apiBuiltinModel = m"
                >
                  <text class="model-name">{{ m }}</text>
                  <text class="model-check" v-if="apiBuiltinModel === m">✓</text>
                </view>
              </scroll-view>
              <view v-else class="placeholder-box" style="margin-top: 8rpx;">
                <text class="placeholder-text">{{ builtinLoading ? '加载中...' : '无可用模型' }}</text>
              </view>
            </view>

            <!-- 自定义模式 -->
            <view v-else>
              <text class="sub-desc" style="margin-top: 16rpx;">API 地址</text>
              <view class="sub-input-group">
                <input class="sub-input" v-model="apiLlmUrl" placeholder="https://api.example.com/v1" />
              </view>
              <text class="sub-desc">API Key</text>
              <view class="sub-input-group">
                <input class="sub-input" v-model="apiLlmKey" placeholder="sk-..." password />
              </view>
              <text class="sub-desc">模型名称</text>
              <view class="sub-input-group" v-if="!customLlmModels.length">
                <input class="sub-input" v-model="apiLlmModel" placeholder="gpt-4o" />
              </view>
              <view v-else>
                <scroll-view class="model-list" scroll-y>
                  <view
                    class="model-item"
                    v-for="(m, idx) in customLlmModels"
                    :key="idx"
                    :class="{ selected: apiLlmModel === m }"
                    @tap="apiLlmModel = m"
                  >
                    <text class="model-name">{{ m }}</text>
                    <text class="model-check" v-if="apiLlmModel === m">✓</text>
                  </view>
                </scroll-view>
              </view>
              <view class="sub-btn secondary" style="margin-top: 16rpx;" @tap="fetchCustomLlmModels">
                <text class="sub-btn-text">{{ customLlmLoading ? '获取中...' : '获取模型列表' }}</text>
              </view>
            </view>
          </view>

          <!-- TTS 配置 -->
          <view class="my-card" style="padding: 32rpx;">
            <text class="sub-section-title">TTS（语音合成）</text>

            <view class="toggle-row">
              <view class="toggle-btn" :class="{ active: !apiTtsCustom }" @tap="apiTtsCustom = false">
                <text class="toggle-text">内置</text>
              </view>
              <view class="toggle-btn" :class="{ active: apiTtsCustom }" @tap="apiTtsCustom = true">
                <text class="toggle-text">自定义</text>
              </view>
            </view>

            <!-- 内置 TTS -->
            <view v-if="!apiTtsCustom">
              <text class="sub-desc" style="margin-top: 16rpx;">使用服务器默认 TTS 引擎</text>
            </view>

            <!-- 自定义 TTS -->
            <view v-else>
              <text class="sub-desc" style="margin-top: 16rpx;">TTS API 地址</text>
              <view class="sub-input-group">
                <input class="sub-input" v-model="apiTtsUrl" placeholder="https://api.minimax.chat/v1/t2a_v2" />
              </view>
              <text class="sub-desc">TTS API Key</text>
              <view class="sub-input-group">
                <input class="sub-input" v-model="apiTtsKey" placeholder="API Key" password />
              </view>
              <text class="sub-desc">Voice ID</text>
              <view class="sub-input-group">
                <input class="sub-input" v-model="apiTtsVoice" placeholder="male-qn-qingse" />
              </view>
              <text class="sub-desc">TTS 模型</text>
              <view class="sub-input-group">
                <input class="sub-input" v-model="apiTtsModel" placeholder="speech-02-hd" />
              </view>
            </view>
          </view>

          <!-- 保存按钮 -->
          <view class="sub-btn" style="margin-top: 8rpx;" @tap="saveApiConfig">
            <text class="sub-btn-text">保存配置</text>
          </view>
        </view>

        <!-- ---- 上下文设置 ---- -->
        <view v-else-if="mySubPage === 'context'">
          <view class="my-card" style="padding: 32rpx;">
            <text class="sub-section-title">最大历史轮数</text>
            <text class="sub-desc">对话时携带的历史消息数量，越多越消耗 token</text>
            <view class="stepper-row">
              <view class="stepper-btn" @tap="ctxMaxHistory = Math.max(0, ctxMaxHistory - 1)">
                <text class="stepper-text">−</text>
              </view>
              <text class="stepper-value">{{ ctxMaxHistory }}</text>
              <view class="stepper-btn" @tap="ctxMaxHistory = Math.min(50, ctxMaxHistory + 1)">
                <text class="stepper-text">+</text>
              </view>
            </view>
          </view>

          <view class="my-card" style="padding: 32rpx;">
            <text class="sub-section-title">自定义提示词</text>
            <text class="sub-desc">追加到系统提示词末尾，用于调整角色行为</text>
            <view class="sub-textarea-group">
              <textarea class="sub-textarea" v-model="ctxExtraPrompt" placeholder="例如：说话更温柔一些" />
            </view>
          </view>

          <view class="sub-btn" @tap="saveContextSettings">
            <text class="sub-btn-text">保存</text>
          </view>
        </view>

        <!-- ---- 通话页面设置 ---- -->
        <view v-else-if="mySubPage === 'callSettings'">
          <view class="my-card" style="padding: 0;">
            <view class="my-item">
              <text class="my-item-title">显示字幕</text>
              <switch :checked="csShowSubtitle" @change="csShowSubtitle = $event.detail.value" color="#0A84FF" />
            </view>
            <view class="my-item">
              <text class="my-item-title">视频通话（预留）</text>
              <switch :checked="csVideoEnabled" @change="csVideoEnabled = $event.detail.value" color="#0A84FF" />
            </view>
            <view class="my-item last-item">
              <text class="my-item-title">API 重试次数</text>
              <view class="stepper-row compact">
                <view class="stepper-btn sm" @tap="csRetryCount = Math.max(0, csRetryCount - 1)">
                  <text class="stepper-text">−</text>
                </view>
                <text class="stepper-value sm">{{ csRetryCount }}</text>
                <view class="stepper-btn sm" @tap="csRetryCount = Math.min(5, csRetryCount + 1)">
                  <text class="stepper-text">+</text>
                </view>
              </view>
            </view>
          </view>

          <view class="sub-btn" style="margin-top: 32rpx;" @tap="saveCallPageSettings">
            <text class="sub-btn-text">保存</text>
          </view>
        </view>

        <!-- ---- 其他子页面占位 ---- -->
        <view v-else>
          <view class="placeholder-box">
            <text class="placeholder-text">{{ subPageTitle }}（待实现）</text>
          </view>
        </view>

      </scroll-view>
    </view>

    <!-- ========== 通话详情弹窗 ========== -->
    <view class="modal-overlay" v-if="detailCall" @tap.self="stopDetailAudio(); detailCall = null">
      <view class="detail-modal">
        <!-- 头部 -->
        <view class="detail-header">
          <view class="detail-avatar">
            <text class="avatar-text">{{ characterName.charAt(0) }}</text>
          </view>
          <view class="detail-meta">
            <text class="detail-name">{{ characterName }}</text>
            <text class="detail-time">{{ formatTime(detailCall.created_at) }} · {{ formatDuration(detailCall.duration) }}</text>
          </view>
          <text class="detail-close" @tap="stopDetailAudio(); detailCall = null">✕</text>
        </view>

        <!-- 消息气泡回放 -->
        <scroll-view class="detail-messages" scroll-y>
          <!-- 查看模式 -->
          <template v-if="!detailEditing">
            <view
              v-for="(msg, idx) in (detailCall.messages || [])"
              :key="idx"
              :class="['bubble-row', msg.role === 'user' ? 'bubble-right' : 'bubble-left']"
            >
              <view :class="['bubble', msg.role === 'user' ? 'bubble-user' : 'bubble-ai']">
                <text class="bubble-text">{{ msg.content }}</text>
              </view>
              <view
                v-if="msg.role === 'assistant' && hasAudio(idx)"
                class="bubble-play-btn"
                :class="{ playing: detailPlayingIdx === idx }"
                @tap="playDetailAudio(idx)"
              >
                <text class="bubble-play-icon">{{ detailPlayingIdx === idx ? '⏸' : '▶' }}</text>
              </view>
            </view>
          </template>
          <!-- 编辑模式 -->
          <template v-else>
            <view
              v-for="(msg, idx) in detailEditMessages"
              :key="idx"
              :class="['bubble-row', msg.role === 'user' ? 'bubble-right' : 'bubble-left']"
            >
              <view :class="['bubble', msg.role === 'user' ? 'bubble-user' : 'bubble-ai', 'bubble-editing']">
                <textarea
                  class="bubble-edit-textarea"
                  v-model="detailEditMessages[idx].content"
                  :auto-height="true"
                />
              </view>
            </view>
          </template>
          <view v-if="!detailCall.messages || !detailCall.messages.length" class="detail-empty">
            <text class="placeholder-text">无消息记录</text>
          </view>
        </scroll-view>

        <!-- 记忆总结 -->
        <view class="detail-memory">
          <view class="detail-memory-header">
            <text class="memory-label">📝 记忆总结</text>
            <view
              class="memory-gen-btn"
              :class="{ disabled: detailMemGenerating }"
              @tap="doGenerateMemory"
            >
              <text class="memory-gen-text">{{ detailMemGenerating ? '生成中...' : (detailCall.memory ? '重新生成' : '生成记忆') }}</text>
            </view>
          </view>
          <text class="memory-text" v-if="detailCall.memory">{{ detailCall.memory }}</text>
          <text class="memory-text memory-empty" v-else>暂无记忆</text>
        </view>

        <!-- 操作按钮 -->
        <view class="detail-actions">
          <template v-if="!detailEditing">
            <view class="detail-actions-row">
              <view class="action-btn action-edit" @tap="startDetailEdit">
                <text class="action-text action-text-blue">编辑</text>
              </view>
              <view class="action-btn action-delete" @tap="confirmDelete(detailCall)">
                <text class="action-text">删除记录</text>
              </view>
            </view>
          </template>
          <template v-else>
            <view class="detail-actions-row">
              <view class="action-btn action-cancel" @tap="cancelDetailEdit">
                <text class="action-text action-text-gray">取消</text>
              </view>
              <view class="action-btn action-save" @tap="saveDetailEdit">
                <text class="action-text action-text-blue">保存</text>
              </view>
            </view>
          </template>
        </view>
      </view>
    </view>

    <!-- ========== 底部 Tab 栏 ========== -->
    <view class="tab-bar">
      <view class="tab-item" :class="{ active: currentTab === 0 }" @tap="currentTab = 0">
        <image class="tab-icon-img" :src="currentTab === 0 ? icons.tabRecentsActive : icons.tabRecents" mode="aspectFit" />
        <text class="tab-label">最近</text>
      </view>
      <view class="tab-item" :class="{ active: currentTab === 1 }" @tap="currentTab = 1">
        <image class="tab-icon-img" :src="currentTab === 1 ? icons.tabDialActive : icons.tabDial" mode="aspectFit" />
        <text class="tab-label">拨号</text>
      </view>
      <view class="tab-item" :class="{ active: currentTab === 2 }" @tap="currentTab = 2">
        <image class="tab-icon-img" :src="currentTab === 2 ? icons.tabProfileActive : icons.tabProfile" mode="aspectFit" />
        <text class="tab-label">我的</text>
      </view>
    </view>
  </view>
</template>

<script>
import { getCallHistory, deleteCallHistory, getBalance, redeemCard, getMemorySummaries, deleteMemory, updateMemory, setAutoMemory, getBuiltinModels, getModels, getCallDetail, updateCallMessages, generateCallMemory, loadCloudSettings, saveCloudSettings } from '../../utils/api.js';
import { get, set, getJSON, setJSON, remove, KEYS } from '../../utils/storage.js';

export default {
  data() {
    const svgUri = (path, size=24, color='%23fff') => `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 ${size} ${size}' fill='${color}'%3E${path}%3C/svg%3E`;
    const svgUriGray = (path, size=24) => svgUri(path, size, '%238E8E93');
    const svgUriBlue = (path, size=24) => svgUri(path, size, '%230A84FF');
    return {
      icons: {
        // 拨号电话
        phoneCall: svgUri("%3Cpath d='M20.01 15.38c-1.23 0-2.42-.2-3.53-.56-.35-.12-.74-.03-1.01.24l-1.57 1.97c-2.83-1.35-5.48-3.9-6.89-6.83l1.95-1.66c.27-.28.35-.67.24-1.02-.37-1.11-.56-2.3-.56-3.53 0-.54-.45-.99-.99-.99H4.19C3.65 3 3 3.24 3 3.99 3 13.28 10.73 21 20.01 21c.71 0 .99-.63.99-1.18v-3.45c0-.54-.45-.99-.99-.99z'/%3E"),
        // Tab 图标
        tabRecents: svgUriGray("%3Cpath d='M13 3a9 9 0 00-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0013 21a9 9 0 000-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z'/%3E"),
        tabRecentsActive: svgUriBlue("%3Cpath d='M13 3a9 9 0 00-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0013 21a9 9 0 000-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z'/%3E"),
        tabDial: svgUriGray("%3Cpath d='M20.01 15.38c-1.23 0-2.42-.2-3.53-.56-.35-.12-.74-.03-1.01.24l-1.57 1.97c-2.83-1.35-5.48-3.9-6.89-6.83l1.95-1.66c.27-.28.35-.67.24-1.02-.37-1.11-.56-2.3-.56-3.53 0-.54-.45-.99-.99-.99H4.19C3.65 3 3 3.24 3 3.99 3 13.28 10.73 21 20.01 21c.71 0 .99-.63.99-1.18v-3.45c0-.54-.45-.99-.99-.99z'/%3E"),
        tabDialActive: svgUriBlue("%3Cpath d='M20.01 15.38c-1.23 0-2.42-.2-3.53-.56-.35-.12-.74-.03-1.01.24l-1.57 1.97c-2.83-1.35-5.48-3.9-6.89-6.83l1.95-1.66c.27-.28.35-.67.24-1.02-.37-1.11-.56-2.3-.56-3.53 0-.54-.45-.99-.99-.99H4.19C3.65 3 3 3.24 3 3.99 3 13.28 10.73 21 20.01 21c.71 0 .99-.63.99-1.18v-3.45c0-.54-.45-.99-.99-.99z'/%3E"),
        tabProfile: svgUriGray("%3Cpath d='M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z'/%3E"),
        tabProfileActive: svgUriBlue("%3Cpath d='M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z'/%3E"),
        // 设置项图标
        person: svgUri("%3Cpath d='M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z'/%3E"),
        memory: svgUri("%3Cpath d='M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z'/%3E"),
        gear: svgUri("%3Cpath d='M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.49.49 0 00-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.09-.49 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z'/%3E"),
        chat: svgUri("%3Cpath d='M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z'/%3E"),
        screen: svgUri("%3Cpath d='M21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H3V5h18v14z'/%3E"),
        dollar: svgUri("%3Cpath d='M11.8 10.9c-2.27-.59-3-1.2-3-2.15 0-1.09 1.01-1.85 2.7-1.85 1.78 0 2.44.85 2.5 2.1h2.21c-.07-1.72-1.12-3.3-3.21-3.81V3h-3v2.16c-1.94.42-3.5 1.68-3.5 3.61 0 2.31 1.91 3.46 4.7 4.13 2.5.6 3 1.48 3 2.41 0 .69-.49 1.79-2.7 1.79-2.06 0-2.87-.92-2.98-2.1h-2.2c.12 2.19 1.76 3.42 3.68 3.83V21h3v-2.15c1.95-.37 3.5-1.5 3.5-3.55 0-2.84-2.43-3.81-4.7-4.4z'/%3E"),
        phone: svgUri("%3Cpath d='M20.01 15.38c-1.23 0-2.42-.2-3.53-.56-.35-.12-.74-.03-1.01.24l-1.57 1.97c-2.83-1.35-5.48-3.9-6.89-6.83l1.95-1.66c.27-.28.35-.67.24-1.02-.37-1.11-.56-2.3-.56-3.53 0-.54-.45-.99-.99-.99H4.19C3.65 3 3 3.24 3 3.99 3 13.28 10.73 21 20.01 21c.71 0 .99-.63.99-1.18v-3.45c0-.54-.45-.99-.99-.99z'/%3E"),
        clock: svgUri("%3Cpath d='M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z'/%3E"),
      },
      currentTab: 1,
      statusBarHeight: 44,
      characterName: '袁朗',
      token: '',
      tabs: [
        { label: '最近' },
        { label: '拨号' },
        { label: '我的' },
      ],
      // Tab 1 数据
      callHistory: [],
      historyLoading: false,
      detailCall: null,
      // 通话详情编辑模式
      detailEditing: false,
      detailEditMessages: [],
      // 通话详情记忆生成
      detailMemGenerating: false,
      // 通话详情音频回放
      detailAudioMap: {},       // assistantIndex → [audioPath, ...]
      detailPlayingIdx: -1,     // 当前正在播放的 assistant 消息序号
      detailAudioPlayer: null,  // InnerAudioContext
      detailAudioQueue: [],     // 当前播放队列
      // 通话详情上下文 & 记忆
      detailContext: [],        // 通话时的上下文历史
      detailMemory: '',         // 通话记忆
      // Tab 3 数据
      nickname: '',
      accountType: '账号',
      mySubPage: null,
      balanceText: '--',
      redeemCode: '',
      redeemLoading: false,
      redeemMsg: '',
      // 上下文设置
      ctxMaxHistory: 10,
      ctxExtraPrompt: '',
      ctxUserId: '',
      ctxUserInfo: '',
      ctxTopic: '',
      // API 配置
      apiLlmCustom: false,
      apiBuiltinModel: '',
      builtinModels: [],
      builtinLoading: false,
      apiLlmUrl: '',
      apiLlmKey: '',
      apiLlmModel: '',
      customLlmModels: [],
      customLlmLoading: false,
      apiTtsCustom: false,
      apiTtsUrl: '',
      apiTtsKey: '',
      apiTtsVoice: '',
      apiTtsModel: '',
      // 通话记忆
      memorySummaries: [],
      memLoading: false,
      memAutoEnabled: true,
      memErrorMsg: '',
      editingMemId: null,
      editingMemText: '',
      // 通话页面设置
      csShowSubtitle: true,
      csVideoEnabled: false,
      csRetryCount: 2,
    };
  },
  onLoad(options) {
    this.token = options.token || get(KEYS.TOKEN) || '';
    this.nickname = get(KEYS.NICKNAME) || '';
    this.accountType = get(KEYS.API_KEY) ? '注册账号' : '体验用户';
    // 加载上下文设置
    this.ctxMaxHistory = parseInt(get(KEYS.MAX_HISTORY)) || 10;
    this.ctxExtraPrompt = get(KEYS.EXTRA_PROMPT) || '';
    this.ctxUserId = get(KEYS.USER_ID) || '';
    this.ctxUserInfo = get(KEYS.USER_INFO) || '';
    this.ctxTopic = get(KEYS.TOPIC) || '';
    // 加载 API 配置
    const savedLlm = getJSON(KEYS.CUSTOM_LLM);
    if (savedLlm && savedLlm.base_url) {
      this.apiLlmCustom = true;
      this.apiLlmUrl = savedLlm.base_url || '';
      this.apiLlmKey = savedLlm.api_key || '';
      this.apiLlmModel = savedLlm.model || '';
    }
    this.apiBuiltinModel = get(KEYS.BUILTIN_MODEL) || '';
    const savedTts = getJSON(KEYS.CUSTOM_TTS);
    if (savedTts && savedTts.base_url) {
      this.apiTtsCustom = true;
      this.apiTtsUrl = savedTts.base_url || '';
      this.apiTtsKey = savedTts.api_key || '';
      this.apiTtsVoice = savedTts.voice_id || '';
      this.apiTtsModel = savedTts.model || '';
    }
    // 加载记忆设置
    this.memAutoEnabled = get(KEYS.AUTO_MEMORY) !== 'false';
    // 加载通话页面设置
    this.csShowSubtitle = get(KEYS.SHOW_SUBTITLE) !== 'false';
    this.csVideoEnabled = get(KEYS.VIDEO_ENABLED) === 'true';
    this.csRetryCount = parseInt(get(KEYS.API_RETRY_COUNT)) || 2;
    // 获取状态栏高度
    try {
      const sysInfo = uni.getSystemInfoSync();
      this.statusBarHeight = sysInfo.statusBarHeight || 44;
    } catch (e) {}
    // 注册账号用户：从云端加载设置并合并
    if (this.token && get(KEYS.API_KEY)) {
      this.syncFromCloud();
    }
  },
  onShow() {
    // 每次显示页面时刷新通话记录
    if (this.token) {
      this.loadHistory();
    }
  },
  computed: {
    subPageTitle() {
      const map = {
        profile: '个人信息',
        memory: '通话记忆',
        api: 'API 配置',
        context: '上下文设置',
        callSettings: '通话页面设置',
        balance: '余额与充值',
      };
      return map[this.mySubPage] || '';
    },
    totalDurationText() {
      const total = this.callHistory.reduce((sum, c) => sum + (c.duration || 0), 0);
      if (total === 0) return '0秒';
      const h = Math.floor(total / 3600);
      const m = Math.floor((total % 3600) / 60);
      const s = total % 60;
      if (h > 0) return `${h}小时${m}分`;
      if (m > 0) return `${m}分${s}秒`;
      return `${s}秒`;
    },
    tokenMasked() {
      if (!this.token) return '无';
      if (this.token.length <= 8) return this.token;
      return this.token.slice(0, 4) + '****' + this.token.slice(-4);
    },
  },
  watch: {
    currentTab(val) {
      // 切到"最近通话"时刷新
      if (val === 0 && this.token && !this.callHistory.length) {
        this.loadHistory();
      }
      // 切到"我的"时加载余额
      if (val === 2 && this.token) {
        this.loadBalance();
      }
    },
  },
  methods: {
    startCall() {
      if (!this.token) {
        uni.showToast({ title: '请先登录', icon: 'none' });
        return;
      }
      uni.navigateTo({ url: '/pages/call/call?token=' + this.token });
    },

    // ---- 云端设置同步 ----
    async syncFromCloud() {
      try {
        const data = await loadCloudSettings(this.token);
        // 云端有值且本地为空时，用云端的
        if (data.user_id && !this.ctxUserId) {
          this.ctxUserId = data.user_id;
          set(KEYS.USER_ID, data.user_id);
        }
        if (data.user_info && !this.ctxUserInfo) {
          this.ctxUserInfo = data.user_info;
          set(KEYS.USER_INFO, data.user_info);
        }
        if (data.topic && !this.ctxTopic) {
          this.ctxTopic = data.topic;
          set(KEYS.TOPIC, data.topic);
        }
        if (data.extra_prompt && !this.ctxExtraPrompt) {
          this.ctxExtraPrompt = data.extra_prompt;
          set(KEYS.EXTRA_PROMPT, data.extra_prompt);
        }
      } catch (e) {
        console.warn('[index] syncFromCloud failed:', e);
      }
    },

    syncToCloud() {
      if (!this.token || !get(KEYS.API_KEY)) return;
      saveCloudSettings(this.token, {
        user_id: this.ctxUserId,
        user_info: this.ctxUserInfo,
        topic: this.ctxTopic,
        extra_prompt: this.ctxExtraPrompt,
      }).catch(e => console.warn('[index] syncToCloud failed:', e));
    },

    // ---- Tab 1: 通话记录 ----
    async loadHistory() {
      this.historyLoading = true;
      try {
        const data = await getCallHistory(this.token);
        // API 返回 {calls: [...]}，后端字段: call_id, start_time, duration, summary, memory, rounds
        const rawCalls = data.calls || data || [];
        // 统一字段映射 → App 内部统一用 id / created_at
        const calls = rawCalls.map(c => ({
          ...c,
          id: c.call_id || c.id,
          created_at: c.start_time || c.created_at,
        }));
        this.callHistory = calls.sort((a, b) => {
          return new Date(b.created_at) - new Date(a.created_at);
        });
      } catch (e) {
        console.error('[index] loadHistory error:', e);
      } finally {
        this.historyLoading = false;
      }
    },

    getLastMsg(call) {
      // call-history API 不返回 messages，优先用 summary/memory
      if (call.summary) {
        const text = call.summary;
        return text.length > 30 ? text.slice(0, 30) + '...' : text;
      }
      if (call.memory) {
        const text = call.memory;
        return text.length > 30 ? text.slice(0, 30) + '...' : text;
      }
      if (call.rounds) return call.rounds + '轮对话';
      // 如果有完整 messages（从 detail 加载过的）
      if (call.messages && call.messages.length) {
        for (let i = call.messages.length - 1; i >= 0; i--) {
          if (call.messages[i].role === 'assistant') {
            const text = call.messages[i].content || '';
            return text.length > 30 ? text.slice(0, 30) + '...' : text;
          }
        }
        return call.messages[call.messages.length - 1].content?.slice(0, 30) || '无消息';
      }
      return '无消息';
    },

    formatTime(ts) {
      if (!ts) return '';
      const d = new Date(ts);
      const now = new Date();
      const isToday = d.toDateString() === now.toDateString();
      const pad = n => String(n).padStart(2, '0');
      if (isToday) {
        return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
      }
      // 昨天
      const yesterday = new Date(now);
      yesterday.setDate(yesterday.getDate() - 1);
      if (d.toDateString() === yesterday.toDateString()) {
        return '昨天';
      }
      // 今年
      if (d.getFullYear() === now.getFullYear()) {
        return `${d.getMonth() + 1}/${d.getDate()}`;
      }
      return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
    },

    formatDuration(sec) {
      if (!sec && sec !== 0) return '';
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      if (m > 0) return `${m}分${s}秒`;
      return `${s}秒`;
    },

    async onCallTap(call) {
      this.detailCall = { ...call };
      this.detailEditing = false;
      this.detailEditMessages = [];
      this.detailMemGenerating = false;
      this.detailAudioMap = {};
      this.detailPlayingIdx = -1;
      this.stopDetailAudio();
      // 总是从 call-detail API 获取完整数据（messages, memory, audio_segments）
      if (call.id) {
        try {
          const detail = await getCallDetail(this.token, call.id);
          if (detail) {
            if (detail.messages) call.messages = detail.messages;
            if (detail.memory) call.memory = detail.memory;
            if (detail.summary && !call.memory) call.memory = detail.summary;
            if (detail.duration) call.duration = detail.duration;
            // 构建音频映射
            if (detail.audio_segments) {
              this.buildAudioMap(detail.audio_segments);
            }
          }
          // 触发视图更新
          this.detailCall = { ...call };
        } catch (e) {
          console.error('[index] getCallDetail error:', e);
        }
      }
    },

    // ---- 音频回放 ----
    buildAudioMap(segments) {
      const map = {};
      const hasMsgIndex = segments.some(s => s.type === 'ai' && typeof s.msg_index === 'number');
      if (hasMsgIndex) {
        for (const seg of segments) {
          if (seg.type === 'ai' && typeof seg.msg_index === 'number') {
            if (!map[seg.msg_index]) map[seg.msg_index] = [];
            map[seg.msg_index].push(seg.path);
          }
        }
      } else {
        // 兼容旧数据：按 user 分组
        let groupIdx = 0;
        let currentGroup = [];
        for (const seg of segments) {
          if (seg.type === 'ai') {
            currentGroup.push(seg.path);
          } else {
            if (currentGroup.length > 0) {
              map[groupIdx] = currentGroup;
              groupIdx++;
              currentGroup = [];
            }
          }
        }
        if (currentGroup.length > 0) {
          map[groupIdx] = currentGroup;
        }
      }
      this.detailAudioMap = map;
    },

    getAssistantIndex(msgIdx) {
      // 计算某条消息是第几条 assistant 消息
      if (!this.detailCall || !this.detailCall.messages) return -1;
      let count = 0;
      for (let i = 0; i < msgIdx; i++) {
        if (this.detailCall.messages[i].role === 'assistant') count++;
      }
      return count;
    },

    hasAudio(msgIdx) {
      const aIdx = this.getAssistantIndex(msgIdx);
      return !!(this.detailAudioMap[aIdx] && this.detailAudioMap[aIdx].length > 0);
    },

    playDetailAudio(msgIdx) {
      const aIdx = this.getAssistantIndex(msgIdx);
      const paths = this.detailAudioMap[aIdx];
      if (!paths || paths.length === 0) return;

      // 如果点的是正在播放的，则停止
      if (this.detailPlayingIdx === msgIdx) {
        this.stopDetailAudio();
        return;
      }

      this.stopDetailAudio();
      this.detailPlayingIdx = msgIdx;
      this.detailAudioQueue = [...paths];
      this._playNextDetailSegment();
    },

    _playNextDetailSegment() {
      if (this.detailAudioQueue.length === 0) {
        this.detailPlayingIdx = -1;
        return;
      }
      const path = this.detailAudioQueue.shift();
      const url = 'https://yolanda083-voice-call-test.hf.space/api/audio-segment?path=' + encodeURIComponent(path) + '&token=' + encodeURIComponent(this.token);

      if (this.detailAudioPlayer) {
        this.detailAudioPlayer.destroy();
      }
      this.detailAudioPlayer = uni.createInnerAudioContext();
      this.detailAudioPlayer.src = url;
      this.detailAudioPlayer.onEnded(() => {
        this._playNextDetailSegment();
      });
      this.detailAudioPlayer.onError(() => {
        // 跳过失败的段
        this._playNextDetailSegment();
      });
      this.detailAudioPlayer.play();
    },

    stopDetailAudio() {
      this.detailPlayingIdx = -1;
      this.detailAudioQueue = [];
      if (this.detailAudioPlayer) {
        try { this.detailAudioPlayer.stop(); } catch(e) {}
        try { this.detailAudioPlayer.destroy(); } catch(e) {}
        this.detailAudioPlayer = null;
      }
    },

    // ---- 通话详情编辑 ----
    startDetailEdit() {
      if (!this.detailCall || !this.detailCall.messages || !this.detailCall.messages.length) {
        uni.showToast({ title: '无消息可编辑', icon: 'none' });
        return;
      }
      this.detailEditMessages = this.detailCall.messages.map(m => ({ role: m.role, content: m.content }));
      this.detailEditing = true;
    },

    cancelDetailEdit() {
      this.detailEditing = false;
      this.detailEditMessages = [];
    },

    async saveDetailEdit() {
      if (!this.detailCall || !this.detailCall.id) return;
      const messages = this.detailEditMessages
        .map(m => ({ role: m.role, content: (m.content || '').trim() }))
        .filter(m => m.content);
      try {
        await updateCallMessages(this.token, this.detailCall.id, messages);
        // 更新本地数据
        this.detailCall.messages = messages;
        this.detailCall = { ...this.detailCall };
        this.detailEditing = false;
        this.detailEditMessages = [];
        uni.showToast({ title: '已保存', icon: 'success' });
        // 刷新通话记录列表
        this.loadHistory();
      } catch (e) {
        uni.showToast({ title: '保存失败', icon: 'none' });
      }
    },

    // ---- 通话详情记忆生成 ----
    async doGenerateMemory() {
      if (this.detailMemGenerating || !this.detailCall || !this.detailCall.id) return;
      this.detailMemGenerating = true;
      try {
        const result = await generateCallMemory(this.token, this.detailCall.id);
        if (result && result.memory) {
          this.detailCall.memory = result.memory;
          this.detailCall = { ...this.detailCall };
          uni.showToast({ title: '记忆已生成', icon: 'success' });
        } else if (result && result.error) {
          uni.showToast({ title: result.error, icon: 'none' });
        }
      } catch (e) {
        uni.showToast({ title: '生成失败', icon: 'none' });
      } finally {
        this.detailMemGenerating = false;
      }
    },

    confirmDelete(call) {
      uni.showModal({
        title: '删除通话记录',
        content: '确定要删除这条通话记录吗？',
        confirmColor: '#FF3B30',
        success: (res) => {
          if (res.confirm) {
            this.doDelete(call);
          }
        },
      });
    },

    async doDelete(call) {
      try {
        // 后端 DELETE 需要 call_id
        const callId = call.call_id || call.id;
        await deleteCallHistory(this.token, callId);
        this.callHistory = this.callHistory.filter(c => (c.call_id || c.id) !== callId);
        this.detailCall = null;
        uni.showToast({ title: '已删除', icon: 'success' });
      } catch (e) {
        uni.showToast({ title: '删除失败', icon: 'none' });
      }
    },

    // ---- Tab 3: 我的 ----
    openSubPage(page) {
      this.mySubPage = page;
      // 进入记忆页时加载
      if (page === 'memory' && this.token) {
        this.loadMemories();
      }
      // 进入 API 配置页时加载内置模型
      if (page === 'api') {
        this.loadBuiltinModels();
      }
    },

    // ---- API 配置 ----
    async loadBuiltinModels() {
      if (this.builtinModels.length) return;
      this.builtinLoading = true;
      try {
        const data = await getBuiltinModels();
        this.builtinModels = data.models || data || [];
        if (!this.apiBuiltinModel && this.builtinModels.length) {
          this.apiBuiltinModel = this.builtinModels[0];
        }
      } catch (e) {
        console.error('[index] loadBuiltinModels error:', e);
      } finally {
        this.builtinLoading = false;
      }
    },

    async fetchCustomLlmModels() {
      if (!this.apiLlmUrl || !this.apiLlmKey) {
        uni.showToast({ title: '请先填写 API 地址和 Key', icon: 'none' });
        return;
      }
      this.customLlmLoading = true;
      try {
        const data = await getModels(this.apiLlmUrl, this.apiLlmKey);
        this.customLlmModels = data.models || data || [];
        if (this.customLlmModels.length && !this.apiLlmModel) {
          this.apiLlmModel = this.customLlmModels[0];
        }
        if (!this.customLlmModels.length) {
          uni.showToast({ title: '未获取到模型', icon: 'none' });
        }
      } catch (e) {
        uni.showToast({ title: '获取失败', icon: 'none' });
      } finally {
        this.customLlmLoading = false;
      }
    },

    saveApiConfig() {
      // 保存 LLM 配置
      if (this.apiLlmCustom) {
        setJSON(KEYS.CUSTOM_LLM, {
          base_url: this.apiLlmUrl,
          api_key: this.apiLlmKey,
          model: this.apiLlmModel,
        });
        set(KEYS.BUILTIN_LLM, 'false');
      } else {
        setJSON(KEYS.CUSTOM_LLM, null);
        set(KEYS.BUILTIN_LLM, 'true');
        set(KEYS.BUILTIN_MODEL, this.apiBuiltinModel);
      }
      // 保存 TTS 配置
      if (this.apiTtsCustom) {
        setJSON(KEYS.CUSTOM_TTS, {
          base_url: this.apiTtsUrl,
          api_key: this.apiTtsKey,
          voice_id: this.apiTtsVoice,
          model: this.apiTtsModel,
        });
        set(KEYS.BUILTIN_TTS, 'false');
      } else {
        setJSON(KEYS.CUSTOM_TTS, null);
        set(KEYS.BUILTIN_TTS, 'true');
      }
      uni.showToast({ title: '已保存', icon: 'success' });
    },

    async doRedeemCard() {
      const code = this.redeemCode.trim();
      this.redeemMsg = '';
      if (!code) {
        this.redeemMsg = '请输入充值码';
        return;
      }
      this.redeemLoading = true;
      try {
        const data = await redeemCard(this.token, code);
        if (data.error) {
          this.redeemMsg = data.error;
        } else {
          this.redeemMsg = '充值成功！';
          this.redeemCode = '';
          this.loadBalance();
        }
      } catch (e) {
        this.redeemMsg = e?.data?.error || '充值失败，请重试';
      } finally {
        this.redeemLoading = false;
      }
    },

    saveContextSettings() {
      set(KEYS.MAX_HISTORY, String(this.ctxMaxHistory));
      set(KEYS.EXTRA_PROMPT, this.ctxExtraPrompt);
      this.syncToCloud();
      uni.showToast({ title: '已保存', icon: 'success' });
    },

    saveProfileSettings() {
      set(KEYS.USER_ID, this.ctxUserId);
      set(KEYS.USER_INFO, this.ctxUserInfo);
      set(KEYS.TOPIC, this.ctxTopic);
      this.syncToCloud();
      uni.showToast({ title: '已保存', icon: 'success' });
    },

    saveCallPageSettings() {
      set(KEYS.SHOW_SUBTITLE, String(this.csShowSubtitle));
      set(KEYS.VIDEO_ENABLED, String(this.csVideoEnabled));
      set(KEYS.API_RETRY_COUNT, String(this.csRetryCount));
      uni.showToast({ title: '已保存', icon: 'success' });
    },

    // ---- 通话记忆 ----
    async loadMemories() {
      this.memLoading = true;
      this.memErrorMsg = '';
      try {
        const data = await getMemorySummaries(this.token);
        console.log('[index] getMemorySummaries response:', JSON.stringify(data).slice(0, 200));
        this.memorySummaries = data.summaries || data || [];
      } catch (e) {
        const errDetail = e && e.data && e.data.error ? e.data.error : (e && e.statusCode ? 'HTTP ' + e.statusCode : (e && e.message ? e.message : JSON.stringify(e).slice(0, 100)));
        console.warn('[index] getMemorySummaries failed:', errDetail);
        this.memErrorMsg = '加载失败: ' + errDetail;
        // 回退：从通话记录里过滤有 memory 的记录
        try {
          const histData = await getCallHistory(this.token);
          const calls = histData.calls || histData || [];
          const memCalls = calls.filter(c => c.memory);
          if (memCalls.length > 0) {
            this.memorySummaries = memCalls.map(c => ({
              id: c.call_id || c.id,
              text: c.memory,
              created_at: c.start_time || c.created_at,
            }));
            this.memErrorMsg = '(已从通话记录中恢复记忆)';
          }
        } catch (e2) {
          console.error('[index] loadMemories fallback error:', e2);
        }
      } finally {
        this.memLoading = false;
      }
    },

    async toggleAutoMemory(val) {
      this.memAutoEnabled = val;
      try {
        await setAutoMemory(this.token, val);
        set(KEYS.AUTO_MEMORY, String(val));
      } catch (e) {
        uni.showToast({ title: '设置失败', icon: 'none' });
      }
    },

    startEditMem(mem) {
      this.editingMemId = mem.id;
      this.editingMemText = mem.text;
    },

    async saveEditMem(mem) {
      try {
        await updateMemory(this.token, mem.id, this.editingMemText);
        mem.text = this.editingMemText;
        this.editingMemId = null;
        uni.showToast({ title: '已保存', icon: 'success' });
      } catch (e) {
        uni.showToast({ title: '保存失败', icon: 'none' });
      }
    },

    confirmDeleteMem(mem) {
      uni.showModal({
        title: '删除记忆',
        content: '确定要删除这条记忆吗？',
        confirmColor: '#FF3B30',
        success: (res) => {
          if (res.confirm) this.doDeleteMem(mem);
        },
      });
    },

    async doDeleteMem(mem) {
      try {
        await deleteMemory(this.token, mem.id);
        this.memorySummaries = this.memorySummaries.filter(m => m.id !== mem.id);
        uni.showToast({ title: '已删除', icon: 'success' });
      } catch (e) {
        uni.showToast({ title: '删除失败', icon: 'none' });
      }
    },

    async loadBalance() {
      try {
        const data = await getBalance(this.token);
        this.balanceText = data.balance_yuan !== undefined
          ? `¥${Number(data.balance_yuan).toFixed(2)}`
          : '--';
      } catch (e) {
        this.balanceText = '--';
      }
    },

    // ---- 退出登录 ----
    confirmLogout() {
      uni.showModal({
        title: '退出登录',
        content: '确定要退出登录吗？所有本地数据将被清除。',
        confirmColor: '#FF3B30',
        confirmText: '退出',
        success: (res) => {
          if (res.confirm) {
            this.doLogout();
          }
        },
      });
    },

    doLogout() {
      // 清除所有已知的 storage keys
      Object.values(KEYS).forEach(key => {
        remove(key);
      });
      // 跳转回登录页
      uni.reLaunch({ url: '/pages/login/login' });
    },
  },
};
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #000;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow-x: hidden;
  overflow-y: auto;
  width: 100%;
  max-width: 100vw;
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

.status-bar {
  width: 100%;
  background: #000;
}

/* ---- Tab 视图通用 ---- */
.tab-view {
  flex: 1;
  padding: 0 32rpx;
  padding-bottom: 160rpx; /* 给 tab-bar 留空间 */
  width: 100%;
  box-sizing: border-box;
}

.tab-header {
  padding: 24rpx 0 16rpx;
}

.tab-title {
  font-size: 64rpx;
  font-weight: 700;
  color: #fff;
}

/* ---- 占位 ---- */
.placeholder-box {
  margin-top: 40rpx;
  background: #1C1C1E;
  border-radius: 24rpx;
  padding: 48rpx 32rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-text {
  font-size: 30rpx;
  color: #8E8E93;
}

/* ---- 拨号页 ---- */
.dial-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
}

.dial-role {
  font-size: 56rpx;
  font-weight: 700;
  color: #fff;
  margin-bottom: 16rpx;
}

.dial-hint {
  font-size: 28rpx;
  color: #8E8E93;
  margin-bottom: 80rpx;
}

.dial-btn {
  width: 160rpx;
  height: 160rpx;
  border-radius: 50%;
  background: #34C759;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8rpx 32rpx rgba(52, 199, 89, 0.4);
}

.dial-btn:active {
  opacity: 0.8;
  transform: scale(0.95);
}

/* 拨号按钮图标已改用 image 标签 */

/* ---- 底部 Tab 栏 ---- */
.tab-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 120rpx;
  background: #1C1C1E;
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding-bottom: env(safe-area-inset-bottom);
  border-top: 1rpx solid rgba(255, 255, 255, 0.08);
}

.tab-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  padding: 8rpx 0;
}

/* tab-icon-wrap 已不再需要 */

/* tab 图标已改用 image 标签 */

.tab-label {
  font-size: 22rpx;
  color: #8E8E93;
}

.tab-item.active .tab-label {
  color: #0A84FF;
}

/* ---- Tab 1: 通话记录列表 ---- */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding-top: 200rpx;
}

/* 空状态圆形图标 */
.empty-icon-circle {
  width: 120rpx;
  height: 120rpx;
  border-radius: 50%;
  background: #2C2C2E;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24rpx;
}
.empty-icon-char {
  font-size: 52rpx;
  color: #636366;
  font-style: normal;
}

.empty-text {
  font-size: 32rpx;
  color: #fff;
  margin-bottom: 8rpx;
}

.empty-hint {
  font-size: 26rpx;
  color: #8E8E93;
}

.call-list {
  margin-top: 16rpx;
}

.call-item {
  display: flex;
  flex-direction: row;
  align-items: center;
  padding: 24rpx 0;
  border-bottom: 1rpx solid rgba(255, 255, 255, 0.06);
}

.call-item:active {
  background: rgba(255, 255, 255, 0.04);
}

.call-avatar {
  width: 88rpx;
  height: 88rpx;
  border-radius: 50%;
  background: linear-gradient(180deg, #b0b0b5, #8e8e93);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-right: 24rpx;
}

.avatar-text {
  font-size: 36rpx;
  color: #fff;
  font-weight: 600;
}

.call-info {
  flex: 1;
  min-width: 0;
}

.call-row-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8rpx;
}

.call-name {
  font-size: 32rpx;
  color: #fff;
  font-weight: 500;
}

.call-time {
  font-size: 24rpx;
  color: #8E8E93;
  flex-shrink: 0;
  margin-left: 16rpx;
}

.call-row-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.call-last-msg {
  font-size: 26rpx;
  color: #8E8E93;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.call-duration {
  font-size: 24rpx;
  color: #636366;
  flex-shrink: 0;
  margin-left: 16rpx;
}

/* ---- 通话详情弹窗 ---- */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: flex-end;
  justify-content: center;
  z-index: 999;
}

.detail-modal {
  width: 100%;
  max-height: 85vh;
  background: #1C1C1E;
  border-radius: 32rpx 32rpx 0 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.detail-header {
  display: flex;
  align-items: center;
  padding: 32rpx;
  border-bottom: 1rpx solid rgba(255, 255, 255, 0.08);
}

.detail-avatar {
  width: 80rpx;
  height: 80rpx;
  border-radius: 50%;
  background: #2C2C2E;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-right: 20rpx;
}

.detail-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.detail-name {
  font-size: 32rpx;
  color: #fff;
  font-weight: 600;
}

.detail-time {
  font-size: 24rpx;
  color: #8E8E93;
  margin-top: 4rpx;
}

.detail-close {
  font-size: 36rpx;
  color: #8E8E93;
  padding: 16rpx;
  flex-shrink: 0;
}

/* 消息气泡 */
.detail-messages {
  flex: 1;
  max-height: 50vh;
  padding: 24rpx 32rpx;
}

.bubble-row {
  display: flex;
  margin-bottom: 20rpx;
}

.bubble-right {
  justify-content: flex-end;
}

.bubble-left {
  justify-content: flex-start;
}

.bubble {
  max-width: 75%;
  padding: 20rpx 28rpx;
  border-radius: 24rpx;
}

.bubble-user {
  background: #0A84FF;
  border-bottom-right-radius: 8rpx;
}

.bubble-ai {
  background: #2C2C2E;
  border-bottom-left-radius: 8rpx;
}

.bubble-text {
  font-size: 28rpx;
  color: #fff;
  line-height: 1.5;
}

/* 音频回放按钮 */
.bubble-play-btn {
  width: 48rpx;
  height: 48rpx;
  border-radius: 50%;
  background: rgba(255,255,255,0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 8rpx;
  flex-shrink: 0;
}
.bubble-play-btn.playing {
  background: rgba(10, 132, 255, 0.4);
}
.bubble-play-icon {
  font-size: 22rpx;
  color: #fff;
}

.detail-empty {
  padding: 48rpx 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 记忆总结 - moved to detail-actions section above */

.memory-label {
  font-size: 26rpx;
  color: #8E8E93;
  margin-bottom: 12rpx;
  display: block;
}

.memory-text {
  font-size: 28rpx;
  color: #fff;
  line-height: 1.5;
}

/* 操作按钮 */
.detail-actions {
  padding: 24rpx 32rpx;
  padding-bottom: calc(24rpx + env(safe-area-inset-bottom));
  border-top: 1rpx solid rgba(255, 255, 255, 0.08);
}

.detail-actions-row {
  display: flex;
  gap: 16rpx;
}

.action-btn {
  flex: 1;
  padding: 24rpx;
  border-radius: 20rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-delete {
  background: rgba(255, 59, 48, 0.15);
}

.action-delete:active {
  background: rgba(255, 59, 48, 0.3);
}

.action-edit {
  background: rgba(10, 132, 255, 0.15);
}

.action-edit:active {
  background: rgba(10, 132, 255, 0.3);
}

.action-save {
  background: rgba(10, 132, 255, 0.15);
}

.action-save:active {
  background: rgba(10, 132, 255, 0.3);
}

.action-cancel {
  background: rgba(142, 142, 147, 0.15);
}

.action-cancel:active {
  background: rgba(142, 142, 147, 0.3);
}

.action-text {
  font-size: 30rpx;
  color: #FF3B30;
  font-weight: 500;
}

.action-text-blue {
  color: #0A84FF;
}

.action-text-gray {
  color: #8E8E93;
}

/* 编辑模式气泡 */
.bubble-editing {
  padding: 8rpx;
}

.bubble-edit-textarea {
  width: 100%;
  min-height: 60rpx;
  border: none;
  background: transparent;
  font-size: 28rpx;
  color: #fff;
  line-height: 1.5;
  padding: 12rpx 20rpx;
}

/* 记忆区域 */
.detail-memory {
  padding: 24rpx 32rpx;
  border-top: 1rpx solid rgba(255, 255, 255, 0.08);
}

.detail-memory-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12rpx;
}

.memory-gen-btn {
  padding: 8rpx 24rpx;
  background: rgba(10, 132, 255, 0.15);
  border-radius: 12rpx;
}

.memory-gen-btn:active {
  background: rgba(10, 132, 255, 0.3);
}

.memory-gen-btn.disabled {
  opacity: 0.5;
}

.memory-gen-text {
  font-size: 24rpx;
  color: #0A84FF;
  font-weight: 500;
}

.memory-empty {
  color: #636366;
  font-style: italic;
}

/* ---- Tab 3: 我的 ---- */
.my-card {
  background: #1C1C1E;
  border-radius: 24rpx;
  margin-bottom: 24rpx;
  overflow: hidden;
  width: 100%;
  box-sizing: border-box;
}

.user-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 28rpx 32rpx;
}

.user-card-left {
  display: flex;
  align-items: center;
}

.user-avatar {
  width: 96rpx;
  height: 96rpx;
  border-radius: 50%;
  background: linear-gradient(180deg, #b0b0b5, #8e8e93);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 24rpx;
}

.user-card-info {
  display: flex;
  flex-direction: column;
}

.user-card-name {
  font-size: 34rpx;
  color: #fff;
  font-weight: 600;
}

.user-card-type {
  font-size: 24rpx;
  color: #8E8E93;
  margin-top: 4rpx;
}

.card-arrow {
  font-size: 36rpx;
  color: #636366;
  flex-shrink: 0;
}

.my-item {
  display: flex;
  align-items: center;
  padding: 28rpx 32rpx;
  border-bottom: 1rpx solid rgba(255, 255, 255, 0.06);
}

.my-item.last-item {
  border-bottom: none;
}

.my-item:active {
  background: rgba(255, 255, 255, 0.04);
}

/* iOS 风格设置项圆形图标 */
.my-item-icon-wrap {
  margin-right: 20rpx;
  flex-shrink: 0;
}
.item-icon-circle {
  width: 56rpx;
  height: 56rpx;
  border-radius: 14rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}
.item-icon-char {
  font-size: 28rpx;
  color: #fff;
  font-weight: 600;
  font-style: normal;
}
.item-icon-img {
  width: 36rpx;
  height: 36rpx;
}
.tab-icon-img {
  width: 48rpx;
  height: 48rpx;
  margin-bottom: 4rpx;
}
.dial-icon-img {
  width: 56rpx;
  height: 56rpx;
}
.bg-purple { background: #AF52DE; }
.bg-gray { background: #636366; }
.bg-blue { background: #0A84FF; }
.bg-green { background: #34C759; }
.bg-orange { background: #FF9500; }
.bg-teal { background: #5AC8FA; }
.bg-red { background: #FF3B30; }

.my-item-title {
  font-size: 30rpx;
  color: #fff;
  flex: 1;
}

.my-item-value {
  font-size: 26rpx;
  color: #8E8E93;
  margin-right: 12rpx;
  flex-shrink: 0;
}

/* ---- 子页面覆盖层 ---- */
.sub-page {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: #000;
  z-index: 100;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 100vw;
  overflow-x: hidden;
}

.sub-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16rpx 32rpx;
  background: #000;
  border-bottom: 1rpx solid rgba(255, 255, 255, 0.08);
}

.sub-back {
  font-size: 34rpx;
  color: #0A84FF;
  padding: 8rpx 0;
  min-width: 120rpx;
}

.sub-nav-title {
  font-size: 32rpx;
  color: #fff;
  font-weight: 600;
}

.sub-nav-right {
  min-width: 120rpx;
}

.sub-content {
  flex: 1;
  padding: 32rpx;
  width: 100%;
  box-sizing: border-box;
}

/* ---- 余额卡片 ---- */
.balance-card {
  padding: 48rpx 32rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.balance-label {
  font-size: 26rpx;
  color: #8E8E93;
  margin-bottom: 16rpx;
}

.balance-amount {
  font-size: 72rpx;
  font-weight: 700;
  color: #fff;
}

/* ---- 子页面通用表单 ---- */
.sub-section-title {
  font-size: 28rpx;
  color: #8E8E93;
  margin-bottom: 16rpx;
  display: block;
}

.sub-input-group {
  background: #2C2C2E;
  border-radius: 16rpx;
  padding: 8rpx 24rpx;
  margin-bottom: 24rpx;
  width: 100%;
  box-sizing: border-box;
}

.sub-input {
  width: 100%;
  height: 80rpx;
  border: none;
  background: transparent;
  font-size: 30rpx;
  color: #fff;
  box-sizing: border-box;
}

.sub-btn {
  background: #0A84FF;
  border-radius: 20rpx;
  padding: 24rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.sub-btn:active {
  opacity: 0.8;
}

.sub-btn.disabled {
  opacity: 0.5;
}

.sub-btn-text {
  font-size: 30rpx;
  color: #fff;
  font-weight: 500;
}

.sub-hint {
  font-size: 26rpx;
  color: #8E8E93;
  text-align: center;
  margin-top: 16rpx;
  display: block;
}

.token-text {
  font-family: monospace;
  font-size: 24rpx;
}

/* ---- Stepper 步进器 ---- */
.stepper-row {
  display: flex;
  align-items: center;
  margin-top: 16rpx;
}

.stepper-row.compact {
  margin-top: 0;
}

.stepper-btn {
  width: 72rpx;
  height: 72rpx;
  border-radius: 16rpx;
  background: #2C2C2E;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stepper-btn.sm {
  width: 56rpx;
  height: 56rpx;
  border-radius: 12rpx;
}

.stepper-btn:active {
  background: #3A3A3C;
}

.stepper-text {
  font-size: 36rpx;
  color: #fff;
  font-weight: 300;
}

.stepper-value {
  font-size: 36rpx;
  color: #fff;
  font-weight: 600;
  min-width: 80rpx;
  text-align: center;
}

.stepper-value.sm {
  font-size: 30rpx;
  min-width: 60rpx;
}

/* ---- Textarea ---- */
.sub-textarea-group {
  background: #2C2C2E;
  border-radius: 16rpx;
  padding: 16rpx 24rpx;
  margin-top: 8rpx;
  width: 100%;
  box-sizing: border-box;
}

.sub-textarea {
  width: 100%;
  min-height: 160rpx;
  border: none;
  background: transparent;
  font-size: 28rpx;
  color: #fff;
  line-height: 1.5;
  box-sizing: border-box;
}

.sub-desc {
  font-size: 24rpx;
  color: #636366;
  margin-bottom: 16rpx;
  display: block;
}

/* ---- 通话记忆 ---- */
.mem-list {
  margin-top: 24rpx;
}

.mem-card {
  margin-bottom: 16rpx;
}

.mem-text {
  font-size: 28rpx;
  color: #fff;
  line-height: 1.6;
  display: block;
}

.mem-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16rpx;
}

.mem-time {
  font-size: 24rpx;
  color: #636366;
}

.mem-actions {
  display: flex;
  gap: 24rpx;
}

.mem-action-btn {
  font-size: 26rpx;
  color: #0A84FF;
  padding: 4rpx 0;
}

.mem-delete {
  color: #FF3B30;
}

.mem-edit-actions {
  display: flex;
  gap: 16rpx;
  margin-top: 16rpx;
}

.mem-edit-btn {
  flex: 1;
  padding: 20rpx;
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mem-edit-btn.cancel {
  background: #2C2C2E;
}

.mem-edit-btn.save {
  background: #0A84FF;
}

.mem-edit-btn-text {
  font-size: 28rpx;
  color: #fff;
  font-weight: 500;
}

.cancel-text {
  color: #8E8E93;
}

/* ---- API 配置 ---- */
.toggle-row {
  display: flex;
  background: #2C2C2E;
  border-radius: 16rpx;
  padding: 6rpx;
  margin-bottom: 8rpx;
}

.toggle-btn {
  flex: 1;
  padding: 16rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.toggle-btn.active {
  background: #0A84FF;
}

.toggle-text {
  font-size: 28rpx;
  color: #8E8E93;
  font-weight: 500;
}

.toggle-btn.active .toggle-text {
  color: #fff;
}

.model-list {
  margin-top: 8rpx;
  height: 400rpx;
  max-height: 400rpx;
}

.model-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx;
  background: #2C2C2E;
  border-radius: 12rpx;
  margin-bottom: 8rpx;
}

.model-item.selected {
  background: rgba(10, 132, 255, 0.15);
}

.model-item:active {
  opacity: 0.8;
}

.model-name {
  font-size: 28rpx;
  color: #fff;
  flex: 1;
}

.model-check {
  font-size: 28rpx;
  color: #0A84FF;
  font-weight: 600;
  flex-shrink: 0;
  margin-left: 16rpx;
}

.sub-btn.secondary {
  background: #2C2C2E;
}

/* ---- 退出登录 ---- */
.logout-area {
  display: flex;
  justify-content: center;
  padding: 32rpx 0 16rpx;
}

.logout-btn {
  font-size: 30rpx;
  color: #FF3B30;
  padding: 16rpx 48rpx;
}

.logout-btn:active {
  opacity: 0.6;
}
</style>
