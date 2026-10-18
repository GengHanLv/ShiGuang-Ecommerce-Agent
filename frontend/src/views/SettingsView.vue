<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '@/components/AppIcon.vue'
import { useConnectionStore } from '@/stores/connection'
import { useChatStore } from '@/stores/chat'
import { checkServices } from '@/api/workspace'
import { errorMessage } from '@/api/http'
import type { ServiceStatus } from '@/types'
const connection = useConnectionStore()
const chat = useChatStore()
const form = reactive({
  baseUrl: connection.baseUrl,
  apiKey: connection.apiKey,
  userId: connection.userId,
  stream: connection.stream,
})
const testing = ref(false)
const status = ref<ServiceStatus>()
const error = ref('')
function save() {
  if (chat.busy) {
    ElMessage.warning('请先等待回复完成或停止生成，再修改连接设置')
    return false
  }
  if (!form.baseUrl.trim() || !form.userId.trim()) {
    ElMessage.warning('请填写服务地址和用户标识')
    return false
  }
  const base = form.baseUrl.trim().replace(/\/$/, '')
  if (
    !(base.startsWith('/') && !base.startsWith('//')) &&
    !/^https?:\/\/[^\s/]+/i.test(base)
  ) {
    ElMessage.warning('服务地址需为 /api 或完整的 http(s) 地址')
    return false
  }
  connection.$patch({
    baseUrl: base,
    apiKey: form.apiKey.trim(),
    userId: form.userId.trim(),
    stream: form.stream,
  })
  status.value = undefined
  error.value = ''
  return true
}
function saveSettings() {
  if (save()) ElMessage.success('连接设置已保存')
}
async function test() {
  if (!form.apiKey.trim()) {
    ElMessage.warning('请先填写 API Key')
    return
  }
  if (!save()) return
  testing.value = true
  error.value = ''
  try {
    status.value = await checkServices()
    ElMessage[status.value.status === 'ok' ? 'success' : 'warning'](
      status.value.status === 'ok' ? '服务连接正常' : '部分服务暂不可用',
    )
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    testing.value = false
  }
}
async function clear() {
  if (chat.busy) {
    ElMessage.warning('请先停止当前回复')
    return
  }
  try {
    await ElMessageBox.confirm(
      '将清除当前用户在此浏览器中的对话记录，后端长期记忆保持不变。',
      '清除本地记录',
      {
        type: 'warning',
        confirmButtonText: '清除记录',
        cancelButtonText: '取消',
      },
    )
    chat.clear()
    ElMessage.success('本地记录已清除')
  } catch {
    /* canceled */
  }
}
const services = [
  { key: 'redis', label: '会话服务', description: '保存多轮对话上下文' },
  { key: 'mysql', label: '订单服务', description: '查询实时订单信息' },
  { key: 'milvus', label: '知识与记忆', description: '检索知识片段和用户偏好' },
] as const
</script>
<template>
  <div class="standard-page settings-page">
    <div class="section-header">
      <div>
        <span class="workspace-label">MAKE IT YOURS</span>
        <h1>一切，从连接开始</h1>
        <p>配置你的客服服务，拾光就准备好为你工作了。</p>
      </div>
      <span class="section-decoration"
        ><AppIcon name="Connection" :size="36"
      /></span>
    </div>
    <div class="settings-columns">
      <section class="panel connection-panel">
        <div class="panel-heading">
          <div>
            <h2>服务连接</h2>
            <p>填入后端地址与访问凭证</p>
          </div>
          <AppIcon name="Connection" :size="22" />
        </div>
        <el-form
          label-position="top"
          :model="form"
          @submit.prevent="saveSettings"
          ><el-form-item label="服务地址"
            ><el-input
              v-model="form.baseUrl"
              placeholder="/api 或 http://127.0.0.1:8000"
              :disabled="testing"
            />
            <p class="field-hint">
              本地开发默认使用 /api，由开发服务器转发到 8000 端口
            </p></el-form-item
          ><el-form-item label="API Key"
            ><el-input
              v-model="form.apiKey"
              type="password"
              show-password
              autocomplete="off"
              placeholder="填写后端 .env 中的 API_KEY"
              :disabled="testing"
            />
            <p class="field-hint">
              访问凭证仅保存在当前浏览器会话中，不写入前端源码
            </p></el-form-item
          ><el-form-item label="用户标识"
            ><el-input
              v-model="form.userId"
              maxlength="64"
              placeholder="例如 user123"
              :disabled="testing"
            />
            <p class="field-hint">
              用于关联订单与偏好；演示数据库中的用户为 user123
            </p></el-form-item
          >
          <div class="settings-switch">
            <div>
              <strong>流式响应</strong>
              <p>让回答逐字出现，沟通更自然</p>
            </div>
            <el-switch
              v-model="form.stream"
              aria-label="启用流式响应"
              :disabled="testing"
            />
          </div>
          <div class="settings-actions">
            <el-button :loading="testing" @click="test"
              ><AppIcon name="Connection" :size="16" />保存并检测</el-button
            ><el-button type="primary" :disabled="testing" @click="saveSettings"
              >保存设置<AppIcon name="Check" :size="16"
            /></el-button></div
        ></el-form>
      </section>
      <div class="settings-right">
        <section class="panel service-panel">
          <div class="panel-heading">
            <div>
              <h2>服务状态</h2>
              <p>
                {{
                  testing ? '正在检测服务连接…' : '点击“保存并检测”获取实时状态'
                }}
              </p>
            </div>
            <span
              class="status-orb"
              :class="{ connected: status?.status === 'ok' }"
            ></span>
          </div>
          <p v-if="error" class="error-text settings-error" role="alert">
            {{ error }}
          </p>
          <div v-for="item in services" :key="item.key" class="service-row">
            <span class="service-icon"
              ><AppIcon
                :name="
                  item.key === 'redis'
                    ? 'ChatLineRound'
                    : item.key === 'mysql'
                      ? 'Box'
                      : 'Collection'
                "
                :size="21"
            /></span>
            <div>
              <strong>{{ item.label }}</strong
              ><small>{{ item.description }}</small>
            </div>
            <span class="service-badge" :class="status?.services[item.key]"
              ><i></i
              >{{
                status
                  ? status.services[item.key] === 'online'
                    ? '已连接'
                    : '不可用'
                  : '待检测'
              }}</span
            >
          </div>
        </section>
        <section class="privacy-card">
          <AppIcon name="Lock" :size="25" />
          <h3>你的连接，由你掌控</h3>
          <p>
            聊天记录保存在此浏览器中，访问凭证随浏览器会话保存。共享设备使用结束后，可清除记录并关闭页面。
          </p>
          <button class="text-button" @click="clear">
            清除当前用户的本地记录<AppIcon name="Right" :size="15" />
          </button>
        </section>
        <p class="settings-note">
          <AppIcon
            name="InfoFilled"
            :size="15"
          />连接检测不会调用对话模型，也不会产生对话费用。
        </p>
      </div>
    </div>
  </div>
</template>
