<script setup lang="ts">
import { ref } from 'vue'
import BrandMark from '@/components/BrandMark.vue'
import { useAuthStore } from '@/stores/auth'
import { useConnectionStore } from '@/stores/connection'
import { errorMessage } from '@/api/http'
const auth = useAuthStore()
const connection = useConnectionStore()
const username = ref('')
const password = ref('')
const registering = ref(false)
const busy = ref(false)
const error = ref('')
function toggleMode() {
  registering.value = !registering.value
  error.value = ''
}
async function submit() {
  busy.value = true
  error.value = ''
  try {
    if (registering.value) await auth.register(username.value, password.value)
    else await auth.login(username.value, password.value)
    password.value = ''
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <main class="login-page">
    <section class="login-intro">
      <BrandMark /><span>SERVICE STUDIO</span>
      <h1>让每一次咨询，<br />都有可靠的回应。</h1>
      <p>查订单、了解好物、记住偏好。登录后，继续你的专属会话。</p>
      <div class="login-tags">
        <span>商品知识</span><span>联网查证</span><span>个人偏好</span>
      </div>
    </section>
    <section class="login-card">
      <h2>{{ registering ? '创建你的账号' : '欢迎回来' }}</h2>
      <p>
        {{
          registering
            ? '创建独立账户，订单与记忆按账号隔离。'
            : '登录拾光，继续上次的沟通。'
        }}
      </p>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名"
          ><el-input
            v-model="username"
            autocomplete="username"
            maxlength="40"
            placeholder="3至40位字母、数字或下划线"
            :disabled="busy"
        /></el-form-item>
        <el-form-item label="密码"
          ><el-input
            v-model="password"
            type="password"
            show-password
            :autocomplete="registering ? 'new-password' : 'current-password'"
            placeholder="至少10位密码"
            :disabled="busy"
        /></el-form-item>
        <details class="login-connection">
          <summary>服务连接</summary>
          <el-input
            v-model="connection.baseUrl"
            aria-label="后端地址"
            placeholder="/api"
            :disabled="busy"
          />
        </details>
        <p v-if="error" class="login-error" role="alert">{{ error }}</p>
        <el-button
          class="login-submit"
          type="primary"
          native-type="submit"
          :loading="busy"
          >{{ registering ? '注册并登录' : '登录' }}</el-button
        >
      </el-form>
      <button class="login-toggle" @click="toggleMode">
        {{ registering ? '已有账号？返回登录' : '还没有账号？创建账户' }}
      </button>
      <p class="login-note">首次使用的管理员账号配置见项目 README。</p>
    </section>
  </main>
</template>
<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  align-items: center;
  gap: 60px;
  padding: 64px max(6vw, 24px);
  background:
    radial-gradient(ellipse at 10% 10%, #e5eddd, transparent 65%), #f7f8f3;
  color: #263c31;
}
.login-intro {
  max-width: 600px;
}
.login-intro > span {
  display: block;
  margin: 20px 0;
  color: #71836e;
  letter-spacing: 3px;
  font-size: 13px;
}
.login-intro h1 {
  font-size: clamp(30px, 4vw, 52px);
  line-height: 1.5;
  letter-spacing: -1px;
}
.login-intro p {
  margin-top: 24px;
  font-size: 16px;
  color: #687566;
  line-height: 1.9;
}
.login-tags {
  display: flex;
  gap: 10px;
  margin-top: 32px;
}
.login-tags span {
  padding: 9px 14px;
  border: 1px solid #d4dfcd;
  border-radius: 30px;
  font-size: 13px;
  color: #65745f;
}
.login-card {
  width: min(100%, 460px);
  padding: 40px;
  border: 1px solid #e0e7d9;
  border-radius: 26px;
  background: #ffffffed;
  box-shadow: 0 20px 70px #5169460d;
}
.login-card h2 {
  font-size: 28px;
  margin-bottom: 12px;
}
.login-card > p {
  color: #7c8579;
  line-height: 1.8;
  font-size: 14px;
  margin-bottom: 28px;
}
.login-connection {
  font-size: 13px;
  color: #7b8876;
  margin: 8px 0 20px;
}
.login-connection summary {
  cursor: pointer;
  margin-bottom: 12px;
}
.login-submit {
  width: 100%;
  height: 44px;
  margin-top: 8px;
}
.login-toggle {
  margin-top: 24px;
  background: none;
  border: 0;
  color: #517348;
  cursor: pointer;
}
.login-error {
  color: #b7493c;
  font-size: 14px;
  line-height: 1.7;
  margin: 12px 0;
}
.login-card .login-note {
  font-size: 12px;
  margin: 24px 0 0;
  color: #929b8e;
}
@media (max-width: 760px) {
  .login-page {
    grid-template-columns: 1fr;
    gap: 28px;
    padding: 28px 20px;
  }
  .login-intro h1 {
    font-size: 30px;
  }
  .login-intro > p,
  .login-tags {
    display: none;
  }
  .login-card {
    padding: 28px;
    width: 100%;
  }
}
</style>
