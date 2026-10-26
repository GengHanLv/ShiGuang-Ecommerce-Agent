<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useConnectionStore } from '@/stores/connection'
import { useChatStore } from '@/stores/chat'
import { http, errorMessage } from '@/api/http'
import { checkServices } from '@/api/workspace'
import type { ServiceStatus } from '@/types'
const auth = useAuthStore()
const connection = useConnectionStore()
const chat = useChatStore()
const baseUrl = ref(connection.baseUrl)
const status = ref<ServiceStatus>()
const busy = ref(false)
const error = ref('')
const preference = ref('')
const preferences = ref<{ topic: string; text: string; version: number }[]>([])
const servers = ref<
  { name: string; enabled: boolean; status: string; tools: string[] }[]
>([])
const tasks = ref<
  { id: string; question: string; status: string; stage: string }[]
>([])
const details = ref('')
async function load() {
  try {
    const results = await Promise.all([
      checkServices(),
      http.get('/preferences'),
      http.get('/tasks'),
    ])
    status.value = results[0]
    preferences.value = results[1].data.preferences
    tasks.value = results[2].data.tasks
    if (auth.admin) servers.value = (await http.get('/tools')).data.servers
  } catch (e) {
    error.value = errorMessage(e)
  }
}
async function save() {
  if (chat.busy) {
    ElMessage.warning('请先完成或停止当前回复')
    return
  }
  const value = baseUrl.value.trim().replace(/\/$/, '')
  if (!/^\/(?!\/)/.test(value) && !/^https?:\/\/[^\s/]+/i.test(value)) {
    ElMessage.warning('请填写 /api 或完整的 HTTP(S) 地址')
    return
  }
  connection.baseUrl = value
  busy.value = true
  error.value = ''
  try {
    await auth.refresh()
    if (auth.user) {
      await load()
      ElMessage.success('连接设置已保存')
    }
  } finally {
    busy.value = false
  }
}
async function logout() {
  if (chat.busy) chat.stop()
  await auth.logout()
}
async function addPreference() {
  if (!preference.value.trim()) return
  try {
    await http.post('/preferences', { text: preference.value.trim() })
    preference.value = ''
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}
async function removePreference(item: { topic: string; version: number }) {
  try {
    await http.delete(`/preferences/${encodeURIComponent(item.topic)}`, {
      params: { expected_version: item.version },
    })
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}
async function reloadTools() {
  busy.value = true
  try {
    servers.value = (
      await http.post('/tools/reload', {}, { timeout: 90000 })
    ).data.servers
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    busy.value = false
  }
}
async function toggleServer(item: { name: string; enabled: boolean }) {
  busy.value = true
  try {
    servers.value = (
      await http.put(
        `/tools/servers/${encodeURIComponent(item.name)}`,
        { enabled: !item.enabled },
        { timeout: 90000 },
      )
    ).data.servers
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    busy.value = false
  }
}
async function showTask(id: string) {
  try {
    details.value = JSON.stringify(
      (await http.get(`/tasks/${encodeURIComponent(id)}`)).data,
      null,
      2,
    )
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}
onMounted(load)
</script>
<template>
  <div class="standard-page settings-page">
    <div class="section-header">
      <div>
        <span class="workspace-label">YOUR WORKSPACE</span>
        <h1>账号与服务</h1>
        <p>管理个人偏好，查看连接状态与任务进度。</p>
      </div>
      <el-button @click="logout">退出登录</el-button>
    </div>
    <p v-if="error" class="inline-alert" role="alert">{{ error }}</p>
    <div class="settings-columns">
      <section class="panel connection-panel">
        <div class="panel-heading">
          <div>
            <h2>服务连接</h2>
            <p>
              {{ auth.user?.username }} ·
              {{ auth.admin ? '管理员' : '个人账号' }}
            </p>
          </div>
        </div>
        <el-form label-position="top" @submit.prevent="save"
          ><el-form-item label="后端地址"
            ><el-input
              v-model="baseUrl"
              placeholder="/api 或 http://127.0.0.1:8001"
          /></el-form-item>
          <p class="field-hint">
            默认 /api 转发到本机 8001。订单与记忆归属当前登录账号。
          </p>
          <div class="settings-switch">
            <div>
              <strong>流式回复</strong>
              <p>逐字呈现回答</p>
            </div>
            <el-switch v-model="connection.stream" aria-label="启用流式响应" />
          </div>
          <el-button type="primary" native-type="submit" :loading="busy"
            >保存并检测</el-button
          ></el-form
        >
        <div class="service-list">
          <div
            v-for="(value, key) in status?.services"
            :key="key"
            class="service-row"
          >
            <strong>{{ key }}</strong
            ><el-tag :type="value === 'online' ? 'success' : 'warning'">{{
              value === 'online' ? '已连接' : '暂不可用'
            }}</el-tag>
          </div>
        </div>
      </section>
      <section class="panel preference-panel">
        <div class="panel-heading">
          <div>
            <h2>个人偏好</h2>
            <p>随时修改或移除当前有效的偏好。</p>
          </div>
        </div>
        <el-input
          v-model="preference"
          maxlength="300"
          placeholder="例如：以后都晚上收货"
          @keyup.enter="addPreference"
        /><el-button class="preference-add" @click="addPreference"
          >保存偏好</el-button
        ><el-empty
          v-if="!preferences.length"
          description="还没有保存偏好"
          :image-size="60"
        />
        <div
          v-for="item in preferences"
          :key="item.topic"
          class="preference-row"
        >
          <span>{{ item.text }}</span
          ><el-button text type="danger" @click="removePreference(item)"
            >移除</el-button
          >
        </div>
      </section>
    </div>
    <section v-if="auth.admin" class="panel management-panel">
      <div class="panel-heading">
        <div>
          <h2>MCP 工具服务</h2>
          <p>查看已配置的只读工具，按需启用或停用。</p>
        </div>
        <el-button :loading="busy" @click="reloadTools">重新加载</el-button>
      </div>
      <div v-for="server in servers" :key="server.name" class="mcp-row">
        <div>
          <strong>{{ server.name }}</strong>
          <p>
            {{ server.status }} ·
            {{ server.tools.join('、') || '暂无可用工具' }}
          </p>
        </div>
        <el-button :disabled="busy" @click="toggleServer(server)">{{
          server.enabled ? '停用' : '启用'
        }}</el-button>
      </div>
    </section>
    <section class="panel management-panel">
      <div class="panel-heading">
        <div>
          <h2>最近任务</h2>
          <p>查看执行阶段和已完成工具。中断的会话可在聊天中继续处理。</p>
        </div>
        <el-button @click="load">刷新</el-button>
      </div>
      <el-table :data="tasks" empty-text="暂无任务"
        ><el-table-column
          prop="question"
          label="问题"
          min-width="200"
          show-overflow-tooltip
        /><el-table-column
          prop="status"
          label="状态"
          width="125"
        /><el-table-column
          prop="stage"
          label="阶段"
          width="110"
        /><el-table-column label="记录" width="90"
          ><template #default="scope"
            ><el-button text @click="showTask(scope.row.id)"
              >查看</el-button
            ></template
          ></el-table-column
        ></el-table
      >
      <pre v-if="details" class="task-details">{{ details }}</pre>
    </section>
  </div>
</template>
<style scoped>
.preference-panel {
  padding: 28px;
}
.preference-add {
  margin: 14px 0;
}
.preference-row {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: center;
  padding: 14px 0;
  border-bottom: 1px solid #edf1e8;
  line-height: 1.8;
  font-size: 15px;
}
.management-panel {
  padding: 28px;
  margin-top: 24px;
}
.mcp-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 0;
  gap: 20px;
  border-top: 1px solid #edf1e8;
}
.mcp-row p {
  margin-top: 7px;
  color: #7e8878;
  font-size: 13px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}
.task-details {
  padding: 18px;
  margin-top: 20px;
  background: #f5f7f1;
  border-radius: 12px;
  overflow: auto;
  font-size: 13px;
  line-height: 1.8;
  max-height: 350px;
}
.service-list {
  margin-top: 24px;
}
.service-row {
  justify-content: space-between;
}
.auth-loading {
  padding: 20vh 24px;
  text-align: center;
}
</style>
