<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import AppIcon from '@/components/AppIcon.vue'
import { getKnowledge, uploadKnowledge } from '@/api/workspace'
import { errorMessage } from '@/api/http'
import { useConnectionStore } from '@/stores/connection'
import type { KnowledgeCollection, UploadResult } from '@/types'
const connection = useConnectionStore()
const collections = ref<KnowledgeCollection[]>([])
const loading = ref(false)
const error = ref('')
const selected = ref('product_knowledge')
const file = ref<File>()
const fileList = ref<UploadFile[]>([])
const uploading = ref(false)
const progress = ref(0)
const results = ref<UploadResult[]>([])
const total = computed(() =>
  collections.value.reduce((sum, item) => sum + item.chunks, 0),
)
async function refresh() {
  if (!connection.apiKey) {
    error.value = '连接客服服务后，即可查看与维护知识库'
    return
  }
  loading.value = true
  error.value = ''
  try {
    collections.value = await getKnowledge()
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}
function choose(upload: UploadFile) {
  if (!upload.raw) return
  if (
    !/\.(pdf|txt|docx)$/i.test(upload.name) ||
    upload.size! > 10 * 1024 * 1024 ||
    !upload.size
  ) {
    ElMessage.warning('请选择非空的 PDF、TXT 或 DOCX 文件，大小不超过 10MB')
    fileList.value = []
    file.value = undefined
    return
  }
  file.value = upload.raw
}
function onExceed() {
  ElMessage.warning('每次上传一份文件，请先移除当前文件')
}
function removeFile() {
  file.value = undefined
}
async function upload() {
  if (!file.value || uploading.value) return
  uploading.value = true
  progress.value = 0
  try {
    const result = await uploadKnowledge(file.value, selected.value, (p) => {
      progress.value = p
    })
    results.value.unshift(result)
    file.value = undefined
    fileList.value = []
    ElMessage.success(`已入库 ${result.chunks} 个知识片段`)
    await refresh()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    uploading.value = false
  }
}
onMounted(refresh)
</script>
<template>
  <div class="standard-page">
    <div class="section-header">
      <div>
        <span class="workspace-label">KNOWLEDGE LIBRARY</span>
        <h1>把知识，变成好回答</h1>
        <p>上传商品资料与常见问题，让拾光更懂你的业务。</p>
      </div>
      <el-button :loading="loading" @click="refresh"
        ><AppIcon name="Refresh" :size="16" />刷新知识库</el-button
      >
    </div>
    <div v-if="error" class="inline-alert">
      <AppIcon name="InfoFilled" :size="18" /><span>{{ error }}</span
      ><router-link v-if="!connection.apiKey" to="/settings"
        >前往设置</router-link
      >
    </div>
    <div class="knowledge-stats">
      <div class="stat-card">
        <span class="stat-icon green"
          ><AppIcon name="Collection" :size="24"
        /></span>
        <div>
          <span>知识片段总数</span
          ><strong
            >{{ error || loading ? '—' : total }}<small>个片段</small></strong
          >
        </div>
      </div>
      <div
        v-for="item in [
          { name: 'product_knowledge', label: '商品知识', icon: 'Box' },
          { name: 'faq', label: '常见问题', icon: 'ChatLineRound' },
        ] as const"
        :key="item.name"
        class="stat-card"
      >
        <span
          class="stat-icon"
          :class="item.name === 'faq' ? 'purple' : 'orange'"
          ><AppIcon :name="item.icon" :size="24"
        /></span>
        <div>
          <span>{{ item.label }}</span
          ><strong
            >{{
              error || loading
                ? '—'
                : (collections.find((c) => c.name === item.name)?.chunks ?? 0)
            }}<small>个片段</small></strong
          >
        </div>
      </div>
    </div>
    <div class="knowledge-columns">
      <section class="panel upload-panel">
        <div class="panel-heading">
          <div>
            <h2>添加新知识</h2>
            <p>一份资料，为每一次回答多一份依据</p>
          </div>
          <AppIcon name="Document" :size="23" />
        </div>
        <label class="field-label" for="collection">知识分类</label
        ><el-select
          id="collection"
          v-model="selected"
          :disabled="uploading"
          aria-label="知识分类"
          ><el-option
            label="商品知识 · 参数、规格与功能"
            value="product_knowledge" /><el-option
            label="常见问题 · 服务与售后政策"
            value="faq" /></el-select
        ><el-upload
          v-model:file-list="fileList"
          class="knowledge-upload"
          drag
          :auto-upload="false"
          :limit="1"
          accept=".pdf,.txt,.docx"
          :disabled="uploading"
          :on-change="choose"
          :on-remove="removeFile"
          :on-exceed="onExceed"
          ><span class="upload-illustration"
            ><AppIcon name="UploadFilled" :size="34" /></span
          ><strong>拖拽文件到这里，或 <em>点击选择</em></strong>
          <p>支持 PDF、TXT、DOCX，单个文件不超过 10MB</p></el-upload
        >
        <div v-if="uploading" class="upload-progress">
          <el-progress
            :percentage="progress"
            :stroke-width="5"
            :show-text="false"
          /><span>{{
            progress < 100
              ? `正在上传 ${progress}%`
              : '文件已上传，正在解析与向量化，请稍候…'
          }}</span>
        </div>
        <div class="upload-footer">
          <span><AppIcon name="Lock" :size="14" />资料仅用于你的知识库</span
          ><el-button
            type="primary"
            :loading="uploading"
            :disabled="!file || !connection.apiKey"
            @click="upload"
            >{{ uploading ? '正在处理' : '开始入库'
            }}<AppIcon v-if="!uploading" name="Right" :size="16"
          /></el-button>
        </div>
      </section>
      <aside class="knowledge-guide">
        <span class="guide-symbol">✳</span>
        <h2>好的知识，<br />让答案更有底气。</h2>
        <p>上传的文本会被自动拆分为知识片段，助手会在需要时检索相关内容。</p>
        <div class="guide-step">
          <span>01</span>
          <div>
            <strong>选对分类</strong>
            <p>商品信息放进商品知识，<br />服务政策放进常见问题。</p>
          </div>
        </div>
        <div class="guide-step">
          <span>02</span>
          <div>
            <strong>保持内容清晰</strong>
            <p>使用可提取文字的文档，<br />扫描 PDF 请先进行 OCR。</p>
          </div>
        </div>
        <div class="guide-step">
          <span>03</span>
          <div>
            <strong>开始一轮对话</strong>
            <p>入库完成后，提出相关问题，<br />检验回答是否符合预期。</p>
          </div>
        </div>
      </aside>
    </div>
    <section class="panel recent-uploads">
      <div class="panel-heading">
        <div>
          <h2>本次上传记录</h2>
          <p>仅展示当前页面成功完成的入库记录</p>
        </div>
        <span class="count-tag">{{ results.length }}</span>
      </div>
      <div v-if="!results.length" class="upload-empty">
        <AppIcon name="FolderOpened" :size="30" /><span
          >还没有新的知识加入，上传第一份资料吧</span
        >
      </div>
      <div v-for="(item, index) in results" :key="index" class="upload-result">
        <span class="file-icon"><AppIcon name="Document" :size="22" /></span>
        <div>
          <strong>{{ item.filename }}</strong
          ><small
            >{{ item.collection === 'faq' ? '常见问题' : '商品知识' }} ·
            {{ item.chunks }} 个片段</small
          >
        </div>
        <span class="success-label"
          ><AppIcon name="CircleCheck" :size="15" />已入库</span
        >
      </div>
    </section>
  </div>
</template>
